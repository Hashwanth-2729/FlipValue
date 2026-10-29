"""Structured JSON logs and the aggregate request log. Never logs keys, bodies or IP addresses."""

from __future__ import annotations

import json
import logging
import sys
from datetime import timedelta

from sqlalchemy import or_, update
from sqlalchemy.orm import Session, sessionmaker

from flipvalue.db.models import ApiClient, ApiUsageEvent, RequestLog, utcnow
from flipvalue.db.session import transaction

logger = logging.getLogger("flipvalue")


class JsonFormatter(logging.Formatter):
    """One JSON object per line. `severity` and `message` are the keys Cloud Logging reads from stdout."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {"time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "severity": record.levelname,
                   "logger": record.name, "message": record.getMessage()}
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    if any(getattr(h, "_flipvalue", False) for h in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._flipvalue = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def record_usage(sessions: sessionmaker[Session], key, **fields) -> None:
    """One usage event per authenticated API request, and the key's last-used time (at most once a minute)."""
    try:
        with transaction(sessions) as session:
            session.add(ApiUsageEvent(client=key.label, api_client_id=key.client_id, **fields))
            if key.client_id is not None:
                now = utcnow()
                session.execute(update(ApiClient).where(
                    ApiClient.id == key.client_id,
                    or_(ApiClient.last_used_at.is_(None), ApiClient.last_used_at < now - timedelta(minutes=1)))
                    .values(last_used_at=now))
    except Exception as exc:  # pragma: no cover - depends on DB failure
        logger.warning("usage write failed", extra={"fields": {"error": type(exc).__name__}})


def record_request(sessions: sessionmaker[Session], **fields) -> None:
    """Best effort: a logging failure must never fail the request."""
    try:
        with transaction(sessions) as session:
            session.add(RequestLog(**fields))
    except Exception as exc:  # pragma: no cover - depends on DB failure
        logger.warning("request log write failed", extra={"fields": {"error": type(exc).__name__}})
