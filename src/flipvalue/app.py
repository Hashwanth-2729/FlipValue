"""FastAPI application. Run with: uvicorn flipvalue.app:create_app --factory"""

from __future__ import annotations

import asyncio
import re
import secrets
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from flipvalue import __version__
from flipvalue.config import Settings
from flipvalue.context import AppContext, build_providers, offer_policy
from flipvalue.db.models import ApiClient, DeviceModel, utcnow
from flipvalue.db.session import database_ready, make_engine, make_sessionmaker, transaction
from flipvalue.engine import Engine
from flipvalue.errors import ApiError, error_response
from flipvalue.marketplace.providers import Provider
from flipvalue.observability import configure_logging, logger, record_request, record_usage
from flipvalue.routes import account, admin, developer, market, partner, public
from flipvalue.security import Authenticator, RateLimiter, client_fingerprint

SUPPORTED_API_VERSION = "1"
ADMIN_RATE_LIMIT = 120
IMPORT_MAX_BYTES = 2_100_000
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
_HTTP_CODES = {403: "forbidden", 404: "not_found", 405: "method_not_allowed", 409: "conflict"}
_CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
_API_PREFIXES = ("/v1/", "/api/", "/admin/api/")


def _request_id(header: str | None) -> str:
    return header if header and _REQUEST_ID.match(header) else str(uuid.uuid4())


def _describe(errors: list[dict]) -> str:
    if any(e.get("type") == "json_invalid" for e in errors):
        return "Request body is not valid JSON."
    parts = []
    for e in errors[:3]:
        field = ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "header", "path")) or "body"
        parts.append(f"{field}: {e['msg']}")
    if len(errors) > 3:
        parts.append(f"(+{len(errors) - 3} more)")
    return "; ".join(parts)


def forwarded_client_ip(request: Request, settings: Settings) -> str:
    """The client address for rate limiting.

    Behind trusted proxies, take the X-Forwarded-For entry `proxy_hops` places from the right (each proxy appends the
    address it received the request from). Never the left-most entry: a client can write anything there.
    """
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if not (settings.trust_proxy and forwarded):
        return peer
    entries = [e.strip() for e in forwarded.split(",") if e.strip()]
    return entries[-settings.proxy_hops] if len(entries) >= settings.proxy_hops else (entries[0] if entries else peer)


def _channel(path: str) -> str:
    if path.startswith("/v1/"):
        return "partner"
    if path.startswith("/admin/api"):
        return "admin"
    if path.startswith("/api/v1/") and path != "/api/v1/health":
        return "developer"
    if path.startswith("/api/"):
        return "public"
    return "other"


def _usage_path(path: str) -> str:
    """Group ids so usage is counted per endpoint, e.g. /api/v1/valuations/{id}."""
    parts = path.split("/")
    if len(parts) == 5 and parts[1:4] in (["api", "v1", "valuations"], ["api", "v1", "products"]):
        parts[4] = "{id}"
    return "/".join(parts)[:100]


def create_app(settings: Settings | None = None, *, clock: Callable[[], date] = date.today,
               wall_clock: Callable[[], float] = time.time,
               providers: Sequence[Provider] | None = None,
               now: Callable[[], datetime] = utcnow) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging()
    db = make_engine(settings.database_url, settings.db_pool_size, settings.db_max_overflow)
    sessions = make_sessionmaker(db)
    ctx = AppContext(
        settings=settings, db=db, sessions=sessions,
        engine=Engine(settings.freshness_days, include_mock=not settings.is_production, clock=clock),
        auth=Authenticator(sessions, {"partner": settings.api_keys, "admin": settings.admin_keys}),
        limiter=RateLimiter(sessions, clock=wall_clock),
        hash_salt=settings.hash_salt or secrets.token_hex(16),
        providers=build_providers(settings) if providers is None else providers,
        offer_policy=offer_policy(settings, now),
    )

    app = FastAPI(
        title="FlipValue API",
        version=__version__,
        description="Phone resale valuations and marketplace prices. Developer API (/api/v1, X-API-Key with "
                    "scopes), FixMyTech partner API (/v1), public website API (/api), operator API (/admin/api). "
                    "Values are gross expected sale prices before selling fees.",
    )
    app.state.ctx = ctx

    def fail(request: Request, status: int, code: str, message: str,
             headers: dict[str, str] | None = None) -> JSONResponse:
        request.state.error_code = code
        return error_response(status, code, message, request.state.request_id, headers)

    def client_ip(request: Request) -> str:
        return forwarded_client_ip(request, settings)

    app.state.client_ip = client_ip

    async def guard(request: Request, channel: str) -> Response | None:
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            limit = IMPORT_MAX_BYTES if request.url.path == "/admin/api/imports" else settings.max_body_bytes
            length = request.headers.get("content-length")
            if length is None and request.headers.get("transfer-encoding"):
                return fail(request, 411, "length_required", "Send a Content-Length header.")
            if length is not None and (not length.isdigit() or int(length) > limit):
                return fail(request, 413, "payload_too_large", f"Request body must be at most {limit} bytes.")

        if channel == "admin":
            client = await run_in_threadpool(ctx.auth.identify, request.headers.get("x-api-key"), "admin")
            if client is None:
                return fail(request, 401, "unauthorized", "Missing or invalid X-API-Key.")
            request.state.client = client
            retry = await run_in_threadpool(ctx.limiter.hit, f"admin:{client}", ADMIN_RATE_LIMIT)
            if retry is not None:
                return fail(request, 429, "rate_limited", "Too many requests; retry later.",
                            {"Retry-After": str(retry)})
        elif channel in ("partner", "developer"):
            # Self-service and partner keys share one identity, one minute limit and one daily quota.
            info = await run_in_threadpool(ctx.auth.lookup, request.headers.get("x-api-key"), "partner")
            if info is None:
                return fail(request, 401, "unauthorized", "Missing or invalid X-API-Key.")
            request.state.client, request.state.key = info.label, info
            own = info.account_id is not None
            per_minute = info.rate_limit_per_minute or (
                settings.developer_rate_limit_per_minute if own else settings.rate_limit_per_minute)
            per_day = info.daily_quota or (settings.developer_daily_quota if own else None)
            minute = await run_in_threadpool(ctx.limiter.consume, f"key:{info.label}", per_minute)
            request.state.rate_headers = headers = {
                "X-RateLimit-Limit": str(per_minute), "X-RateLimit-Remaining": str(minute.remaining),
                "X-RateLimit-Reset": str(minute.reset_s)}
            request.state.limits = {"minute": per_minute, "minute_remaining": minute.remaining, "day": per_day,
                                    "day_remaining": None}
            if not minute.allowed:
                return fail(request, 429, "rate_limited", "Too many requests; retry later.",
                            {**headers, "Retry-After": str(minute.reset_s)})
            if per_day is not None:
                day = await run_in_threadpool(ctx.limiter.consume, f"day:{info.label}", per_day, 86400)
                headers.update({"X-Quota-Limit": str(per_day), "X-Quota-Remaining": str(day.remaining),
                                "X-Quota-Reset": str(day.reset_s)})
                request.state.limits["day_remaining"] = day.remaining
                if not day.allowed:
                    return fail(request, 429, "quota_exceeded",
                                f"Daily quota of {per_day} requests used; it resets at 00:00 UTC.",
                                {**headers, "Retry-After": str(day.reset_s)})
            if channel == "partner":
                version = request.headers.get("flipvalue-api-version")
                if version is not None and version.strip() != SUPPORTED_API_VERSION:
                    return fail(request, 400, "unsupported_api_version",
                                f"FlipValue-API-Version must be {SUPPORTED_API_VERSION}.")
                if "valuation:read" not in info.scopes:
                    return fail(request, 403, "insufficient_scope", "This key does not have the valuation:read "
                                                                    "scope.")
        elif channel == "public":
            reading = request.method in ("GET", "HEAD", "OPTIONS")
            kind = "r" if reading else "w"
            factor = 4 if reading else 1
            # Per client first, then a cap on all anonymous traffic together: forwarded IPs can be spoofed, the
            # global cap bounds database load and cost regardless.
            for bucket, per_minute, message in (
                (f"ip:{kind}:{client_fingerprint(client_ip(request), ctx.hash_salt)}",
                 settings.public_rate_limit_per_minute * factor, "Too many requests from your network; wait a moment."),
                (f"global:{kind}", settings.public_global_rate_limit_per_minute * factor,
                 "FlipValue is busy right now; please try again shortly."),
            ):
                retry = await run_in_threadpool(ctx.limiter.hit, bucket, per_minute)
                if retry is not None:
                    return fail(request, 429, "rate_limited", message, {"Retry-After": str(retry)})
        return None

    @app.middleware("http")
    async def gatekeeper(request: Request, call_next):
        request.state.request_id = request_id = _request_id(request.headers.get("x-request-id"))
        request.state.error_code = request.state.method_version = None
        request.state.client = request.state.key = request.state.rate_headers = None
        path = request.url.path
        channel = _channel(path)
        started = time.perf_counter()
        try:
            response = await guard(request, channel)
            if response is None:
                response = await asyncio.wait_for(call_next(request), timeout=settings.request_timeout_s)
        except TimeoutError:
            response = fail(request, 503, "service_timeout", "The request took too long; it is safe to retry.",
                            {"Retry-After": "1"})
        except Exception as exc:  # last resort: no stack trace in the response or the log
            logger.error("unhandled exception", extra={"fields": {"error": type(exc).__name__,
                                                                   "request_id": request_id}})
            response = fail(request, 500, "internal_error", "Internal server error.")

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if not path.startswith(("/docs", "/redoc")):
            response.headers["Content-Security-Policy"] = _CSP
        if path.startswith(_API_PREFIXES):
            response.headers["Cache-Control"] = "no-store"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        for name, value in (request.state.rate_headers or {}).items():
            response.headers.setdefault(name, value)

        latency = int((time.perf_counter() - started) * 1000)
        if channel != "other":
            await run_in_threadpool(record_request, sessions, channel=channel, http_method=request.method,
                                    path=path[:100], status=response.status_code,
                                    error_code=request.state.error_code,
                                    method_version=request.state.method_version, latency_ms=latency)
        if request.state.key is not None:
            await run_in_threadpool(record_usage, sessions, request.state.key, http_method=request.method,
                                    path=_usage_path(path), status=response.status_code,
                                    error_code=request.state.error_code, latency_ms=latency)
        logger.info("request", extra={"fields": {
            "method": request.method, "path": path[:200], "status": response.status_code, "latency_ms": latency,
            "request_id": request_id, "channel": channel, "client": request.state.client,
            "error_code": request.state.error_code}})
        return response

    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                           allow_methods=["GET", "POST", "DELETE"],
                           allow_headers=["Content-Type", "X-Delete-Token", "X-Request-ID"])

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return fail(request, exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return fail(request, 422, "validation_error", _describe(list(exc.errors())))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return fail(request, exc.status_code, _HTTP_CODES.get(exc.status_code, "http_error"), str(exc.detail))

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        """Liveness: the process is serving. Does not touch the database or any market source."""
        return {"status": "ok"}

    @app.get("/ready", include_in_schema=False)
    def ready() -> JSONResponse:
        """Readiness: the database is reachable and migrated, and the catalogue is loaded."""
        checks = {"database": database_ready(db), "catalogue": False, "partner_keys": bool(settings.api_keys)}
        if checks["database"]:
            with transaction(sessions) as session:
                checks["catalogue"] = bool(session.scalar(select(func.count(DeviceModel.id))))
                if not checks["partner_keys"]:
                    checks["partner_keys"] = bool(session.scalar(
                        select(func.count(ApiClient.id)).where(ApiClient.role == "partner",
                                                               ApiClient.revoked_at.is_(None))))
        ok = checks["database"] and checks["catalogue"]
        return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks},
                            status_code=200 if ok else 503)

    app.include_router(partner.router)
    app.include_router(developer.router)
    app.include_router(market.router)
    app.include_router(account.router)
    app.include_router(public.router)
    app.include_router(admin.router)
    _mount_frontend(app, settings.frontend_dist)
    return app


def _mount_frontend(app: FastAPI, dist: Path | None) -> None:
    """Serve the built website (frontend/dist) with client-side routing, when it has been built."""
    if dist is None or not (dist / "index.html").is_file():
        return
    root = dist.resolve()
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if f"/{path}".startswith(_API_PREFIXES):
            raise StarletteHTTPException(404, "Not Found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(root / "index.html")
