"""Marketplace prices for the website: provider status, current offers, observed price history. Anonymous.

The same functions back the developer API (/api/v1/market-prices, /api/v1/price-history).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy.orm import Session

from flipvalue.config import REGION_CURRENCY
from flipvalue.context import DbSession, get_ctx
from flipvalue.db.models import DeviceModel
from flipvalue.engine import EngineError
from flipvalue.errors import ApiError
from flipvalue.marketplace import service

router = APIRouter(prefix="/api/market", tags=["public"])

OfferCondition = Literal["new", "refurbished", "used"]


def resolve(session: Session, request: Request, model_id: str, storage_gb: int | None,
            region: str) -> tuple[DeviceModel, int]:
    model = session.get(DeviceModel, model_id)
    if model is None:
        raise ApiError(404, "unsupported_model", "That product is not in the FlipValue catalogue.")
    if region not in REGION_CURRENCY:
        raise ApiError(422, "unsupported_region", f"Region {region} is not supported.")
    try:
        device = get_ctx(request).engine.match_storage(session, model, storage_gb)
    except EngineError as exc:
        raise ApiError(422, "variant_required", exc.message) from exc
    return model, device.storage_gb


def market_prices(session: Session, request: Request, model_id: str, storage_gb: int | None, region: str) -> dict:
    ctx = get_ctx(request)
    model, storage = resolve(session, request, model_id, storage_gb, region)
    result = service.compare(session, model, storage, region, ctx.offer_policy)
    result["providers"] = service.provider_status(session, ctx.providers, ctx.offer_policy)
    result["product"] = {"id": model.id, "manufacturer": model.manufacturer, "name": model.name}
    return result


def price_history(session: Session, request: Request, model_id: str, storage_gb: int | None, region: str,
                  condition: str, days: int) -> dict:
    ctx = get_ctx(request)
    model, storage = resolve(session, request, model_id, storage_gb, region)
    result = service.history(session, model, storage, region, condition, days, ctx.offer_policy)
    result["resale_trend"] = {
        basis: [{"month": p["month"], "median": float(p["median"]), "count": p["count"]} for p in points]
        for basis, points in ctx.engine.trend(session, model.id, storage, region, "good").items()
    }
    return result


@router.get("/providers")
def providers(request: Request, session: DbSession) -> list[dict]:
    """Which marketplace sources are connected, failing, or need credentials or approval."""
    ctx = get_ctx(request)
    return service.provider_status(session, ctx.providers, ctx.offer_policy)


@router.get("/offers")
def offers(request: Request, session: DbSession, model_id: str = Query(max_length=80),
           storage_gb: int | None = Query(default=None, ge=1, le=4096),
           region: str = Query("IN", pattern="^[A-Z]{2}$")) -> dict:
    return market_prices(session, request, model_id, storage_gb, region)


@router.get("/history")
def history(request: Request, session: DbSession, model_id: str = Query(max_length=80),
            storage_gb: int | None = Query(default=None, ge=1, le=4096),
            region: str = Query("IN", pattern="^[A-Z]{2}$"), condition: OfferCondition = Query("new"),
            days: int = Query(90, ge=7, le=730)) -> dict:
    return price_history(session, request, model_id, storage_gb, region, condition, days)
