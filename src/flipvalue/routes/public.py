"""Public website API. Anonymous; protected by per-IP rate limits, size limits and timeouts (middleware).

No partner key is involved: the browser never sees one.
"""

from __future__ import annotations

import hmac
import json
import secrets
from datetime import date

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from flipvalue import catalogue
from flipvalue.config import REGION_CURRENCY
from flipvalue.context import DbSession, get_ctx
from flipvalue.db.models import DeviceModel, Observation, SavedValuation, Source
from flipvalue.decision import DecisionInput, DecisionResult, decide
from flipvalue.engine import ESTIMATE_BASES, METHOD_VERSION, MIN_OBSERVATIONS, EngineError
from flipvalue.errors import ApiError
from flipvalue.schemas import (
    CatalogueModelOut,
    Grade,
    PublicValuation,
    PublicValuationRequest,
    SavedValuationOut,
    SaveResponse,
    TrendOut,
    TrendPoint,
)
from flipvalue.security import hash_key
from flipvalue.services import public_valuation

router = APIRouter(prefix="/api", tags=["public"])


class SourceOut(BaseModel):
    id: str
    name: str
    source_type: str
    collection_method: str
    markets: str
    verified: bool
    is_mock: bool
    observation_count: int
    newest_observation: date | None


class MetaOut(BaseModel):
    environment: str
    method_version: str
    regions: dict[str, str]
    data_status: str  # real | estimated | mock_only | none
    real_observations: int
    estimated_observations: int
    mock_observations: int
    mock_data_in_use: bool
    newest_real_observation: date | None
    freshness_days: int
    sources: list[SourceOut]


@router.get("/meta", response_model=MetaOut)
def meta(request: Request, session: DbSession) -> MetaOut:
    ctx = get_ctx(request)
    rows = session.execute(
        select(Source, func.count(Observation.id), func.max(Observation.observed_at))
        .outerjoin(Observation, Observation.source_id == Source.id)
        .group_by(Source.id).order_by(Source.id)
    ).all()
    def observed(s: Source) -> bool:
        return not s.is_mock and s.source_type not in ESTIMATE_BASES

    real = sum(n for s, n, _ in rows if observed(s))
    estimated = sum(n for s, n, _ in rows if s.source_type in ESTIMATE_BASES)
    mock = sum(n for s, n, _ in rows if s.is_mock)
    newest_real = max((d for s, _, d in rows if observed(s) and d), default=None)
    mock_in_use = ctx.engine.include_mock and mock > 0
    return MetaOut(
        environment=ctx.settings.environment, method_version=METHOD_VERSION, regions=REGION_CURRENCY,
        data_status="real" if real else "estimated" if estimated else "mock_only" if mock_in_use else "none",
        real_observations=real, estimated_observations=estimated, mock_observations=mock,
        mock_data_in_use=mock_in_use,
        newest_real_observation=newest_real, freshness_days=ctx.settings.freshness_days,
        sources=[SourceOut(id=s.id, name=s.name, source_type=s.source_type, collection_method=s.collection_method,
                           markets=s.markets, verified=s.verified, is_mock=s.is_mock, observation_count=n,
                           newest_observation=d)
                 for s, n, d in rows if ctx.engine.include_mock or not s.is_mock],
    )


def model_out(session: Session, model: DeviceModel, status: dict[tuple[str, str], str]) -> CatalogueModelOut:
    """Shared by /api/catalogue and /api/v1/products."""
    return CatalogueModelOut(
        id=model.id, manufacturer=model.manufacturer, name=model.name, release_date=model.release_date,
        storage_gb=catalogue.variants(session, model.id), oem_codes=catalogue.aliases(session, model.id),
        evidence={r: status.get((model.id, r), "insufficient") for r in REGION_CURRENCY},  # type: ignore[misc]
    )


@router.get("/catalogue", response_model=list[CatalogueModelOut])
def search_catalogue(request: Request, session: DbSession,
                     q: str = Query("", max_length=80)) -> list[CatalogueModelOut]:
    status = get_ctx(request).engine.evidence_status(session)
    return [model_out(session, m, status) for m in catalogue.search(session, q)]


@router.get("/catalogue/{model_id}", response_model=CatalogueModelOut)
def get_model(model_id: str, request: Request, session: DbSession) -> CatalogueModelOut:
    model = session.get(DeviceModel, model_id)
    if model is None:
        raise ApiError(404, "unsupported_model", "That model is not in the FlipValue catalogue.")
    return model_out(session, model, get_ctx(request).engine.evidence_status(session))


@router.post("/valuations", response_model=PublicValuation)
def create_public_valuation(body: PublicValuationRequest, request: Request,
                            session: DbSession) -> PublicValuation:
    ctx = get_ctx(request)
    result = public_valuation(session, ctx.engine, body, ctx.offer_policy)
    request.state.method_version = result.method_version
    if result.status == "unavailable":
        request.state.error_code = "no_data_for_condition"
    return result


@router.post("/decision", response_model=DecisionResult)
def decision(body: DecisionInput) -> DecisionResult:
    return decide(body)


@router.post("/saved", response_model=SaveResponse, status_code=201)
def save_valuation(body: PublicValuationRequest, request: Request,
                   session: DbSession) -> SaveResponse:
    """Re-runs the valuation server-side and stores the request and result (no personal data)."""
    ctx = get_ctx(request)
    result = public_valuation(session, ctx.engine, body, ctx.offer_policy)
    saved_id, delete_token = secrets.token_urlsafe(16), secrets.token_urlsafe(24)
    session.add(SavedValuation(id=saved_id, delete_token_hash=hash_key(delete_token),
                               request_json=body.model_dump_json(), result_json=result.model_dump_json()))
    return SaveResponse(id=saved_id, delete_token=delete_token, result=result)


def _saved(session: Session, saved_id: str) -> SavedValuation:
    saved = session.get(SavedValuation, saved_id) if len(saved_id) <= 32 else None
    if saved is None:
        raise ApiError(404, "not_found", "No saved valuation with that link (it may have been deleted).")
    return saved


@router.get("/saved/{saved_id}", response_model=SavedValuationOut)
def get_saved(saved_id: str, session: DbSession) -> SavedValuationOut:
    saved = _saved(session, saved_id)
    return SavedValuationOut(id=saved.id, created_at=saved.created_at,
                             result=PublicValuation.model_validate(json.loads(saved.result_json)))


@router.get("/saved/{saved_id}/request", response_model=PublicValuationRequest)
def get_saved_request(saved_id: str, session: DbSession) -> PublicValuationRequest:
    """The answers behind a saved valuation, so it can be edited and recalculated."""
    return PublicValuationRequest.model_validate_json(_saved(session, saved_id).request_json)


@router.delete("/saved/{saved_id}", status_code=204)
def delete_saved(saved_id: str, session: DbSession,
                 x_delete_token: str = Header(default="", max_length=100)) -> None:
    saved = _saved(session, saved_id)
    if not hmac.compare_digest(hash_key(x_delete_token), saved.delete_token_hash):
        raise ApiError(403, "forbidden", "The delete token does not match this saved valuation.")
    session.delete(saved)


@router.get("/trends", response_model=TrendOut)
def trends(request: Request, session: DbSession, model_id: str = Query(max_length=80),
           region: str = Query(pattern="^[A-Z]{2}$"), grade: Grade = Query(),
           storage_gb: int | None = Query(default=None, ge=1, le=4096)) -> TrendOut:
    return trend_out(session, request, model_id, region, grade, storage_gb)


def trend_out(session: Session, request: Request, model_id: str, region: str, grade: str,
              storage_gb: int | None) -> TrendOut:
    """Shared by /api/trends and /api/v1/trends, so both return the same JSON."""
    engine = get_ctx(request).engine
    model = session.get(DeviceModel, model_id)
    if model is None:
        raise ApiError(404, "unsupported_model", "That model is not in the FlipValue catalogue.")
    if region not in REGION_CURRENCY:
        raise ApiError(422, "unsupported_region", f"Region {region} is not supported.")
    try:
        device = engine.match_storage(session, model, storage_gb)
    except EngineError as exc:
        raise ApiError(404, exc.code, exc.message) from exc
    # Since the phone's release (the estimate curve starts there), at least the last two years, at most ten.
    today = engine.clock()
    months = min(120, max(24, (today - (model.release_date or today)).days // 30 + 2))
    series = engine.trend(session, model.id, device.storage_gb, region, grade, months)
    available = any(len(points) >= 3 for points in series.values())
    return TrendOut(
        model_id=model.id, storage_gb=device.storage_gb, region=region, currency=REGION_CURRENCY[region],
        grade=grade, available=available,
        reason=None if available else (
            "Not enough price history: a chart needs at least 3 months with "
            f"{MIN_OBSERVATIONS}+ observations or estimates each. Synthetic (mock) data is never shown as history."),
        series={basis: [TrendPoint(**p) for p in points] for basis, points in series.items()},
        min_observations_per_month=MIN_OBSERVATIONS,
    )
