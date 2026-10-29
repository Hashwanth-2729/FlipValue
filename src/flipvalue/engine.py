"""Valuation engine `comparables-v1`. The only place where prices are computed; every channel uses it.

Method (docs/VALUATION_METHODOLOGY.md):
* Comparables = observations for the exact model, storage, region and grade, observed within the freshness window.
* One price basis per estimate, never mixed: completed sales; if fewer than MIN_OBSERVATIONS, asking prices
  (labelled); then FlipValue modelled estimates (labelled, latest month only, flipvalue/estimates.py); synthetic
  data only when mock data is allowed (never in production).
* value = median; range = 10th-90th percentile with >= 10 observations, otherwise min-max; < 3 = no estimate.
* Faults and device age do not adjust the price (no evidence for an adjustment); this is disclosed.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from flipvalue import catalogue
from flipvalue.config import REGION_CURRENCY
from flipvalue.db.models import DeviceModel, Observation, Source

METHOD_VERSION = "comparables-v1"
MIN_OBSERVATIONS = 3
DECILE_MIN = 10
EVIDENCE_BACKED_MAX_AGE_DAYS = 90
RESALE_BASES = ("completed_sale", "listing")
ESTIMATE_BASES = ("estimate", "estimate_buyback")
REPAIRED_GRADE = {"faulty": "good"}  # a repair restores function, not cosmetics
MOCK_WARNING = "MOCK DATA: these values come from synthetic development data and are not real market prices."
ESTIMATE_WARNING = ("FlipValue estimate: modelled from the launch price and approximate current price ranges for "
                    "this phone, not from observed sales. Treat it as a rough guide.")
BASIS_LABEL = {
    "completed_sale": "completed sales",
    "listing": "asking prices",
    "trade_in": "trade-in offers",
    "synthetic": "synthetic (mock) observations",
    "estimate": "FlipValue modelled estimates",
    "estimate_buyback": "FlipValue modelled buyback estimates",
}


class EngineError(Exception):
    """A request the engine cannot value. `code` matches the API error codes."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Estimate:
    value: Decimal
    low: Decimal
    high: Decimal
    range_method: str           # p10_p90 | min_max
    basis: str                  # completed_sale | listing | trade_in | estimate | estimate_buyback | synthetic
    quality: str                # evidence_backed | limited | modelled
    count: int
    oldest: date
    newest: date
    source_ids: tuple[str, ...]
    observation_ids: tuple[int, ...]

    @property
    def is_mock(self) -> bool:
        return self.basis == "synthetic"

    @property
    def is_estimate(self) -> bool:
        return self.basis in ESTIMATE_BASES


@dataclass(frozen=True)
class DeviceMatch:
    model: DeviceModel
    storage_gb: int
    storage_inferred: bool      # only one storage variant exists, so it was not needed


@dataclass
class Outcome:
    device: DeviceMatch
    region: str
    currency: str
    grade: str
    faults: tuple[str, ...]
    repair_type: str | None
    as_is: Estimate | None
    as_is_gap: str | None
    target_grade: str | None
    after_repair: Estimate | None
    after_repair_gap: str | None
    trade_in: Estimate | None
    warnings: list[str] = field(default_factory=list)
    method_version: str = METHOD_VERSION

    @property
    def used(self) -> list[Estimate]:
        return [e for e in (self.as_is, self.after_repair) if e is not None]

    @property
    def mock(self) -> bool:
        return any(e.is_mock for e in self.used)

    @property
    def status(self) -> str:
        limited = any(e.quality != "evidence_backed" for e in self.used)
        missing_repair = self.repair_type is not None and self.after_repair is None
        return "partial" if limited or missing_repair else "ok"

    @property
    def data_timestamp(self) -> date | None:
        return max((e.newest for e in self.used), default=None)

    def valuation_id(self, request: dict) -> str:
        """Deterministic: same request and same evidence give the same id."""
        evidence = sorted(i for e in self.used for i in e.observation_ids)
        canonical = json.dumps({"request": request, "evidence": evidence, "method": self.method_version},
                               sort_keys=True)
        return "val_" + hashlib.sha256(canonical.encode()).hexdigest()[:24]


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def summarise(rows: list[tuple[int, Decimal, date, str]], basis: str, today: date) -> Estimate:
    """rows: (observation id, price, observed_at, source id); at least MIN_OBSERVATIONS of them."""
    prices = sorted(Decimal(r[1]) for r in rows)
    value = statistics.median(prices)
    if len(prices) >= DECILE_MIN:
        deciles = statistics.quantiles(prices, n=10, method="inclusive")
        low, high, method = deciles[0], deciles[8], "p10_p90"
    else:
        low, high, method = prices[0], prices[-1], "min_max"
    dates = [r[2] for r in rows]
    newest = max(dates)
    backed = (basis in ("completed_sale", "synthetic") and len(rows) >= DECILE_MIN
              and (today - newest).days <= EVIDENCE_BACKED_MAX_AGE_DAYS)
    quality = "modelled" if basis in ESTIMATE_BASES else "evidence_backed" if backed else "limited"
    return Estimate(
        value=_money(value), low=_money(min(low, value)), high=_money(max(high, value)), range_method=method,
        basis=basis, quality=quality, count=len(rows),
        oldest=min(dates), newest=newest, source_ids=tuple(sorted({r[3] for r in rows})),
        observation_ids=tuple(sorted(r[0] for r in rows)),
    )


class Engine:
    def __init__(self, freshness_days: int, include_mock: bool, clock: Callable[[], date] = date.today) -> None:
        self.freshness_days = freshness_days
        self.include_mock = include_mock
        self.clock = clock

    # --- building blocks ---------------------------------------------------------------------

    def check_market(self, region: str, currency: str) -> None:
        expected = REGION_CURRENCY.get(region)
        if expected is None:
            supported = ", ".join(sorted(REGION_CURRENCY))
            raise EngineError("unsupported_region", f"Region {region} is not supported (supported: {supported}).")
        if currency != expected:
            raise EngineError("unsupported_currency",
                              f"Region {region} is valued in {expected} only; FlipValue does not convert currencies.")

    def match_storage(self, session: Session, model: DeviceModel, storage_gb: int | None) -> DeviceMatch:
        known = catalogue.variants(session, model.id)
        if storage_gb is not None:
            if storage_gb not in known:
                listed = ", ".join(f"{s} GB" for s in known)
                raise EngineError("no_data_for_condition",
                                  f"{model.name} is not catalogued with {storage_gb} GB (known: {listed}).")
            return DeviceMatch(model, storage_gb, storage_inferred=False)
        if len(known) == 1:
            return DeviceMatch(model, known[0], storage_inferred=True)
        listed = ", ".join(str(s) for s in known)
        raise EngineError("no_data_for_condition",
                          f"storage_gb is required for {model.name}: prices differ by storage ({listed} GB) "
                          "and FlipValue does not mix storage variants.")

    def _rows(self, session: Session, model_id: str, storage_gb: int, region: str, grade: str,
              bases: tuple[str, ...]) -> dict[str, list[tuple[int, Decimal, date, str]]]:
        today = self.clock()
        query = (
            select(Observation.id, Observation.price, Observation.observed_at, Observation.source_id,
                   Source.source_type)
            .join(Source, Source.id == Observation.source_id)
            .where(Observation.model_id == model_id, Observation.storage_gb == storage_gb,
                   Observation.region == region, Observation.grade == grade,
                   Observation.observed_at >= today - timedelta(days=self.freshness_days),
                   Observation.observed_at <= today, Source.source_type.in_(bases))
        )
        if not self.include_mock:
            query = query.where(Observation.is_mock.is_(False))
        grouped: dict[str, list[tuple[int, Decimal, date, str]]] = defaultdict(list)
        for obs_id, price, observed, source_id, basis in session.execute(query):
            grouped[basis].append((obs_id, price, observed, source_id))
        return grouped

    def estimate(self, session: Session, model_id: str, storage_gb: int, region: str, grade: str,
                 bases: tuple[str, ...] = RESALE_BASES) -> tuple[Estimate | None, int]:
        """Best single-basis estimate, and the number of usable observations found if there was none."""
        if bases == RESALE_BASES:  # real data, when present, always wins; then modelled estimates; then mock
            bases = (*RESALE_BASES, "estimate", *(("synthetic",) if self.include_mock else ()))
        grouped = self._rows(session, model_id, storage_gb, region, grade, bases)
        for basis in bases:
            rows = grouped.get(basis, [])
            if basis in ESTIMATE_BASES and rows:  # a modelled estimate is the latest month, not a multi-month mix
                newest = max(r[2] for r in rows)
                rows = [r for r in rows if r[2] == newest]
            if len(rows) >= MIN_OBSERVATIONS:
                return summarise(rows, basis, self.clock()), len(rows)
        return None, max((len(r) for r in grouped.values()), default=0)

    # --- full valuation ----------------------------------------------------------------------

    def valuate(self, session: Session, model: DeviceModel, storage_gb: int | None, region: str, currency: str,
                grade: str, faults: tuple[str, ...] = (), repair_type: str | None = None,
                age_months: int | None = None) -> Outcome:
        self.check_market(region, currency)
        device = self.match_storage(session, model, storage_gb)
        label = f"{model.name} {device.storage_gb} GB"

        def gap(found: int, for_grade: str) -> str:
            return (f"Not enough recent price evidence for {label} in grade '{for_grade}' ({region}): "
                    f"{found} usable observation(s) in the last {self.freshness_days} days, "
                    f"{MIN_OBSERVATIONS} needed.")

        as_is, found = self.estimate(session, model.id, device.storage_gb, region, grade)
        outcome = Outcome(device=device, region=region, currency=currency, grade=grade, faults=faults,
                          repair_type=repair_type, as_is=as_is, as_is_gap=None if as_is else gap(found, grade),
                          target_grade=None, after_repair=None, after_repair_gap=None, trade_in=None)
        if repair_type is not None:
            target = REPAIRED_GRADE.get(grade, grade)
            outcome.target_grade = target
            after, found = self.estimate(session, model.id, device.storage_gb, region, target)
            outcome.after_repair = after
            if after is None:
                outcome.after_repair_gap = gap(found, target)
        outcome.trade_in, _ = self.estimate(session, model.id, device.storage_gb, region, grade, ("trade_in",))
        outcome.warnings = self._warnings(outcome, age_months)
        return outcome

    def _warnings(self, outcome: Outcome, age_months: int | None) -> list[str]:
        warnings: list[str] = []
        if outcome.mock:
            warnings.append(MOCK_WARNING)
        if any(e.is_estimate for e in outcome.used):
            warnings.append(ESTIMATE_WARNING)
        today = self.clock()
        for name, est in (("as_is", outcome.as_is), ("after_repair", outcome.after_repair)):
            if est is None or est.is_estimate:
                continue
            if est.basis == "listing":
                warnings.append(f"{name} is based on asking prices, not completed sales; "
                                "actual sale prices are often lower.")
            if est.count < DECILE_MIN:
                warnings.append(f"{name} is based on only {est.count} recent observations.")
            if (today - est.newest).days > EVIDENCE_BACKED_MAX_AGE_DAYS:
                warnings.append(f"{name}: the newest observation is from {est.newest.isoformat()}.")
        if outcome.faults:
            warnings.append(f"Fault categories are not priced separately; the value reflects grade "
                            f"'{outcome.grade}' only.")
        if age_months is not None:
            warnings.append("Device age is not used; the estimate reflects recent prices for this model.")
        if outcome.repair_type is not None:
            if outcome.after_repair is not None:
                warnings.append(f"after_repair assumes the {outcome.repair_type} is done well and the phone then "
                                f"grades '{outcome.target_grade}'.")
            else:
                warnings.append(f"No sufficient price data for grade '{outcome.target_grade}' after "
                                f"{outcome.repair_type}; after_repair is not available.")
        return warnings[:20]

    # --- catalogue evidence and trends ---------------------------------------------------------

    def evidence_status(self, session: Session) -> dict[tuple[str, str], str]:
        """Per (model_id, region): evidence_backed | limited | estimated | mock_only | insufficient (absent =
        insufficient)."""
        today = self.clock()
        rows = session.execute(
            select(Observation.model_id, Observation.region, Observation.grade, Observation.storage_gb,
                   Source.source_type, func.count(), func.max(Observation.observed_at))
            .join(Source, Source.id == Observation.source_id)
            .where(Observation.observed_at >= today - timedelta(days=self.freshness_days),
                   Observation.observed_at <= today)
            .group_by(Observation.model_id, Observation.region, Observation.grade, Observation.storage_gb,
                      Source.source_type)
        )
        rank = {"insufficient": 0, "mock_only": 1, "estimated": 2, "limited": 3, "evidence_backed": 4}
        status: dict[tuple[str, str], str] = {}
        for model_id, region, _grade, _storage, basis, count, newest in rows:
            if basis == "completed_sale" and count >= DECILE_MIN and \
                    (today - newest).days <= EVIDENCE_BACKED_MAX_AGE_DAYS:
                level = "evidence_backed"
            elif basis in RESALE_BASES and count >= MIN_OBSERVATIONS:
                level = "limited"
            elif basis == "estimate" and count >= MIN_OBSERVATIONS:
                level = "estimated"
            elif basis == "synthetic" and self.include_mock and count >= MIN_OBSERVATIONS:
                level = "mock_only"
            else:
                level = "insufficient"
            key = (model_id, region)
            if rank[level] > rank[status.get(key, "insufficient")]:
                status[key] = level
        return status

    def trend(self, session: Session, model_id: str, storage_gb: int, region: str, grade: str,
              months: int = 24) -> dict[str, list[dict]]:
        """Monthly medians of genuine observations, plus the modelled estimate curve as its own labelled series.
        Synthetic data is never shown as history.

        A month appears only with >= MIN_OBSERVATIONS observations of that basis.
        """
        since = self.clock() - timedelta(days=31 * months)
        rows = session.execute(
            select(Observation.price, Observation.observed_at, Source.source_type)
            .join(Source, Source.id == Observation.source_id)
            .where(Observation.model_id == model_id, Observation.storage_gb == storage_gb,
                   Observation.region == region, Observation.grade == grade, Observation.observed_at >= since,
                   Observation.observed_at <= self.clock(), Observation.is_mock.is_(False),
                   Source.source_type.in_((*RESALE_BASES, "trade_in", "estimate")))
        )
        buckets: dict[str, dict[str, list[Decimal]]] = defaultdict(lambda: defaultdict(list))
        for price, observed, basis in rows:
            buckets[basis][observed.strftime("%Y-%m")].append(Decimal(price))
        series: dict[str, list[dict]] = {}
        for basis, months_map in buckets.items():
            points = [{"month": m, "median": _money(statistics.median(p)), "count": len(p)}
                      for m, p in sorted(months_map.items()) if len(p) >= MIN_OBSERVATIONS]
            if points:
                series[basis] = points
        return series
