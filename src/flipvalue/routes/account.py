"""Accounts (/api/account): sign-in, self-service API keys and their usage, watchlist and price alerts.

Authentication is an HttpOnly, SameSite=Strict session cookie. Every state-changing request must also carry
`X-FlipValue-Client: web`: a custom header a cross-site form cannot send and CORS does not allow, so a forged
request from another site is refused even if a browser attached the cookie.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from flipvalue import accounts, catalogue
from flipvalue.config import REGION_CURRENCY
from flipvalue.context import DbSession, get_ctx
from flipvalue.db.models import (
    Account,
    ApiClient,
    ApiUsageEvent,
    AuditLog,
    DeviceModel,
    MarketplaceOffer,
    PriceAlert,
    Source,
    WatchlistItem,
    utcnow,
)
from flipvalue.errors import ApiError
from flipvalue.security import SCOPES, client_fingerprint, issue_key, parse_scopes, revoke_key

router = APIRouter(prefix="/api/account", tags=["account"])
CSRF_HEADER = "x-flipvalue-client"
LOGIN_ATTEMPTS_PER_MINUTE = 10


def _audit(session, actor: str, action: str, detail: str) -> None:
    session.add(AuditLog(actor=actor[:80], action=action, detail=detail))


def require_web_client(request: Request) -> None:
    if request.method not in ("GET", "HEAD") and request.headers.get(CSRF_HEADER) != "web":
        raise ApiError(403, "forbidden", "Missing X-FlipValue-Client header.")


def current_account(request: Request, session: DbSession) -> Account:
    require_web_client(request)
    account = accounts.account_for(session, request.cookies.get(accounts.SESSION_COOKIE))
    if account is None:
        raise ApiError(401, "not_signed_in", "Sign in to continue.")
    request.state.client = f"acct-{account.id}"
    return account


CurrentAccount = Annotated[Account, Depends(current_account)]


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(accounts.SESSION_COOKIE, token, max_age=accounts.SESSION_DAYS * 86400, httponly=True,
                        secure=get_ctx(request).settings.cookie_secure, samesite="strict", path="/api/account")


def _limit_login(request: Request, email: str) -> None:
    ctx = get_ctx(request)
    ip = client_fingerprint(request.app.state.client_ip(request), ctx.hash_salt)
    for bucket, per_minute in ((f"login:ip:{ip}", LOGIN_ATTEMPTS_PER_MINUTE),
                               (f"login:em:{client_fingerprint(email.strip().lower(), ctx.hash_salt)}", 5)):
        retry = ctx.limiter.hit(bucket, per_minute)
        if retry is not None:
            raise ApiError(429, "rate_limited", "Too many sign-in attempts; wait a minute.",
                           {"Retry-After": str(retry)})


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=accounts.MAX_PASSWORD)


class AccountOut(BaseModel):
    id: int
    email: str
    created_at: datetime
    limits: dict[str, int]
    scopes_available: list[str]


def _me(request: Request, account: Account) -> AccountOut:
    s = get_ctx(request).settings
    return AccountOut(id=account.id, email=account.email, created_at=account.created_at,
                      limits={"rate_limit_per_minute": s.developer_rate_limit_per_minute,
                              "daily_quota": s.developer_daily_quota, "max_keys": s.max_keys_per_account},
                      scopes_available=list(SCOPES))


@router.post("/register", response_model=AccountOut, status_code=201)
def register(body: Credentials, request: Request, response: Response, session: DbSession) -> AccountOut:
    require_web_client(request)
    if not get_ctx(request).settings.developer_signup:
        raise ApiError(403, "signup_closed", "New accounts are not open; contact the FlipValue operator.")
    _limit_login(request, body.email)
    try:
        account = accounts.register(session, body.email, body.password)
    except accounts.AccountError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    _audit(session, f"acct-{account.id}", "account.register", "{}")
    _set_cookie(request, response, accounts.start_session(session, account))
    return _me(request, account)


@router.post("/login", response_model=AccountOut)
def login(body: Credentials, request: Request, response: Response, session: DbSession) -> AccountOut:
    require_web_client(request)
    _limit_login(request, body.email)
    account = accounts.authenticate(session, body.email, body.password)
    if account is None:
        raise ApiError(401, "invalid_credentials", "Email or password is incorrect.")
    _set_cookie(request, response, accounts.start_session(session, account))
    return _me(request, account)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, session: DbSession) -> None:
    require_web_client(request)
    accounts.end_session(session, request.cookies.get(accounts.SESSION_COOKIE))
    response.delete_cookie(accounts.SESSION_COOKIE, path="/api/account")


@router.get("/me", response_model=AccountOut)
def me(request: Request, account: CurrentAccount) -> AccountOut:
    return _me(request, account)


# --- API keys --------------------------------------------------------------------------------------------------


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[Literal["valuation:read", "market_prices:read", "price_history:read"]] = Field(min_length=1)


class KeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    scopes: list[str]
    status: Literal["active", "revoked"]
    created_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    rate_limit_per_minute: int
    daily_quota: int
    requests_today: int
    requests_30d: int


class NewKeyOut(KeyOut):
    key: str = Field(description="Shown once. FlipValue stores only a SHA-256 verifier and cannot show it again.")


def _key_out(request: Request, session, c: ApiClient) -> KeyOut:
    s = get_ctx(request).settings
    now = utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def count(since: datetime) -> int:
        return session.scalar(select(func.count(ApiUsageEvent.id)).where(ApiUsageEvent.api_client_id == c.id,
                                                                        ApiUsageEvent.at >= since)) or 0

    return KeyOut(id=c.id, name=c.name, prefix=c.key_prefix, scopes=list(parse_scopes(c.scopes)),
                  status="revoked" if c.revoked_at else "active", created_at=c.created_at, revoked_at=c.revoked_at,
                  last_used_at=c.last_used_at,
                  rate_limit_per_minute=c.rate_limit_per_minute or s.developer_rate_limit_per_minute,
                  daily_quota=c.daily_quota or s.developer_daily_quota, requests_today=count(day_start),
                  requests_30d=count(now - timedelta(days=30)))


def _own_key(session, account: Account, key_id: int) -> ApiClient:
    client = session.get(ApiClient, key_id)
    if client is None or client.account_id != account.id:
        raise ApiError(404, "not_found", "No such key in your account.")  # same answer for other accounts' keys
    return client


@router.get("/keys", response_model=list[KeyOut])
def list_keys(request: Request, session: DbSession, account: CurrentAccount) -> list[KeyOut]:
    rows = session.scalars(select(ApiClient).where(ApiClient.account_id == account.id).order_by(ApiClient.id.desc()))
    return [_key_out(request, session, c) for c in rows]


@router.post("/keys", response_model=NewKeyOut, status_code=201)
def create_key(body: KeyIn, request: Request, session: DbSession, account: CurrentAccount) -> NewKeyOut:
    limit = get_ctx(request).settings.max_keys_per_account
    active = session.scalar(select(func.count(ApiClient.id)).where(ApiClient.account_id == account.id,
                                                                   ApiClient.revoked_at.is_(None))) or 0
    if active >= limit:
        raise ApiError(409, "key_limit_reached", f"An account can have at most {limit} active keys; revoke one first.")
    client, raw = issue_key(session, body.name.strip(), "partner", scopes=body.scopes, account_id=account.id)
    _audit(session, f"acct-{account.id}", "key.create",
           f'{{"id": {client.id}, "prefix": "{client.key_prefix}", "scopes": "{client.scopes}"}}')
    out = _key_out(request, session, client)
    return NewKeyOut(**out.model_dump(), key=raw)


@router.delete("/keys/{key_id}", response_model=KeyOut)
def revoke(key_id: int, request: Request, session: DbSession, account: CurrentAccount) -> KeyOut:
    client = _own_key(session, account, key_id)
    if revoke_key(session, client.id):
        _audit(session, f"acct-{account.id}", "key.revoke", f'{{"id": {client.id}}}')
    session.flush()
    return _key_out(request, session, client)


class UsageDay(BaseModel):
    date: str
    requests: int
    errors: int


class KeyUsageOut(BaseModel):
    key_id: int
    days: int
    total: int
    by_day: list[UsageDay]
    by_endpoint: dict[str, int]
    by_status: dict[str, int]


def usage_summary(session, client_filter, days: int) -> tuple[int, list[UsageDay], dict[str, int], dict[str, int]]:
    since = utcnow() - timedelta(days=days)
    rows = session.execute(select(ApiUsageEvent.at, ApiUsageEvent.path, ApiUsageEvent.status)
                           .where(client_filter, ApiUsageEvent.at >= since)).all()
    per_day: dict[str, list[int]] = {}
    endpoints: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for at, path, status in rows:
        d = per_day.setdefault(at.date().isoformat(), [0, 0])
        d[0] += 1
        d[1] += status >= 400
        endpoints[path] = endpoints.get(path, 0) + 1
        statuses[str(status)] = statuses.get(str(status), 0) + 1
    by_day = [UsageDay(date=k, requests=v[0], errors=v[1]) for k, v in sorted(per_day.items())]
    return len(rows), by_day, endpoints, statuses


@router.get("/keys/{key_id}/usage", response_model=KeyUsageOut)
def key_usage(key_id: int, session: DbSession, account: CurrentAccount,
              days: int = Query(30, ge=1, le=90)) -> KeyUsageOut:
    client = _own_key(session, account, key_id)
    total, by_day, endpoints, statuses = usage_summary(session, ApiUsageEvent.api_client_id == client.id, days)
    return KeyUsageOut(key_id=client.id, days=days, total=total, by_day=by_day, by_endpoint=endpoints,
                       by_status=statuses)


# --- watchlist and alerts --------------------------------------------------------------------------------------


class WatchIn(BaseModel):
    model_id: str = Field(max_length=80)
    storage_gb: int = Field(ge=1, le=4096)
    region: str = Field("IN", pattern="^[A-Z]{2}$")
    condition: Literal["new", "refurbished"]
    target_price: Decimal | None = Field(default=None, gt=0, le=10_000_000, decimal_places=2)


class WatchOut(BaseModel):
    id: int
    model_id: str
    product_name: str
    storage_gb: int
    region: str
    currency: str
    condition: str
    target_price: float | None
    created_at: datetime
    lowest_current_price: float | None
    lowest_current_retrieved_at: datetime | None
    unread_alerts: int


def _watch_out(request: Request, session, w: WatchlistItem) -> WatchOut:
    model = session.get(DeviceModel, w.model_id)
    policy = get_ctx(request).offer_policy
    q = (select(MarketplaceOffer).where(
        MarketplaceOffer.model_id == w.model_id, MarketplaceOffer.storage_gb == w.storage_gb,
        MarketplaceOffer.region == w.region, MarketplaceOffer.condition == w.condition,
        MarketplaceOffer.match_category.in_(("exact", "strong")), MarketplaceOffer.price_type != "buyback_quote",
        MarketplaceOffer.retrieved_at >= policy.now() - timedelta(days=policy.max_age_days))
        .order_by(MarketplaceOffer.price, MarketplaceOffer.retrieved_at.desc()).limit(1))
    if not policy.include_mock:
        q = q.where(MarketplaceOffer.is_mock.is_(False))
    lowest = session.scalars(q).first()
    unread = session.scalar(select(func.count(PriceAlert.id)).where(PriceAlert.watch_id == w.id,
                                                                    PriceAlert.read_at.is_(None))) or 0
    return WatchOut(id=w.id, model_id=w.model_id, product_name=f"{model.manufacturer} {model.name}",
                    storage_gb=w.storage_gb, region=w.region, currency=REGION_CURRENCY[w.region],
                    condition=w.condition, target_price=float(w.target_price) if w.target_price else None,
                    created_at=w.created_at, lowest_current_price=float(lowest.price) if lowest else None,
                    lowest_current_retrieved_at=lowest.retrieved_at if lowest else None, unread_alerts=unread)


@router.get("/watchlist", response_model=list[WatchOut])
def watchlist(request: Request, session: DbSession, account: CurrentAccount) -> list[WatchOut]:
    rows = session.scalars(select(WatchlistItem).where(WatchlistItem.account_id == account.id)
                           .order_by(WatchlistItem.id.desc()))
    return [_watch_out(request, session, w) for w in rows]


@router.post("/watchlist", response_model=WatchOut, status_code=201)
def add_watch(body: WatchIn, request: Request, session: DbSession, account: CurrentAccount) -> WatchOut:
    model = session.get(DeviceModel, body.model_id)
    if model is None:
        raise ApiError(404, "unsupported_model", "That product is not in the FlipValue catalogue.")
    if body.region not in REGION_CURRENCY:
        raise ApiError(422, "unsupported_region", f"Region {body.region} is not supported.")
    if body.storage_gb not in catalogue.variants(session, model.id):
        raise ApiError(422, "validation_error", f"{model.name} is not catalogued with {body.storage_gb} GB.")
    count = session.scalar(select(func.count(WatchlistItem.id)).where(WatchlistItem.account_id == account.id)) or 0
    if count >= 50:
        raise ApiError(409, "watchlist_full", "A watchlist can hold at most 50 products.")
    item = WatchlistItem(account_id=account.id, model_id=model.id, storage_gb=body.storage_gb, region=body.region,
                         condition=body.condition, target_price=body.target_price)
    try:
        with session.begin_nested():
            session.add(item)
    except IntegrityError as exc:
        raise ApiError(409, "conflict", "You already watch this product, storage and condition.") from exc
    return _watch_out(request, session, item)


@router.delete("/watchlist/{watch_id}", status_code=204)
def remove_watch(watch_id: int, session: DbSession, account: CurrentAccount) -> None:
    item = session.get(WatchlistItem, watch_id)
    if item is None or item.account_id != account.id:
        raise ApiError(404, "not_found", "No such watchlist item.")
    session.delete(item)


class AlertOut(BaseModel):
    id: int
    watch_id: int
    product_name: str
    storage_gb: int
    condition: str
    price: float
    currency: str
    reason: str
    source_name: str
    url: str | None
    is_mock: bool
    offer_retrieved_at: datetime
    created_at: datetime
    read: bool


@router.get("/alerts", response_model=list[AlertOut])
def alerts(session: DbSession, account: CurrentAccount) -> list[AlertOut]:
    rows = session.execute(
        select(PriceAlert, WatchlistItem, MarketplaceOffer, Source, DeviceModel)
        .join(WatchlistItem, WatchlistItem.id == PriceAlert.watch_id)
        .join(MarketplaceOffer, MarketplaceOffer.id == PriceAlert.offer_id)
        .join(Source, Source.id == MarketplaceOffer.source_id)
        .join(DeviceModel, DeviceModel.id == WatchlistItem.model_id)
        .where(WatchlistItem.account_id == account.id).order_by(PriceAlert.id.desc()).limit(100))
    return [AlertOut(id=a.id, watch_id=w.id, product_name=f"{m.manufacturer} {m.name}", storage_gb=w.storage_gb,
                     condition=w.condition, price=float(a.price), currency=o.currency, reason=a.reason,
                     source_name=s.name, url=o.url, is_mock=o.is_mock, offer_retrieved_at=o.retrieved_at,
                     created_at=a.created_at, read=a.read_at is not None)
            for a, w, o, s, m in rows]


@router.post("/alerts/{alert_id}/read", status_code=204)
def mark_read(alert_id: int, session: DbSession, account: CurrentAccount) -> None:
    alert = session.get(PriceAlert, alert_id)
    watch = session.get(WatchlistItem, alert.watch_id) if alert else None
    if alert is None or watch is None or watch.account_id != account.id:
        raise ApiError(404, "not_found", "No such alert.")
    alert.read_at = alert.read_at or utcnow()
