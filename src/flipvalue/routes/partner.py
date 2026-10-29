"""POST /v1/valuations - the FixMyTech integration contract. Auth and rate limits are applied by middleware."""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from sqlalchemy.exc import IntegrityError

from flipvalue.context import DbSession, get_ctx
from flipvalue.db.models import IdempotencyRecord
from flipvalue.errors import ApiError
from flipvalue.schemas import ErrorResponse, Valuation, ValuationRequest
from flipvalue.services import partner_valuation

router = APIRouter(tags=["partner"])

# Declared so the OpenAPI document shows the header; middleware enforces it before the body is parsed.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@router.post(
    "/v1/valuations",
    response_model=Valuation,
    dependencies=[Security(api_key_header)],
    responses={
        400: {"model": ErrorResponse, "description": "unsupported_api_version"},
        401: {"model": ErrorResponse, "description": "unauthorized: missing, invalid or revoked X-API-Key"},
        404: {"model": ErrorResponse, "description": "unsupported_model or no_data_for_condition"},
        413: {"model": ErrorResponse, "description": "payload_too_large"},
        422: {"model": ErrorResponse, "description": "validation_error, unsupported_region, "
                                                     "unsupported_currency or idempotency_key_reused"},
        429: {"model": ErrorResponse, "description": "rate_limited; see Retry-After"},
        503: {"model": ErrorResponse, "description": "service_timeout; safe to retry"},
    },
)
def create_valuation(body: ValuationRequest, request: Request,
                     session: DbSession) -> JSONResponse:
    """Value a phone as it is and, when `repair_scenario` is given, after that repair.

    Side-effect free. A repeated `Idempotency-Key` with the same body replays the stored response; with a
    different body it is rejected (422 `idempotency_key_reused`).
    """
    ctx = get_ctx(request)
    request_id = request.state.request_id
    client = request.state.client
    canonical = json.dumps(body.model_dump(mode="json", exclude_none=True), sort_keys=True)
    request_hash = hashlib.sha256(canonical.encode()).hexdigest()
    idem_key = request.headers.get("idempotency-key")
    if idem_key is not None and not 1 <= len(idem_key) <= 100:
        raise ApiError(422, "validation_error", "Idempotency-Key must be 1-100 characters.")

    if idem_key:
        record = session.get(IdempotencyRecord, (client, idem_key))
        if record is not None:
            if record.request_hash != request_hash:
                raise ApiError(422, "idempotency_key_reused",
                               "This Idempotency-Key was already used with a different request body.")
            payload = json.loads(record.response_body)
            if "error" in payload:
                payload["error"]["request_id"] = request_id
                request.state.error_code = payload["error"]["code"]
            return JSONResponse(payload, status_code=record.status_code, headers={"Idempotent-Replayed": "true"})

    try:
        status, payload = 200, partner_valuation(session, ctx.engine, body).model_dump(mode="json")
        request.state.method_version = payload["method"]
    except ApiError as exc:
        request.state.error_code = exc.code
        status = exc.status
        payload = {"error": {"code": exc.code, "message": exc.message, "request_id": request_id}}

    if idem_key:
        try:
            with session.begin_nested():
                session.add(IdempotencyRecord(client=client, key=idem_key, request_hash=request_hash,
                                              status_code=status, response_body=json.dumps(payload)))
        except IntegrityError:
            pass  # a concurrent retry stored the same deterministic result first
    return JSONResponse(payload, status_code=status)
