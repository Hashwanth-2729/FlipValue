"""Operator API under /admin/api. Requires an admin-role key (middleware); partner keys are refused.

Every change is written to the audit log.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query, Request, Security
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from flipvalue import catalogue
from flipvalue.context import DbSession, get_ctx
from flipvalue.db.models import (
    ApiClient,
    AuditLog,
    DeviceModel,
    IngestionJob,
    ModelAlias,
    Observation,
    RejectedRecord,
    RequestLog,
    Source,
    utcnow,
)
from flipvalue.errors import ApiError
from flipvalue.ingestion.adapters import CsvImportAdapter
from flipvalue.ingestion.runner import run_ingestion
from flipvalue.ingestion.sources import SourceError, SourceSpec, register_source
from flipvalue.marketplace import service as market
from flipvalue.routes.partner import api_key_header

router = APIRouter(prefix="/admin/api", tags=["admin"], dependencies=[Security(api_key_header)])


def audit(session: Session, request: Request, action: str, detail: dict) -> None:
    session.add(AuditLog(actor=request.state.client, action=action, detail=json.dumps(detail, default=str)))


class SourceStatus(BaseModel):
    id: str
    name: str
    source_type: str
    collection_method: str
    url: str | None
    markets: str
    terms_note: str
    verified: bool
    is_mock: bool
    observation_count: int
    newest_observation: date | None
    freshness_days: int | None
    last_job_status: str | None
    last_job_at: datetime | None


@router.get("/sources", response_model=list[SourceStatus])
def sources(request: Request, session: DbSession) -> list[SourceStatus]:
    today = get_ctx(request).engine.clock()
    out = []
    for source in session.scalars(select(Source).order_by(Source.id)):
        count, newest = session.execute(select(func.count(Observation.id), func.max(Observation.observed_at))
                                        .where(Observation.source_id == source.id)).one()
        job = session.scalars(select(IngestionJob).where(IngestionJob.source_id == source.id)
                              .order_by(IngestionJob.id.desc()).limit(1)).first()
        out.append(SourceStatus(
            id=source.id, name=source.name, source_type=source.source_type,
            collection_method=source.collection_method, url=source.url, markets=source.markets,
            terms_note=source.terms_note, verified=source.verified, is_mock=source.is_mock,
            observation_count=count, newest_observation=newest,
            freshness_days=(today - newest).days if newest else None,
            last_job_status=job.status if job else None, last_job_at=job.started_at if job else None,
        ))
    return out


class SourceIn(BaseModel):
    id: str = Field(max_length=60)
    name: str = Field(min_length=1, max_length=120)
    source_type: str
    collection_method: str = Field(min_length=1, max_length=200)
    markets: str = Field(max_length=40)
    terms_note: str = Field(min_length=1, max_length=2000)
    verified: bool
    url: str | None = Field(default=None, max_length=300)


@router.post("/sources", response_model=SourceStatus, status_code=201)
def add_source(body: SourceIn, request: Request, session: DbSession) -> SourceStatus:
    if body.source_type == "synthetic":
        raise ApiError(422, "validation_error", "Synthetic sources are created only by the seed-mock command.")
    try:
        register_source(session, SourceSpec(**body.model_dump()))
    except SourceError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    audit(session, request, "source.register", body.model_dump())
    return next(s for s in sources(request, session) if s.id == body.id)


class JobOut(BaseModel):
    id: int
    source_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    accepted: int
    rejected: int
    duplicates: int
    triggered_by: str
    message: str | None


def _job(j: IngestionJob) -> JobOut:
    return JobOut(id=j.id, source_id=j.source_id, status=j.status, started_at=j.started_at,
                  finished_at=j.finished_at, accepted=j.accepted, rejected=j.rejected, duplicates=j.duplicates,
                  triggered_by=j.triggered_by, message=j.message)


@router.get("/jobs", response_model=list[JobOut])
def jobs(session: DbSession, limit: int = Query(50, ge=1, le=500)) -> list[JobOut]:
    return [_job(j) for j in session.scalars(select(IngestionJob).order_by(IngestionJob.id.desc()).limit(limit))]


class RejectedOut(BaseModel):
    line: int
    reason: str
    raw: str


@router.get("/jobs/{job_id}/rejected", response_model=list[RejectedOut])
def rejected(job_id: int, session: DbSession) -> list[RejectedOut]:
    rows = session.scalars(select(RejectedRecord).where(RejectedRecord.job_id == job_id)
                           .order_by(RejectedRecord.line).limit(1000))
    return [RejectedOut(line=r.line, reason=r.reason, raw=r.raw) for r in rows]


class ImportIn(BaseModel):
    source_id: str = Field(max_length=60)
    csv_text: str = Field(min_length=1, max_length=2_000_000)


@router.post("/imports", response_model=JobOut, status_code=201)
def import_csv(body: ImportIn, request: Request, session: DbSession) -> JobOut:
    """Manual import of legitimately obtained observations (CSV columns: see docs/DATA_QUALITY.md)."""
    ctx = get_ctx(request)
    source = session.get(Source, body.source_id)
    if source is None:
        raise ApiError(404, "not_found", f"Unknown source {body.source_id!r}; register it first.")
    if source.is_mock:
        raise ApiError(422, "validation_error", "Synthetic sources cannot receive imports.")
    try:
        job = run_ingestion(session, source.id, CsvImportAdapter(body.csv_text), request.state.client,
                            production=ctx.settings.is_production, today=ctx.engine.clock())
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    audit(session, request, "ingestion.import", {"source": source.id, "job": job.id, "accepted": job.accepted,
                                                 "rejected": job.rejected, "duplicates": job.duplicates})
    return _job(job)


class AliasIn(BaseModel):
    alias: str = Field(min_length=1, max_length=80)
    kind: str = Field(pattern="^(name|oem_code)$")


@router.post("/models/{model_id}/aliases", status_code=201)
def add_alias(model_id: str, body: AliasIn, request: Request,
              session: DbSession) -> dict[str, str]:
    model = session.get(DeviceModel, model_id)
    if model is None:
        raise ApiError(404, "unsupported_model", "Unknown model.")
    maker, alias = catalogue.normalise(model.manufacturer), catalogue.normalise(body.alias)
    existing = session.scalar(select(ModelAlias).where(ModelAlias.manufacturer_norm == maker,
                                                       ModelAlias.alias_norm == alias))
    if existing is not None:
        raise ApiError(409, "conflict", f"Alias already maps to {existing.model_id}.")
    session.add(ModelAlias(model_id=model.id, manufacturer_norm=maker, alias=body.alias.strip(), alias_norm=alias,
                           kind=body.kind))
    audit(session, request, "catalogue.alias_add", {"model": model.id, "alias": body.alias, "kind": body.kind})
    return {"model_id": model.id, "alias": body.alias.strip()}


class MetricsOut(BaseModel):
    since: datetime
    requests_by_channel: dict[str, int]
    status_counts: dict[str, int]
    error_codes: dict[str, int]
    method_versions: dict[str, int]
    latency_ms_p50: int | None
    latency_ms_p95: int | None
    api_clients_active: int


@router.get("/metrics", response_model=MetricsOut)
def metrics(session: DbSession, hours: int = Query(24, ge=1, le=24 * 90)) -> MetricsOut:
    since = utcnow() - timedelta(hours=hours)
    window = RequestLog.at >= since

    def counts(column) -> dict[str, int]:
        rows = session.execute(select(column, func.count()).where(window, column.is_not(None)).group_by(column))
        return {str(k): v for k, v in rows}

    latencies = sorted(session.scalars(select(RequestLog.latency_ms).where(window)))

    def pct(p: float) -> int | None:
        return latencies[min(len(latencies) - 1, int(p * len(latencies)))] if latencies else None

    active = session.scalar(select(func.count(ApiClient.id)).where(ApiClient.revoked_at.is_(None))) or 0
    return MetricsOut(since=since, requests_by_channel=counts(RequestLog.channel),
                      status_counts=counts(RequestLog.status), error_codes=counts(RequestLog.error_code),
                      method_versions=counts(RequestLog.method_version), latency_ms_p50=pct(0.5),
                      latency_ms_p95=pct(0.95), api_clients_active=active)


class ForwardingOut(BaseModel):
    x_forwarded_for: list[str]
    peer: str | None
    trust_proxy: bool
    proxy_hops: int
    client_ip_used_for_rate_limits: str
    hint: str


@router.get("/diagnostics/forwarding", response_model=ForwardingOut)
def forwarding(request: Request) -> ForwardingOut:
    """Shows the caller (an admin) how proxies forwarded *their own* request, to set FLIPVALUE_PROXY_HOPS correctly.

    Nothing is stored or logged. Call it once through each entry point (Cloud Run URL, Firebase Hosting) and check
    that `client_ip_used_for_rate_limits` is your own public IP.
    """
    settings = get_ctx(request).settings
    raw = request.headers.get("x-forwarded-for", "")
    return ForwardingOut(
        x_forwarded_for=[e.strip() for e in raw.split(",") if e.strip()],
        peer=request.client.host if request.client else None,
        trust_proxy=settings.trust_proxy, proxy_hops=settings.proxy_hops,
        client_ip_used_for_rate_limits=request.app.state.client_ip(request),
        hint="Set FLIPVALUE_PROXY_HOPS so the chosen entry is your real public IP for the entry point users use.",
    )


@router.get("/providers")
def providers(request: Request, session: DbSession) -> list[dict]:
    ctx = get_ctx(request)
    return market.provider_status(session, ctx.providers, ctx.offer_policy)


class RefreshIn(BaseModel):
    model_id: str = Field(max_length=80)
    storage_gb: int | None = Field(default=None, ge=1, le=4096)
    region: str = Field("IN", pattern="^[A-Z]{2}$")


@router.post("/offers/refresh")
def refresh_offers(body: RefreshIn, request: Request, session: DbSession) -> list[dict]:
    """Ask every configured provider for this model now (subject to the per-provider minimum interval)."""
    ctx = get_ctx(request)
    model = session.get(DeviceModel, body.model_id)
    if model is None:
        raise ApiError(404, "unsupported_model", "Unknown model.")
    runs = market.refresh(session, ctx.providers, model, body.storage_gb, body.region, request.state.client,
                          ctx.offer_policy)
    audit(session, request, "offers.refresh", {"model": model.id, "runs": [r.__dict__ for r in runs]})
    return [r.__dict__ for r in runs]


class OfferImportIn(BaseModel):
    source_id: str = Field(max_length=60)
    region: str = Field("IN", pattern="^[A-Z]{2}$")
    csv_text: str = Field(min_length=1, max_length=2_000_000)


@router.post("/offer-imports", response_model=JobOut, status_code=201)
def import_offers(body: OfferImportIn, request: Request, session: DbSession) -> JobOut:
    """Curated offers or buyback quotes recorded by hand, with their source (columns: docs/DATA_QUALITY.md)."""
    source = session.get(Source, body.source_id)
    if source is None:
        raise ApiError(404, "not_found", f"Unknown source {body.source_id!r}; register it first.")
    if source.is_mock:
        raise ApiError(422, "validation_error", "Mock sources cannot receive imports.")
    if body.region not in source.markets.split(","):
        raise ApiError(422, "validation_error", f"Source {source.id} is not registered for {body.region}.")
    job = market.import_offers_csv(session, source, body.csv_text, body.region, request.state.client)
    audit(session, request, "offers.import", {"source": source.id, "job": job.id, "accepted": job.accepted,
                                              "rejected": job.rejected, "duplicates": job.duplicates})
    return _job(job)


@router.get("/data-quality")
def data_quality(request: Request, session: DbSession, days: int = Query(30, ge=1, le=365)) -> dict:
    ctx = get_ctx(request)
    return market.data_quality(session, ctx.providers, ctx.offer_policy, days=days)


class AuditOut(BaseModel):
    at: datetime
    actor: str
    action: str
    detail: str


@router.get("/audit", response_model=list[AuditOut])
def audit_log(session: DbSession, limit: int = Query(100, ge=1, le=1000)) -> list[AuditOut]:
    rows = session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
    return [AuditOut(at=r.at, actor=r.actor, action=r.action, detail=r.detail) for r in rows]
