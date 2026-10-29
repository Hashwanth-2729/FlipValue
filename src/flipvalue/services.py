"""Channel adapters around the engine: partner contract output and public website output."""

from __future__ import annotations

import statistics
from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from flipvalue import catalogue
from flipvalue.condition import derive
from flipvalue.db.models import DeviceModel, MarketplaceOffer, Source
from flipvalue.engine import BASIS_LABEL, DECILE_MIN, MIN_OBSERVATIONS, Engine, EngineError, Estimate, Outcome
from flipvalue.errors import ApiError
from flipvalue.marketplace.matching import PRIMARY
from flipvalue.marketplace.service import OfferPolicy, current_offers
from flipvalue.schemas import (
    ApiDevice,
    ApiValuationRequest,
    Condition,
    ConditionOut,
    DeviceOut,
    EstimateOut,
    EvidenceSource,
    ProductRef,
    PublicValuation,
    PublicValuationRequest,
    PublicValueTypes,
    RepairComparison,
    SourceRef,
    Valuation,
    ValuationRequest,
    ValuationV1,
    ValueBand,
    ValueEstimateV1,
)

ERROR_STATUS = {"unsupported_region": 422, "unsupported_currency": 422, "no_data_for_condition": 404,
                "unsupported_model": 404}
REGION_NAME = {"IN": "India", "US": "the United States"}


def _engine_call(fn, *args, **kwargs) -> Outcome:
    try:
        return fn(*args, **kwargs)
    except EngineError as exc:
        raise ApiError(ERROR_STATUS[exc.code], exc.code, exc.message) from exc


# --- partner (FixMyTech contract) ------------------------------------------------------------


def _band(e: Estimate) -> ValueBand:
    return ValueBand(value=float(e.value), low=float(e.low), high=float(e.high))


def partner_valuation(session: Session, engine: Engine, body: ValuationRequest) -> Valuation:
    try:
        engine.check_market(body.region, body.currency)
    except EngineError as exc:
        raise ApiError(422, exc.code, exc.message) from exc
    device = body.device
    model = catalogue.find_model(session, device.manufacturer, device.model)
    if model is None:
        raise ApiError(404, "unsupported_model", f"No valuation data for {device.manufacturer} {device.model}.")
    repair = body.repair_scenario.repair_type if body.repair_scenario else None
    outcome = _engine_call(engine.valuate, session, model, device.storage_gb, body.region, body.currency,
                           body.condition.grade, tuple(dict.fromkeys(body.condition.faults)), repair,
                           device.age_months)
    if outcome.as_is is None:
        raise ApiError(404, "no_data_for_condition", outcome.as_is_gap or "No price data.")
    assert outcome.data_timestamp is not None
    return Valuation(
        valuation_id=outcome.valuation_id(body.model_dump(mode="json", exclude_none=True)),
        currency=body.currency,
        as_is=_band(outcome.as_is),
        after_repair=_band(outcome.after_repair) if outcome.after_repair else None,
        data_timestamp=datetime.combine(outcome.data_timestamp, time.min, tzinfo=UTC),
        method=outcome.method_version,
        status=outcome.status,
        warnings=outcome.warnings,
        mock=outcome.mock,
    )


# --- public website ----------------------------------------------------------------------------


def _estimate_out(session: Session, e: Estimate | None) -> EstimateOut | None:
    if e is None:
        return None
    sources = session.scalars(select(Source).where(Source.id.in_(e.source_ids)).order_by(Source.id))
    return EstimateOut(
        value=e.value, low=e.low, high=e.high, range_method=e.range_method, basis=e.basis,
        basis_label=BASIS_LABEL[e.basis], quality=e.quality, observation_count=e.count,
        oldest_observation=e.oldest, newest_observation=e.newest,
        sources=[SourceRef(id=s.id, name=s.name, source_type=s.source_type, verified=s.verified,
                           is_mock=s.is_mock) for s in sources],
    )


def _day(d: date) -> str:
    return f"{d.day} {d:%b %Y}"  # matches the website's date format, e.g. "1 Oct 2026"


def _explain(o: Outcome) -> list[str]:
    lines: list[str] = []
    label = f"{o.device.model.name} {o.device.storage_gb} GB"
    if o.as_is and o.as_is.is_estimate:
        lines.append(f"This is a FlipValue estimate for a {label} in '{o.grade}' condition in "
                     f"{REGION_NAME[o.region]} ({o.as_is.newest:%B %Y}). There are not yet enough real sales of "
                     "this phone, so the price is modelled instead of observed.")
        lines.append("How: approximate current price ranges for this phone (new, refurbished and used, from public "
                     "listings and price checks) set the price for each condition — excellent near the top of the "
                     "used range, fair near the bottom. The range shown is about ±6%.")
        lines.append("Treat it as a rough guide: a buyer's offer can differ, especially for poor or faulty phones.")
    elif o.as_is:
        e = o.as_is
        lines.append(f"Based on {e.count} {BASIS_LABEL[e.basis]} of a {label} in '{o.grade}' condition in "
                     f"{REGION_NAME[o.region]}, dated {_day(e.oldest)} to {_day(e.newest)}.")
        lines.append("The estimate is the middle (median) price. " + (
            "The range covers the middle 80% of prices (10th to 90th percentile)."
            if e.range_method == "p10_p90" else
            f"With fewer than {DECILE_MIN} observations, the range is simply the lowest to the highest price."))
        if e.is_mock:
            lines.append("Evidence quality: none — these are synthetic observations, not market prices.")
        else:
            lines.append("Evidence quality: " + (
                "evidence-backed (10 or more completed sales within the last 90 days)."
                if e.quality == "evidence_backed"
                else "limited (few observations, older data, or asking prices rather than sales)."))
    if o.device.storage_inferred:
        lines.append(f"This model is only catalogued with {o.device.storage_gb} GB of storage.")
    lines.append("Reported faults and the phone's age do not change the estimate: there is not yet evidence for "
                 "how much they move prices. The grade is what matters.")
    if o.repair_type and o.after_repair:
        lines.append(f"The after-repair value uses prices of phones in '{o.target_grade}' condition and assumes "
                     "the repair is done well. It does not include the repair cost.")
    return lines


def public_valuation(session: Session, engine: Engine, req: PublicValuationRequest,
                     policy: OfferPolicy | None = None) -> PublicValuation:
    model = session.get(DeviceModel, req.device.model_id)
    if model is None:
        raise ApiError(404, "unsupported_model", "That model is not in the FlipValue catalogue.")
    derivation = derive(req.assessment)
    outcome = _engine_call(engine.valuate, session, model, req.device.storage_gb, req.region, req.currency,
                           derivation.grade, tuple(derivation.faults), req.repair_type)
    types = None
    if policy is not None:
        types = PublicValueTypes(buyback=_buyback(session, engine, outcome),
                                 refurbished_retail=_refurbished(session, outcome, policy),
                                 original_retail=_original_retail(session, outcome, policy))
    return PublicValuation(
        value_types=types,
        valuation_id=outcome.valuation_id(req.model_dump(mode="json", exclude_none=True)),
        method_version=outcome.method_version,
        mock=outcome.mock,
        generated_at=datetime.now(UTC),
        region=req.region,
        currency=req.currency,
        status="unavailable" if outcome.as_is is None else outcome.status,
        device=DeviceOut(model_id=model.id, manufacturer=model.manufacturer, name=model.name,
                         storage_gb=outcome.device.storage_gb, storage_inferred=outcome.device.storage_inferred),
        condition=ConditionOut(grade=derivation.grade, faults=derivation.faults, reasons=derivation.reasons,
                               uncertainties=derivation.uncertainties, not_used=derivation.not_used,
                               safety=derivation.safety),
        as_is=_estimate_out(session, outcome.as_is),
        as_is_unavailable_reason=outcome.as_is_gap,
        repair_type=req.repair_type,
        assumed_grade_after_repair=outcome.target_grade,
        after_repair=_estimate_out(session, outcome.after_repair),
        after_repair_unavailable_reason=outcome.after_repair_gap,
        trade_in=_estimate_out(session, outcome.trade_in),
        explanation=_explain(outcome),
        warnings=[w for w in outcome.warnings if not w.startswith("after_repair assumes")],
    )


# --- developer API (/api/v1/valuations) ------------------------------------------------------------------------

BUYBACK_BASES = ("dealer_offer", "trade_in", "estimate_buyback")  # real quotes first, then the modelled estimate
OFFER_BASIS_LABEL = {"refurbished_offers": "current refurbished retail offers", "mrp": "retailer-supplied MRP"}


def confidence_of(e: Estimate | None) -> str:
    """high: evidence-backed (>= 10 completed sales, newest <= 90 days); medium: >= 10 observations of another
    basis, or 3-9 completed sales; low: anything thinner, asking prices, or synthetic data."""
    if e is None:
        return "insufficient"
    if e.is_mock or e.is_estimate:  # modelled estimates are never more than a rough guide
        return "low"
    if e.quality == "evidence_backed":
        return "high"
    if e.count >= DECILE_MIN or e.basis == "completed_sale":
        return "medium" if e.basis != "listing" else "low"
    return "low"


def _sources(session: Session, ids: tuple[str, ...] | list[str]) -> list[EvidenceSource]:
    return [EvidenceSource(id=s.id, name=s.name, source_type=s.source_type, verified=s.verified, is_mock=s.is_mock)
            for s in session.scalars(select(Source).where(Source.id.in_(ids)).order_by(Source.id))]


def _from_estimate(session: Session, kind: str, e: Estimate | None, gap: str | None) -> ValueEstimateV1:
    if e is None:
        return ValueEstimateV1(type=kind, available=False, confidence="insufficient", reason=gap)
    return ValueEstimateV1(
        type=kind, available=True, value=e.value, low=e.low, high=e.high, basis=e.basis,
        basis_label=BASIS_LABEL.get(e.basis, e.basis.replace("_", " ")), range_method=e.range_method,
        confidence=confidence_of(e), observation_count=e.count, oldest_observation=e.oldest,
        newest_observation=e.newest, sources=_sources(session, e.source_ids),
        reason="Based on asking prices, which are usually above sale prices." if e.basis == "listing" else
        "FlipValue estimate, modelled from approximate price ranges; not observed sales." if e.is_estimate else None,
    )


def _buyback(session: Session, engine: Engine, o: Outcome) -> ValueEstimateV1:
    est, found = engine.estimate(session, o.device.model.id, o.device.storage_gb, o.region, o.grade, BUYBACK_BASES)
    gap = (f"No dealer buyback or trade-in quotes for this phone in grade '{o.grade}' ({found} found, "
           f"{MIN_OBSERVATIONS} needed). Buyback quotes are recorded manually; no buyback provider offers "
           "authorised automated access.")
    return _from_estimate(session, "buyback", est, gap)


def _offer_estimate(session: Session, kind: str, offers: list[tuple[MarketplaceOffer, Source]], amounts: list,
                    basis: str, gap: str) -> ValueEstimateV1:
    if not amounts:
        return ValueEstimateV1(type=kind, available=False, confidence="insufficient", reason=gap)
    values = sorted(Decimal(str(a)) for a in amounts)
    dates = [o.retrieved_at.date() for o, _ in offers]
    n = len(values)
    return ValueEstimateV1(
        type=kind, available=True, value=statistics.median(values).quantize(Decimal("0.01")), low=values[0],
        high=values[-1], basis=basis, basis_label=OFFER_BASIS_LABEL[basis], range_method="min_max",
        confidence="medium" if n >= 5 else "low", observation_count=n, oldest_observation=min(dates),
        newest_observation=max(dates), sources=_sources(session, sorted({s.id for _, s in offers})),
        reason=None if n >= 3 else f"Only {n} current offer(s).",
    )


def _primary_offers(session: Session, o: Outcome, policy: OfferPolicy, condition: str
                    ) -> list[tuple[MarketplaceOffer, Source]]:
    return [(offer, source) for offer, source in
            current_offers(session, o.device.model.id, o.region, policy, policy.now())
            if offer.match_category in PRIMARY and offer.storage_gb == o.device.storage_gb
            and offer.condition == condition and offer.price_type != "buyback_quote"
            and offer.availability != "out_of_stock"]


def _refurbished(session: Session, o: Outcome, policy: OfferPolicy) -> ValueEstimateV1:
    offers = _primary_offers(session, o, policy, "refurbished")
    return _offer_estimate(session, "refurbished_retail", offers, [x.price for x, _ in offers], "refurbished_offers",
                           f"No current refurbished offers for this exact variant (last {policy.max_age_days} days). "
                           "This is what a refurbisher charges, not what a seller receives.")


def _original_retail(session: Session, o: Outcome, policy: OfferPolicy) -> ValueEstimateV1:
    offers = [(x, s) for x, s in _primary_offers(session, o, policy, "new") if x.mrp]
    return _offer_estimate(session, "original_retail", offers, [x.mrp for x, _ in offers], "mrp",
                           "No retailer has supplied an MRP for this exact variant; FlipValue does not use a "
                           "launch price it cannot attribute to a source.")


def resolve_model(session: Session, device: ApiDevice) -> DeviceModel:
    if device.product_id is not None:
        model = session.get(DeviceModel, device.product_id)
    else:
        model = catalogue.find_model(session, device.manufacturer or "", device.model or "")
    if model is None:
        what = device.product_id or f"{device.manufacturer} {device.model}"
        raise ApiError(404, "unsupported_model", f"{what} is not in the FlipValue catalogue (GET /api/v1/products).")
    return model


def api_valuation(session: Session, engine: Engine, body: ApiValuationRequest, policy: OfferPolicy,
                  valuation_id: str) -> ValuationV1:
    try:
        engine.check_market(body.region, body.currency)
    except EngineError as exc:
        raise ApiError(422, exc.code, exc.message) from exc
    model = resolve_model(session, body.device)
    repair = body.repair_scenario.repair_type if body.repair_scenario else None
    faults = tuple(dict.fromkeys(body.condition.faults))
    o = _engine_call(engine.valuate, session, model, body.device.storage_gb, body.region, body.currency,
                     body.condition.grade, faults, repair, body.device.age_months)

    private = _from_estimate(session, "private_sale", o.as_is, o.as_is_gap)
    after = _from_estimate(session, "after_repair", o.after_repair, o.after_repair_gap) if repair else None
    comparison = None
    if repair and o.target_grade:
        uplift = (o.after_repair.value - o.as_is.value) if (o.as_is and o.after_repair) else None
        comparison = RepairComparison(
            repair_type=repair, assumed_grade_after_repair=o.target_grade, value_uplift=uplift,
            confidence=min((confidence_of(o.as_is), confidence_of(o.after_repair)), key=CONFIDENCE_ORDER.index),
            note=("Difference between comparable prices in the two grades; it is not a universal percentage and "
                  "does not include the repair cost." if uplift is not None else
                  "Not available: there is not enough price evidence for both the current and the repaired grade."))

    missing, improve = [], []
    if o.as_is is None:
        missing.append(f"comparable prices for grade '{o.grade}'")
    if body.device.storage_gb is None and not o.device.storage_inferred:
        missing.append("storage_gb")
    if not faults:
        improve.append("Report known faults so warnings can mention them (faults do not yet change the value).")
    if o.as_is and o.as_is.basis == "listing":
        improve.append("Completed-sale data for this model would replace asking prices.")
    if o.as_is and o.as_is.count < DECILE_MIN:
        improve.append("More recent comparable observations would narrow the range.")
    limitations = [
        "Values are gross sale prices before selling fees, in the requested currency; no conversion is done.",
        "Condition is as reported by the caller; a buyer inspects the phone.",
        "Faults and device age do not adjust the value: there is no evidence yet for how much they move prices.",
    ]
    assumptions = [f"Grade '{o.grade}' as reported."]
    if o.device.storage_inferred:
        assumptions.append(f"{model.name} is only catalogued with {o.device.storage_gb} GB.")
    if repair and o.target_grade:
        assumptions.append(f"After the {repair.replace('_', ' ')} the phone grades '{o.target_grade}' "
                           "(a repair restores function, not cosmetics).")
    status = "unavailable" if o.as_is is None else o.status
    return ValuationV1(
        id=valuation_id, created_at=datetime.now(UTC), method=o.method_version, status=status, mock=o.mock,
        region=body.region, currency=body.currency,
        product=ProductRef(id=model.id, manufacturer=model.manufacturer, name=model.name,
                           storage_gb=o.device.storage_gb, storage_inferred=o.device.storage_inferred),
        condition=Condition(grade=body.condition.grade, faults=list(faults)),
        private_sale=private, buyback=_buyback(session, engine, o), refurbished_retail=_refurbished(session, o, policy),
        original_retail=_original_retail(session, o, policy), after_repair=after, repair=comparison,
        confidence=private.confidence, data_timestamp=o.data_timestamp, assumptions=assumptions,
        limitations=limitations, missing_data=missing, how_to_improve=improve,
        warnings=o.warnings,
    )


CONFIDENCE_ORDER = ["insufficient", "low", "medium", "high"]
