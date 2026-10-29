"""Normalise, validate, de-duplicate and store rows from one adapter run as an ingestion job."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from flipvalue import catalogue
from flipvalue.config import REGION_CURRENCY
from flipvalue.db.models import IngestionJob, Observation, RejectedRecord, Source, utcnow
from flipvalue.ingestion.adapters import AdapterError, SourceAdapter
from flipvalue.schemas import GRADES

MAX_PRICE = Decimal("10000000")      # catches unit/format mistakes (e.g. paise entered as rupees)
MAX_AGE = timedelta(days=5 * 365)


class RowRejected(ValueError):
    pass


@dataclass(frozen=True)
class NormalisedRow:
    model_id: str
    storage_gb: int
    region: str
    currency: str
    grade: str
    price: Decimal
    observed_at: date
    external_ref: str | None


def normalise_row(session: Session, raw: dict[str, str], source: Source, today: date) -> NormalisedRow:
    model = catalogue.find_model(session, raw.get("manufacturer", ""), raw.get("model", ""))
    if model is None:
        raise RowRejected(f"model not in catalogue: {raw.get('manufacturer')} {raw.get('model')}")
    region, currency = raw.get("region", ""), raw.get("currency", "")
    if REGION_CURRENCY.get(region) != currency:
        raise RowRejected(f"region/currency {region}/{currency} is not a supported pair")
    if region not in source.markets.split(","):
        raise RowRejected(f"source {source.id} is not registered for market {region}")
    grade = raw.get("grade", "")
    if grade not in GRADES:
        raise RowRejected(f"grade must be one of {', '.join(GRADES)}")

    known = catalogue.variants(session, model.id)
    if raw.get("storage_gb"):
        if not raw["storage_gb"].isdigit() or int(raw["storage_gb"]) not in known:
            raise RowRejected(f"storage_gb must be one of {known} for {model.name}")
        storage = int(raw["storage_gb"])
    elif len(known) == 1:
        storage = known[0]
    else:
        raise RowRejected(f"storage_gb is required for {model.name} (variants {known})")

    try:
        price = Decimal(raw.get("price", ""))
    except InvalidOperation as exc:
        raise RowRejected("price is not a number") from exc
    if not price.is_finite() or price <= 0 or price > MAX_PRICE:
        raise RowRejected("price must be > 0 and plausible")
    if price != price.quantize(Decimal("0.01")):
        raise RowRejected("price has more than 2 decimal places")

    try:
        observed = date.fromisoformat(raw.get("observed_at", ""))
    except ValueError as exc:
        raise RowRejected("observed_at must be YYYY-MM-DD") from exc
    if observed > today:
        raise RowRejected("observed_at is in the future")
    if today - observed > MAX_AGE:
        raise RowRejected("observed_at is more than 5 years old")

    ref = raw.get("external_ref") or None
    if ref and len(ref) > 200:
        raise RowRejected("external_ref longer than 200 characters")
    return NormalisedRow(model.id, storage, region, currency, grade, price, observed, ref)


def dedup_key(source_id: str, row: NormalisedRow) -> str:
    if row.external_ref:
        basis = f"{source_id}|ref|{row.external_ref}"
    else:
        basis = "|".join(map(str, (source_id, row.model_id, row.storage_gb, row.region, row.grade,
                                   row.price, row.observed_at)))
    return hashlib.sha256(basis.encode()).hexdigest()


def run_ingestion(session: Session, source_id: str, adapter: SourceAdapter, triggered_by: str,
                  *, production: bool, today: date | None = None) -> IngestionJob:
    """Store every valid row; record every invalid one. The job row always records the outcome."""
    source = session.get(Source, source_id)
    if source is None:
        raise ValueError(f"unknown source {source_id!r}; register it first")
    if source.is_mock and production:
        raise ValueError("synthetic (mock) sources cannot be ingested in production")
    today = today or date.today()
    job = IngestionJob(source_id=source.id, status="running", triggered_by=triggered_by,
                       accepted=0, rejected=0, duplicates=0)
    session.add(job)
    session.flush()

    seen: set[str] = set()
    try:
        for line, raw in adapter.rows():
            try:
                row = normalise_row(session, raw, source, today)
            except RowRejected as exc:
                job.rejected += 1
                session.add(RejectedRecord(job_id=job.id, line=line, reason=str(exc)[:300],
                                           raw=json.dumps(raw, ensure_ascii=False)[:1000]))
                continue
            key = dedup_key(source.id, row)
            exists = key in seen or session.scalar(select(Observation.id).where(Observation.dedup_key == key))
            if exists:
                job.duplicates += 1
                continue
            seen.add(key)
            session.add(Observation(
                source_id=source.id, job_id=job.id, model_id=row.model_id, storage_gb=row.storage_gb,
                region=row.region, currency=row.currency, grade=row.grade, price=row.price,
                observed_at=row.observed_at, collected_at=utcnow(), external_ref=row.external_ref,
                dedup_key=key, is_mock=source.is_mock,
            ))
            job.accepted += 1
        job.status = "succeeded"
    except AdapterError as exc:
        job.status, job.message = "failed", str(exc)[:1000]
    job.finished_at = utcnow()
    session.flush()
    return job


def latest_jobs(session: Session, limit: int = 50) -> list[IngestionJob]:
    return list(session.scalars(select(IngestionJob).order_by(IngestionJob.id.desc()).limit(limit)))
