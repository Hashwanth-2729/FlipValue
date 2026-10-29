"""Refresh offers from providers, compare current prices, and build price history from stored retrievals.

Rules:
* Each provider runs in its own ingestion job; a failure is recorded on that job and never affects other providers.
* Offers are validated, matched to the catalogue (matching.py) and de-duplicated. Unrelated listings are rejected.
* "Current" offers are the latest retrieval of each listing within OFFER_MAX_AGE; their freshness is classified.
* History uses only stored retrievals; nothing is interpolated. Mock (fixture) offers are never used in production.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from flipvalue.config import REGION_CURRENCY
from flipvalue.db.models import (
    DeviceModel,
    IngestionJob,
    MarketplaceOffer,
    PriceAlert,
    RejectedRecord,
    Source,
    WatchlistItem,
    utcnow,
)
from flipvalue.ingestion.sources import register_source
from flipvalue.marketplace.matching import PRIMARY, Match, match_listing, ram_from_title
from flipvalue.marketplace.providers import AMAZON, FLIPKART, PRICE_TYPE, Provider, ProviderError, RawOffer, money

AUTOMATED_SOURCES = (FLIPKART.id, AMAZON.id)  # everything else is recorded by hand or is a fixture

MAX_PRICE = Decimal("10000000")
CONDITIONS = ("new", "refurbished", "used")
PRICE_TYPES = ("new_retail", "refurbished_retail", "used_listing", "buyback_quote")
SELLER_TYPES = ("marketplace_seller", "retailer", "manufacturer", "refurbisher", "dealer")


@dataclass(frozen=True)
class OfferPolicy:
    fresh_hours: int = 24        # retrieved within this many hours = "fresh"
    max_age_days: int = 14       # older offers are not shown as current prices (history only)
    min_refresh_minutes: int = 60  # per provider and product, regardless of how often refresh is called
    include_mock: bool = True
    clock: Callable[[], datetime] = utcnow  # naive UTC "now"; injectable for tests

    def now(self) -> datetime:
        return self.clock()


@dataclass
class ProviderRun:
    source_id: str
    name: str
    status: str            # succeeded | failed | not_configured | skipped_recent
    job_id: int | None = None
    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    error_code: str | None = None
    message: str | None = None


# --- storing -------------------------------------------------------------------------------------------------


def _dedup(source_id: str, offer: RawOffer, retrieved: datetime) -> str:
    ref = offer.provider_product_id or offer.url or offer.title
    basis = "|".join(map(str, (source_id, ref, offer.condition, offer.seller or "", offer.price, retrieved.date())))
    return hashlib.sha256(basis.encode()).hexdigest()


def validate(offer: RawOffer, region: str) -> str | None:
    """A reason to reject the offer, or None."""
    if not offer.title.strip():
        return "title is empty"
    if offer.currency != REGION_CURRENCY.get(region):
        return f"currency {offer.currency or '?'} is not {REGION_CURRENCY.get(region)} for {region}"
    if not (Decimal(0) < offer.price <= MAX_PRICE):
        return "price must be > 0 and plausible"
    if offer.price != offer.price.quantize(Decimal("0.01")):
        return "price has more than 2 decimal places"
    if offer.mrp is not None and offer.mrp < offer.price * Decimal("0.5"):
        return "MRP is implausibly below the price"
    if offer.url and not offer.url.startswith("https://"):
        return "listing URL must be https"
    if offer.condition not in CONDITIONS or offer.price_type not in PRICE_TYPES:
        return "unknown condition or price type"
    if offer.seller_type is not None and offer.seller_type not in SELLER_TYPES:
        return f"seller_type must be one of {', '.join(SELLER_TYPES)}"
    return None


def store_offers(session: Session, source: Source, job: IngestionJob, offers: Iterable[tuple[str, RawOffer]],
                 region: str, retrieved: datetime, target: DeviceModel | None = None,
                 wanted_storage: int | None = None) -> list[MarketplaceOffer]:
    """Validate, match, de-duplicate and store. `offers` are (raw reference for rejects, offer)."""
    stored: list[MarketplaceOffer] = []
    seen: set[str] = set()
    for line, (ref, offer) in enumerate(offers, start=1):
        reason = validate(offer, region)
        match: Match | None = None
        if reason is None:
            match = match_listing(session, offer.title, offer.brand, offer.storage_gb, target, wanted_storage)
            if match.category == "similar" and target is not None:
                # Kept as a labelled alternative for the model that was searched for, never as a comparable.
                match.model_id = target.id
            if match.model_id is None:
                reason = "unrelated product: " + "; ".join(match.reasons)
        if reason is not None or match is None:
            job.rejected += 1
            session.add(RejectedRecord(job_id=job.id, line=line, reason=(reason or "")[:300],
                                       raw=json.dumps({"ref": ref, "title": offer.title, "price": str(offer.price)},
                                                      ensure_ascii=False)[:1000]))
            continue
        key = _dedup(source.id, offer, retrieved)
        if key in seen or session.scalar(select(MarketplaceOffer.id).where(MarketplaceOffer.dedup_key == key)):
            job.duplicates += 1
            continue
        seen.add(key)
        row = MarketplaceOffer(
            source_id=source.id, job_id=job.id, provider_product_id=offer.provider_product_id,
            title=offer.title[:300], brand=(offer.brand or None) and offer.brand[:80], model_id=match.model_id,
            storage_gb=match.storage_gb if match.category != "similar" else offer.storage_gb,
            ram_gb=offer.ram_gb if offer.ram_gb is not None else ram_from_title(offer.title),
            color=offer.color and offer.color[:60], condition=offer.condition, price_type=offer.price_type,
            price=offer.price, mrp=offer.mrp, currency=offer.currency, region=region,
            url=offer.url and offer.url[:600], seller=offer.seller and offer.seller[:120],
            seller_type=offer.seller_type, availability=offer.availability,
            delivery_note=offer.delivery_note and offer.delivery_note[:200], retrieved_at=retrieved,
            published_at=offer.published_at,
            raw_json=json.dumps(offer.raw, ensure_ascii=False, default=str)[:20000] if offer.raw else None,
            match_score=match.score, match_category=match.category, match_reasons=json.dumps(match.reasons),
            dedup_key=key, is_mock=source.is_mock,
        )
        session.add(row)
        stored.append(row)
        job.accepted += 1
    session.flush()
    return stored


def refresh(session: Session, providers: Sequence[Provider], model: DeviceModel, storage_gb: int | None,
            region: str, triggered_by: str, policy: OfferPolicy, now: datetime | None = None) -> list[ProviderRun]:
    """Ask every provider for this model; store what is valid. Never raises for a provider failure."""
    now = now or policy.now()
    query = f"{model.manufacturer} {model.name}" + (f" {storage_gb} GB" if storage_gb else "")
    runs = []
    for provider in providers:
        source = register_source(session, provider.spec)
        run = ProviderRun(source.id, source.name, "not_configured")
        if not provider.configured():
            run.message = provider.requirement()
            runs.append(run)
            continue
        recent = session.scalar(select(func.max(MarketplaceOffer.retrieved_at)).where(
            MarketplaceOffer.source_id == source.id, MarketplaceOffer.model_id == model.id,
            MarketplaceOffer.region == region))
        if recent and now - recent < timedelta(minutes=policy.min_refresh_minutes):
            run.status = "skipped_recent"
            run.message = f"Retrieved {int((now - recent).total_seconds() // 60)} min ago; minimum interval is " \
                          f"{policy.min_refresh_minutes} min."
            runs.append(run)
            continue
        job = IngestionJob(source_id=source.id, status="running", triggered_by=triggered_by[:80], accepted=0,
                           rejected=0, duplicates=0, started_at=now)
        session.add(job)
        session.flush()
        run.job_id = job.id
        try:
            result = provider.search(query, region)
        except ProviderError as exc:
            job.status, job.message = "failed", f"{exc.code}: {exc.message}"[:1000]
            run.status, run.error_code, run.message = "failed", exc.code, exc.message
        else:
            for ref, reason in result.rejected:
                job.rejected += 1
                session.add(RejectedRecord(job_id=job.id, line=0, reason=reason[:300], raw=ref[:1000]))
            stored = store_offers(session, source, job, ((o.provider_product_id or "", o) for o in result.offers),
                                  region, now, model, storage_gb)
            check_alerts(session, stored)
            job.status = "succeeded"
            run.status = "succeeded"
        job.finished_at = utcnow()
        run.accepted, run.rejected, run.duplicates = job.accepted, job.rejected, job.duplicates
        session.flush()
        runs.append(run)
    return runs


# --- curated (manual) offers -----------------------------------------------------------------------------------


OFFER_COLUMNS = ("title", "brand", "storage_gb", "condition", "price_type", "price", "mrp", "currency", "url",
                 "seller", "seller_type", "availability", "retrieved_at", "external_ref")


def import_offers_csv(session: Session, source: Source, text: str, region: str, triggered_by: str) -> IngestionJob:
    """Manually curated, source-attributed offers (e.g. buyback quotes recorded by hand). Same validation as API
    offers; `retrieved_at` is when the person recorded the price (ISO date or datetime)."""
    job = IngestionJob(source_id=source.id, status="running", triggered_by=triggered_by[:80], accepted=0,
                       rejected=0, duplicates=0)
    session.add(job)
    session.flush()
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if tuple(reader.fieldnames or ()) != OFFER_COLUMNS:
        job.status, job.message = "failed", f"CSV header must be {','.join(OFFER_COLUMNS)}"
        job.finished_at = utcnow()
        return job
    by_time: dict[datetime, list[tuple[str, RawOffer]]] = defaultdict(list)
    for line, raw in enumerate(reader, start=2):
        row = {k: (v or "").strip() for k, v in raw.items() if k is not None}
        try:
            offer, retrieved = _offer_from_row(row)
        except ValueError as exc:
            job.rejected += 1
            session.add(RejectedRecord(job_id=job.id, line=line, reason=str(exc)[:300],
                                       raw=json.dumps(row, ensure_ascii=False)[:1000]))
            continue
        if retrieved > utcnow() or utcnow() - retrieved > timedelta(days=5 * 365):
            job.rejected += 1
            session.add(RejectedRecord(job_id=job.id, line=line, reason="retrieved_at is in the future or too old",
                                       raw=json.dumps(row, ensure_ascii=False)[:1000]))
            continue
        by_time[retrieved].append((row.get("external_ref") or f"line {line}", offer))
    for retrieved, offers in by_time.items():
        check_alerts(session, store_offers(session, source, job, offers, region, retrieved))
    job.status, job.finished_at = "succeeded", utcnow()
    session.flush()
    return job


def _offer_from_row(row: dict[str, str]) -> tuple[RawOffer, datetime]:
    price = money(row["price"])
    if price is None:
        raise ValueError("price must be a positive number")
    condition = row["condition"]
    if condition not in CONDITIONS:
        raise ValueError(f"condition must be one of {', '.join(CONDITIONS)}")
    price_type = row["price_type"] or PRICE_TYPE[condition]
    try:
        retrieved = datetime.fromisoformat(row["retrieved_at"])
    except ValueError as exc:
        raise ValueError("retrieved_at must be an ISO date or datetime") from exc
    storage = row["storage_gb"]
    if storage and not storage.isdigit():
        raise ValueError("storage_gb must be a whole number")
    return RawOffer(
        title=row["title"], brand=row["brand"] or None, storage_gb=int(storage) if storage else None,
        condition=condition, price_type=price_type, price=price, mrp=money(row["mrp"]) if row["mrp"] else None,
        currency=row["currency"], url=row["url"] or None, seller=row["seller"] or None,
        seller_type=row["seller_type"] or None,
        availability=row["availability"] if row["availability"] in ("in_stock", "out_of_stock") else None,
        provider_product_id=row["external_ref"] or None, raw={"manual_row": row},
    ), retrieved.replace(tzinfo=None)


FIXTURE_COLUMNS = ("search_model_id", "days_ago", "title", "brand", "storage_gb", "condition", "price_type", "price",
                   "mrp", "seller", "seller_type", "availability")


def seed_fixture_offers(session: Session, source: Source, text: str, now: datetime) -> IngestionJob:
    """Development fixtures (MOCK): stored exactly as a provider search for `search_model_id` would store them,
    so matching, comparison and history run on them. No URLs: there are no real listings."""
    if not source.is_mock:
        raise ValueError("fixture offers belong only to a mock source")
    job = IngestionJob(source_id=source.id, status="running", triggered_by="cli:seed-mock", accepted=0,
                       rejected=0, duplicates=0)
    session.add(job)
    session.flush()
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if tuple(reader.fieldnames or ()) != FIXTURE_COLUMNS:
        raise ValueError(f"fixture header must be {','.join(FIXTURE_COLUMNS)}")
    groups: dict[tuple[str, int], list[tuple[str, RawOffer]]] = defaultdict(list)
    for line, row in enumerate(reader, start=2):
        price = money(row["price"])
        assert price is not None, f"fixture line {line}: price"
        groups[(row["search_model_id"], int(row["days_ago"]))].append((f"fixture line {line}", RawOffer(
            title=row["title"], brand=row["brand"] or None,
            storage_gb=int(row["storage_gb"]) if row["storage_gb"] else None, condition=row["condition"],
            price_type=row["price_type"], price=price, mrp=money(row["mrp"]), currency="INR",
            seller=row["seller"] or None, seller_type=row["seller_type"] or None,
            availability=row["availability"] or None, provider_product_id=f"fixture-{row['title']}"[:100])))
    for (model_id, days_ago), offers in groups.items():
        store_offers(session, source, job, offers, "IN", now - timedelta(days=days_ago),
                     session.get(DeviceModel, model_id))
    job.status, job.finished_at = "succeeded", utcnow()
    session.flush()
    return job


def data_quality(session: Session, providers: Sequence[Provider], policy: OfferPolicy, now: datetime | None = None,
                 days: int = 30) -> dict:
    """Retrievals, failures, staleness, rejects, duplicates, matching uncertainty and missing metadata."""
    now = now or policy.now()
    since = now - timedelta(days=days)
    jobs = session.execute(select(IngestionJob.source_id, IngestionJob.status, func.count(),
                                  func.sum(IngestionJob.accepted), func.sum(IngestionJob.rejected),
                                  func.sum(IngestionJob.duplicates))
                           .where(IngestionJob.started_at >= since)
                           .group_by(IngestionJob.source_id, IngestionJob.status)).all()
    retrievals: dict[str, dict] = {}
    for source_id, status, count, accepted, rejected, duplicates in jobs:
        r = retrievals.setdefault(source_id, {"succeeded": 0, "failed": 0, "running": 0, "accepted": 0,
                                              "rejected": 0, "duplicates": 0})
        r[status] = r.get(status, 0) + count
        r["accepted"] += accepted or 0
        r["rejected"] += rejected or 0
        r["duplicates"] += duplicates or 0
    failures = [{"source_id": j.source_id, "at": j.started_at.isoformat() + "Z", "message": j.message}
                for j in session.scalars(select(IngestionJob).where(IngestionJob.status == "failed",
                                                                    IngestionJob.started_at >= since)
                                         .order_by(IngestionJob.id.desc()).limit(20))]
    latest = current_offers_all(session, policy, now)
    fresh = {"fresh": 0, "stale": 0}
    for offer in latest:
        label = freshness(offer.retrieved_at, now, policy)
        fresh[label] = fresh.get(label, 0) + 1
    expired = session.scalar(select(func.count(MarketplaceOffer.id)).where(
        MarketplaceOffer.retrieved_at < now - timedelta(days=policy.max_age_days))) or 0
    matches = dict(session.execute(select(MarketplaceOffer.match_category, func.count())
                                   .group_by(MarketplaceOffer.match_category)).all())
    reasons = session.execute(select(RejectedRecord.reason).join(IngestionJob, IngestionJob.id == RejectedRecord.job_id)
                              .where(IngestionJob.started_at >= since)).scalars().all()
    reject_kinds: dict[str, int] = defaultdict(int)
    for reason in reasons:
        reject_kinds[reason.split(":")[0][:60]] += 1
    total = session.scalar(select(func.count(MarketplaceOffer.id))) or 0
    missing = {column: session.scalar(select(func.count(MarketplaceOffer.id)).where(attr.is_(None))) or 0
               for column, attr in (("url", MarketplaceOffer.url), ("seller", MarketplaceOffer.seller),
                                    ("availability", MarketplaceOffer.availability),
                                    ("mrp", MarketplaceOffer.mrp), ("storage_gb", MarketplaceOffer.storage_gb))}
    sources = session.scalars(select(Source).order_by(Source.id)).all()
    return {
        "generated_at": now.isoformat() + "Z", "window_days": days,
        "providers": provider_status(session, providers, policy, now),
        "retrievals_by_source": retrievals, "recent_failures": failures,
        "offers": {"total_rows": total, "current_listings": fresh, "older_than_max_age": expired},
        "match_categories": matches, "rejected_by_reason": dict(reject_kinds),
        "duplicates_skipped": sum(r["duplicates"] for r in retrievals.values()),
        "offers_missing_field": missing,
        "sources_missing_metadata": [{"id": s.id, "missing": [n for n, v in (("url", s.url),) if not v]
                                      + ([] if s.verified else ["not verified"])}
                                     for s in sources if not s.url or not s.verified],
    }


def current_offers_all(session: Session, policy: OfferPolicy, now: datetime) -> list[MarketplaceOffer]:
    query = select(MarketplaceOffer).where(MarketplaceOffer.retrieved_at >= now - timedelta(days=policy.max_age_days))
    latest: dict[tuple, MarketplaceOffer] = {}
    for offer in session.scalars(query.order_by(MarketplaceOffer.retrieved_at.desc())):
        latest.setdefault((offer.source_id, offer.provider_product_id or offer.url or offer.title, offer.condition,
                           offer.seller or ""), offer)
    return list(latest.values())


# --- alerts --------------------------------------------------------------------------------------------------


def check_alerts(session: Session, offers: Iterable[MarketplaceOffer]) -> int:
    """Create an alert for each watch whose target price an actually stored, primary-match offer meets."""
    created = 0
    for offer in offers:
        if offer.match_category not in PRIMARY or offer.model_id is None or offer.availability == "out_of_stock":
            continue
        watches = session.scalars(select(WatchlistItem).where(
            WatchlistItem.model_id == offer.model_id, WatchlistItem.storage_gb == offer.storage_gb,
            WatchlistItem.region == offer.region, WatchlistItem.condition == offer.condition,
            WatchlistItem.target_price.is_not(None), WatchlistItem.target_price >= offer.price))
        for watch in watches:
            duplicate = session.scalar(select(PriceAlert.id).where(PriceAlert.watch_id == watch.id,
                                                                   PriceAlert.price <= offer.price))
            if duplicate:
                continue  # already alerted at this price or lower
            session.add(PriceAlert(watch_id=watch.id, offer_id=offer.id, price=offer.price,
                                   reason=f"{offer.price} {offer.currency} is at or below your target "
                                          f"{watch.target_price}"))
            created += 1
    session.flush()
    return created


# --- reading -------------------------------------------------------------------------------------------------


def freshness(retrieved: datetime, now: datetime, policy: OfferPolicy) -> str:
    age = now - retrieved
    if age <= timedelta(hours=policy.fresh_hours):
        return "fresh"
    return "stale" if age <= timedelta(days=policy.max_age_days) else "expired"


def offer_dict(o: MarketplaceOffer, source: Source, now: datetime, policy: OfferPolicy) -> dict:
    discount = None
    if o.mrp and o.mrp > o.price:
        discount = float(((o.mrp - o.price) / o.mrp * 100).quantize(Decimal("0.1")))
    return {
        "id": o.id, "source": {"id": source.id, "name": source.name, "verified": source.verified,
                               "is_mock": source.is_mock, "automated": source.id in AUTOMATED_SOURCES,
                               "estimated": source.source_type == "estimate"},
        "title": o.title, "brand": o.brand, "model_id": o.model_id, "storage_gb": o.storage_gb, "ram_gb": o.ram_gb,
        "color": o.color, "condition": o.condition, "price_type": o.price_type, "price": float(o.price),
        "mrp": float(o.mrp) if o.mrp else None, "discount_pct": discount, "currency": o.currency, "url": o.url,
        "seller": o.seller, "seller_type": o.seller_type, "availability": o.availability,
        "delivery_note": o.delivery_note, "retrieved_at": o.retrieved_at.isoformat() + "Z",
        "published_at": o.published_at.isoformat() + "Z" if o.published_at else None,
        "freshness": "estimate" if source.source_type == "estimate" else freshness(o.retrieved_at, now, policy),
        "is_mock": o.is_mock,
        "match": {"category": o.match_category, "score": o.match_score, "reasons": json.loads(o.match_reasons)},
    }


def current_offers(session: Session, model_id: str, region: str, policy: OfferPolicy,
                   now: datetime) -> list[tuple[MarketplaceOffer, Source]]:
    """The latest retrieval of each listing for this model within max_age_days. Modelled store estimates do not
    age out: `load-estimates` replaces them as a whole."""
    query = (select(MarketplaceOffer, Source).join(Source, Source.id == MarketplaceOffer.source_id)
             .where(MarketplaceOffer.model_id == model_id, MarketplaceOffer.region == region,
                    or_(MarketplaceOffer.retrieved_at >= now - timedelta(days=policy.max_age_days),
                        Source.source_type == "estimate"))
             .order_by(MarketplaceOffer.retrieved_at.desc(), MarketplaceOffer.id.desc()))
    if not policy.include_mock:
        query = query.where(MarketplaceOffer.is_mock.is_(False))
    latest: dict[tuple, tuple[MarketplaceOffer, Source]] = {}
    for offer, source in session.execute(query):
        key = (offer.source_id, offer.provider_product_id or offer.url or offer.title, offer.condition,
               offer.seller or "")
        latest.setdefault(key, (offer, source))
    return list(latest.values())


def compare(session: Session, model: DeviceModel, storage_gb: int, region: str, policy: OfferPolicy,
            now: datetime | None = None) -> dict:
    """Comparable offers for exactly this model and storage, grouped by condition, plus labelled alternatives."""
    now = now or policy.now()
    groups: dict[str, list[dict]] = {"new": [], "refurbished": [], "used": [], "buyback": []}
    alternatives: list[dict] = []
    for offer, source in current_offers(session, model.id, region, policy, now):
        item = offer_dict(offer, source, now, policy)
        if offer.match_category in PRIMARY and offer.storage_gb == storage_gb:
            groups["buyback" if offer.price_type == "buyback_quote" else offer.condition].append(item)
            continue
        if offer.match_category in PRIMARY:
            # The right model in another storage variant: relative to this request it is a variant mismatch.
            item["match"] = {"category": "variant_mismatch", "score": 45,
                             "reasons": [*item["match"]["reasons"], f"listing is {offer.storage_gb} GB, not "
                                                                    f"{storage_gb} GB"]}
        alternatives.append(item)
    summaries = {}
    for name, items in groups.items():
        items.sort(key=lambda i: (i["availability"] == "out_of_stock", i["price"]))
        prices = [i["price"] for i in items if i["availability"] != "out_of_stock"]
        summaries[name] = {
            "count": len(items), "lowest": min(prices) if prices else None,
            "highest": max(prices) if prices else None,
            "spread": round(max(prices) - min(prices), 2) if len(prices) >= 2 else None,
            "sources": sorted({i["source"]["name"] for i in items}),
        }
    alternatives.sort(key=lambda i: (-i["match"]["score"], i["price"]))
    mrps = [i["mrp"] for i in groups["new"] if i["mrp"]]
    return {
        "model_id": model.id, "storage_gb": storage_gb, "region": region, "currency": REGION_CURRENCY[region],
        "groups": groups, "summary": summaries, "alternatives": alternatives[:30],
        "mrp": {"value": statistics.median(mrps), "count": len(mrps)} if mrps else None,
        "mock_data_included": any(i["is_mock"] for items in groups.values() for i in items),
        "estimates_included": any(i["source"]["estimated"] for items in groups.values() for i in items),
        "generated_at": now.isoformat() + "Z", "fresh_hours": policy.fresh_hours,
        "max_age_days": policy.max_age_days,
    }


def history(session: Session, model: DeviceModel, storage_gb: int, region: str, condition: str, days: int,
            policy: OfferPolicy, now: datetime | None = None) -> dict:
    """Daily lowest observed price per source for primary matches. Only actual retrievals (never modelled
    estimates); gaps are reported."""
    now = now or policy.now()
    since = now - timedelta(days=days)
    query = (select(MarketplaceOffer, Source.name).join(Source, Source.id == MarketplaceOffer.source_id)
             .where(Source.source_type != "estimate",
                    MarketplaceOffer.model_id == model.id, MarketplaceOffer.storage_gb == storage_gb,
                    MarketplaceOffer.region == region, MarketplaceOffer.condition == condition,
                    MarketplaceOffer.match_category.in_(PRIMARY), MarketplaceOffer.price_type != "buyback_quote",
                    MarketplaceOffer.retrieved_at >= since))
    if not policy.include_mock:
        query = query.where(MarketplaceOffer.is_mock.is_(False))
    per_day: dict[str, dict[date, Decimal]] = defaultdict(dict)
    count = 0
    last: datetime | None = None
    mock = False
    for offer, source_name in session.execute(query):
        count += 1
        mock = mock or offer.is_mock
        last = max(last, offer.retrieved_at) if last else offer.retrieved_at
        day = offer.retrieved_at.date()
        current = per_day[source_name].get(day)
        per_day[source_name][day] = min(current, offer.price) if current is not None else offer.price
    overall: dict[date, Decimal] = {}
    for series in per_day.values():
        for day, price in series.items():
            overall[day] = min(overall.get(day, price), price)
    observed_days = sorted(overall)
    available = len(observed_days) >= 2
    result: dict = {
        "model_id": model.id, "storage_gb": storage_gb, "region": region, "condition": condition,
        "currency": REGION_CURRENCY[region], "days": days, "observation_count": count,
        "observed_days": len(observed_days), "available": available, "mock_data_included": mock,
        "last_observation": last.isoformat() + "Z" if last else None,
        "series": {name: [{"date": d.isoformat(), "lowest": float(p)} for d, p in sorted(s.items())]
                   for name, s in per_day.items()},
        "lowest": None, "highest": None, "change": None, "gaps": [],
        "reason": None if available else (
            "No price has been retrieved for this product yet." if not observed_days else
            "Tracking has only just started: history needs prices retrieved on at least two different days."),
    }
    if observed_days:
        low_day = min(observed_days, key=lambda d: overall[d])
        high_day = max(observed_days, key=lambda d: overall[d])
        result["lowest"] = {"price": float(overall[low_day]), "date": low_day.isoformat()}
        result["highest"] = {"price": float(overall[high_day]), "date": high_day.isoformat()}
        result["gaps"] = [{"from": a.isoformat(), "to": b.isoformat(), "days": (b - a).days - 1}
                          for a, b in zip(observed_days, observed_days[1:], strict=False) if (b - a).days > 1]
    if available:
        latest, previous = overall[observed_days[-1]], overall[observed_days[-2]]
        result["change"] = {"from_date": observed_days[-2].isoformat(), "to_date": observed_days[-1].isoformat(),
                            "amount": float(latest - previous),
                            "pct": float(((latest - previous) / previous * 100).quantize(Decimal("0.1")))}
    return result


def provider_status(session: Session, providers: Sequence[Provider], policy: OfferPolicy,
                    now: datetime | None = None) -> list[dict]:
    """Per provider: configured, last job outcome, last successful retrieval. No credentials are exposed."""
    now = now or policy.now()
    out = []
    for p in providers:
        job = session.scalars(select(IngestionJob).where(IngestionJob.source_id == p.spec.id)
                              .order_by(IngestionJob.id.desc()).limit(1)).first()
        last_ok = session.scalar(select(func.max(MarketplaceOffer.retrieved_at))
                                 .where(MarketplaceOffer.source_id == p.spec.id))
        if not p.configured():
            state = "manual_only" if not p.automated else "not_configured"
        elif job is not None and job.status == "failed":
            state = "failing"
        elif last_ok and freshness(last_ok, now, policy) == "fresh":
            state = "operational"
        else:
            state = "configured"
        out.append({"id": p.spec.id, "name": p.spec.name, "state": state, "automated": p.automated,
                    "markets": p.spec.markets, "configured": p.configured(),
                    "requirement": None if p.configured() else p.requirement(),
                    "last_job_status": job.status if job else None,
                    "last_job_message": job.message if job and job.status == "failed" else None,
                    "last_retrieved_at": last_ok.isoformat() + "Z" if last_ok else None,
                    "terms_note": p.spec.terms_note, "docs_url": p.spec.url})
    return out
