"""Developer API /api/v1 (docs/API_REFERENCE.md). Middleware authenticates X-API-Key, applies the per-key minute limit
and daily quota, and records usage; routes enforce scopes. /api/v1/health needs no key.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Security
from pydantic import BaseModel

from flipvalue import __version__, catalogue
from flipvalue.config import REGION_CURRENCY
from flipvalue.context import DbSession, get_ctx
from flipvalue.db.models import ApiUsageEvent, ApiValuation, DeviceModel
from flipvalue.decision import DecisionInput, DecisionResult, decide
from flipvalue.errors import ApiError
from flipvalue.routes.account import usage_summary
from flipvalue.routes.market import market_prices, price_history
from flipvalue.routes.partner import api_key_header
from flipvalue.routes.public import model_out, trend_out
from flipvalue.schemas import ApiValuationRequest, CatalogueModelOut, ErrorResponse, Grade, TrendOut, ValuationV1
from flipvalue.security import KeyInfo
from flipvalue.services import api_valuation

router = APIRouter(prefix="/api/v1", tags=["developer"])

ERRORS = {
    401: {"model": ErrorResponse, "description": "unauthorized: missing, invalid or revoked X-API-Key"},
    403: {"model": ErrorResponse, "description": "insufficient_scope"},
    422: {"model": ErrorResponse, "description": "validation_error, unsupported_region, unsupported_currency"},
    429: {"model": ErrorResponse, "description": "rate_limited or quota_exceeded; see Retry-After"},
}


def key_info(request: Request) -> KeyInfo:
    info = getattr(request.state, "key", None)
    if info is None:  # pragma: no cover - middleware guarantees it
        raise ApiError(401, "unauthorized", "Missing or invalid X-API-Key.")
    return info


def scope(name: str):
    def check(request: Request) -> KeyInfo:
        info = key_info(request)
        if name not in info.scopes:
            raise ApiError(403, "insufficient_scope", f"This key does not have the {name} scope.")
        return info
    return Depends(check)


@router.get("/health")
def health(request: Request) -> dict:
    """No key needed. Reports the API version and whether marketplace providers are configured (no secrets)."""
    ctx = get_ctx(request)
    return {"status": "ok", "api_version": "1", "service_version": __version__,
            "environment": ctx.settings.environment,
            "providers": {p.spec.id: ("configured" if p.configured() else
                                      "manual_only" if not p.automated else "not_configured")
                          for p in ctx.providers}}


@router.post("/valuations", response_model=ValuationV1, status_code=201, responses={
    **ERRORS, 404: {"model": ErrorResponse, "description": "unsupported_model or no_data_for_condition (storage)"}},
    dependencies=[Security(api_key_header)])
def create_valuation(body: ApiValuationRequest, request: Request, session: DbSession,
                     info: KeyInfo = scope("valuation:read")) -> ValuationV1:
    """Value a phone: private sale, buyback, refurbished retail, original retail and (with `repair_scenario`)
    after repair. Values without enough evidence come back `available: false` with a reason, never guessed."""
    ctx = get_ctx(request)
    valuation_id = "val_" + secrets.token_urlsafe(18)
    result = api_valuation(session, ctx.engine, body, ctx.offer_policy, valuation_id)
    request.state.method_version = result.method
    session.add(ApiValuation(id=valuation_id, owner=info.owner(), request_json=body.model_dump_json(),
                             result_json=result.model_dump_json()))
    return result


@router.get("/valuations/{valuation_id}", response_model=ValuationV1, responses=ERRORS,
            dependencies=[Security(api_key_header)])
def get_valuation(valuation_id: str, session: DbSession, info: KeyInfo = scope("valuation:read")) -> ValuationV1:
    """A valuation created by this account (or this key). Others' valuations answer 404, like unknown ids."""
    row = session.get(ApiValuation, valuation_id) if len(valuation_id) <= 40 else None
    if row is None or row.owner != info.owner():
        raise ApiError(404, "not_found", "No valuation with that id for this API key.")
    return ValuationV1.model_validate_json(row.result_json)


@router.get("/market-prices", responses=ERRORS, dependencies=[Security(api_key_header)])
def get_market_prices(request: Request, session: DbSession, product_id: str = Query(max_length=80),
                      storage_gb: int | None = Query(default=None, ge=1, le=4096),
                      region: str = Query("IN", pattern="^[A-Z]{2}$"),
                      _: KeyInfo = scope("market_prices:read")) -> dict:
    """Current offers for exactly this product and storage, grouped by condition, plus labelled alternatives and
    provider status. Only offers actually retrieved from a source are returned."""
    return market_prices(session, request, product_id, storage_gb, region)


@router.get("/price-history", responses=ERRORS, dependencies=[Security(api_key_header)])
def get_price_history(request: Request, session: DbSession, product_id: str = Query(max_length=80),
                      storage_gb: int | None = Query(default=None, ge=1, le=4096),
                      region: str = Query("IN", pattern="^[A-Z]{2}$"),
                      condition: Literal["new", "refurbished", "used"] = Query("new"),
                      days: int = Query(90, ge=7, le=730), _: KeyInfo = scope("price_history:read")) -> dict:
    """Observed prices by day (lowest per source), with gaps and observation counts. No interpolation."""
    return price_history(session, request, product_id, storage_gb, region, condition, days)


class ProductOut(CatalogueModelOut):
    """The website's catalogue entry (/api/catalogue: oem_codes, evidence) plus the earlier v1 fields."""

    model_codes: list[str]
    regions: dict[str, str]


def _product(session, m: DeviceModel, status: dict[tuple[str, str], str]) -> ProductOut:
    base = model_out(session, m, status)
    return ProductOut(**base.model_dump(), model_codes=base.oem_codes, regions=REGION_CURRENCY)


@router.get("/products", response_model=list[ProductOut], responses=ERRORS,
            dependencies=[Security(api_key_header), Depends(key_info)])
def list_products(request: Request, session: DbSession, q: str = Query("", max_length=80)) -> list[ProductOut]:
    """Catalogue search by name or model code (a code with a suffix such as SM-G991B/DS also finds SM-G991B).
    Any valid key."""
    status = get_ctx(request).engine.evidence_status(session)
    return [_product(session, m, status) for m in catalogue.search(session, q)]


@router.get("/products/{product_id}", response_model=ProductOut,
            responses={**ERRORS, 404: {"model": ErrorResponse, "description": "unsupported_model"}},
            dependencies=[Security(api_key_header), Depends(key_info)])
def get_product(product_id: str, request: Request, session: DbSession) -> ProductOut:
    model = session.get(DeviceModel, product_id)
    if model is None:
        raise ApiError(404, "unsupported_model", "That product is not in the FlipValue catalogue.")
    return _product(session, model, get_ctx(request).engine.evidence_status(session))


@router.get("/trends", response_model=TrendOut,
            responses={**ERRORS, 404: {"model": ErrorResponse, "description": "unsupported_model"}},
            dependencies=[Security(api_key_header)])
def get_trends(request: Request, session: DbSession, product_id: str | None = Query(None, max_length=80),
               model_id: str | None = Query(None, max_length=80), region: str = Query("IN", pattern="^[A-Z]{2}$"),
               grade: Grade = Query("good"), storage_gb: int | None = Query(default=None, ge=1, le=4096),
               _: KeyInfo = scope("price_history:read")) -> TrendOut:
    """Same JSON as GET /api/trends: monthly resale prices since release (observed series and the labelled
    `estimate` series). `available: false` with a `reason` when there is not enough history."""
    product = product_id or model_id
    if not product:
        raise ApiError(422, "validation_error", "product_id (or model_id) is required.")
    return trend_out(session, request, product, region, grade, storage_gb)


@router.post("/decision", response_model=DecisionResult, responses=ERRORS, dependencies=[Security(api_key_header)])
def post_decision(body: DecisionInput, _: KeyInfo = scope("valuation:read")) -> DecisionResult:
    """Same body and response as POST /api/decision: repair-or-sell scenarios from values you supply."""
    return decide(body)


class UsageOut(BaseModel):
    key: dict
    limits: dict
    current: dict
    days: int
    total: int
    by_day: list[dict]
    by_endpoint: dict[str, int]
    by_status: dict[str, int]
    generated_at: datetime


@router.get("/usage", response_model=UsageOut, responses=ERRORS, dependencies=[Security(api_key_header)])
def usage(request: Request, session: DbSession, days: int = Query(30, ge=1, le=90)) -> UsageOut:
    """Usage of the calling key only. A key can never read another key's usage."""
    info = key_info(request)
    limits = request.state.limits
    total, by_day, endpoints, statuses = usage_summary(session, ApiUsageEvent.client == info.label, days)
    return UsageOut(
        key={"label": info.label.split("-", 2)[-1] if info.client_id else "environment key",
             "scopes": list(info.scopes)},
        limits={"rate_limit_per_minute": limits["minute"], "daily_quota": limits["day"]},
        current={"minute_remaining": limits["minute_remaining"], "day_remaining": limits["day_remaining"]},
        days=days, total=total, by_day=[d.model_dump() for d in by_day], by_endpoint=endpoints,
        by_status=statuses, generated_at=datetime.now().astimezone(),
    )
