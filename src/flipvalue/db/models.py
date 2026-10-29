"""Tables. Keep in step with migrations/versions (tests/test_db.py checks for drift).

All datetimes are stored as naive UTC.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


# --- catalogue -------------------------------------------------------------------------------


class DeviceModel(Base):
    __tablename__ = "device_models"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    manufacturer: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    release_date: Mapped[date | None] = mapped_column(Date)
    catalogue_source: Mapped[str] = mapped_column(String(300))


class ModelAlias(Base):
    __tablename__ = "model_aliases"
    __table_args__ = (UniqueConstraint("manufacturer_norm", "alias_norm", name="uq_alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("device_models.id", ondelete="CASCADE"), index=True)
    manufacturer_norm: Mapped[str] = mapped_column(String(80))
    alias: Mapped[str] = mapped_column(String(80))
    alias_norm: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20))  # name | oem_code


class ModelVariant(Base):
    __tablename__ = "model_variants"

    model_id: Mapped[str] = mapped_column(ForeignKey("device_models.id", ondelete="CASCADE"), primary_key=True)
    storage_gb: Mapped[int] = mapped_column(Integer, primary_key=True)


# --- market data -----------------------------------------------------------------------------


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    # completed_sale | listing | dealer_offer | trade_in | refurbished_retail | customer_quote | synthetic
    source_type: Mapped[str] = mapped_column(String(30))
    collection_method: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(300))
    markets: Mapped[str] = mapped_column(String(40))
    terms_note: Mapped[str] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean)
    is_mock: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20))  # running | succeeded | failed
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    triggered_by: Mapped[str] = mapped_column(String(80))
    message: Mapped[str | None] = mapped_column(Text)


class RejectedRecord(Base):
    __tablename__ = "rejected_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), index=True)
    line: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(300))
    raw: Mapped[str] = mapped_column(String(1000))


class Observation(Base):
    """One genuine (or, for synthetic sources, mock) price data point with its provenance."""

    __tablename__ = "observations"
    __table_args__ = (
        Index("ix_obs_lookup", "model_id", "region", "grade", "storage_gb", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("ingestion_jobs.id"))
    model_id: Mapped[str] = mapped_column(ForeignKey("device_models.id"))
    storage_gb: Mapped[int] = mapped_column(Integer)
    region: Mapped[str] = mapped_column(String(2))
    currency: Mapped[str] = mapped_column(String(3))
    grade: Mapped[str] = mapped_column(String(10))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    observed_at: Mapped[date] = mapped_column(Date)
    collected_at: Mapped[datetime] = mapped_column(DateTime)
    external_ref: Mapped[str | None] = mapped_column(String(200))
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True)
    is_mock: Mapped[bool] = mapped_column(Boolean)


# --- API clients and request state -----------------------------------------------------------


class ApiClient(Base):
    __tablename__ = "api_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20))  # partner | admin
    key_prefix: Mapped[str] = mapped_column(String(12))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 of the key; the key is never stored
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Self-service keys belong to an account; operator-issued (CLI) keys have none.
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    scopes: Mapped[str] = mapped_column(String(200), default="")  # comma-separated, see security.SCOPES
    rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer)  # None = server default
    daily_quota: Mapped[int | None] = mapped_column(Integer)            # None = server default
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)


class ApiUsageEvent(Base):
    """One authenticated API request. No key, IP or body is stored."""

    __tablename__ = "api_usage_events"
    __table_args__ = (Index("ix_usage_client_at", "client", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client: Mapped[str] = mapped_column(String(64))  # non-secret label, e.g. db-12-myapp
    api_client_id: Mapped[int | None] = mapped_column(ForeignKey("api_clients.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    http_method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(100))
    status: Mapped[int] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(40))
    latency_ms: Mapped[int] = mapped_column(Integer)


class ApiValuation(Base):
    """A valuation created through /api/v1/valuations; readable only by the same owner."""

    __tablename__ = "api_valuations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # random, not derived from the request
    owner: Mapped[str] = mapped_column(String(64), index=True)
    request_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# --- accounts (developer portal and watchlists) --------------------------------------------


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # stored lower-cased
    password_hash: Mapped[str] = mapped_column(String(200))         # scrypt, see accounts.py
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime)


class AccountSession(Base):
    __tablename__ = "account_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("account_id", "model_id", "storage_gb", "condition", name="uq_watch"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("device_models.id", ondelete="CASCADE"))
    storage_gb: Mapped[int] = mapped_column(Integer)
    region: Mapped[str] = mapped_column(String(2))
    condition: Mapped[str] = mapped_column(String(20))  # new | refurbished
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PriceAlert(Base):
    """Created only when a stored offer actually met the watch's condition."""

    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watchlist_items.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("marketplace_offers.id", ondelete="CASCADE"))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    reason: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)


# --- marketplace offers (new / refurbished retail, buyback quotes) ----------------------------


class MarketplaceOffer(Base):
    """One offer as retrieved from one provider at one time. Re-retrieving the same price later adds a row, which
    is what price history is built from. `raw_json` keeps the provider's record (where its terms allow)."""

    __tablename__ = "marketplace_offers"
    __table_args__ = (
        Index("ix_offer_lookup", "model_id", "storage_gb", "region", "retrieved_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("ingestion_jobs.id"))
    provider_product_id: Mapped[str | None] = mapped_column(String(100))  # FSN, ASIN, ...
    title: Mapped[str] = mapped_column(String(300))
    brand: Mapped[str | None] = mapped_column(String(80))
    model_id: Mapped[str | None] = mapped_column(ForeignKey("device_models.id"))
    storage_gb: Mapped[int | None] = mapped_column(Integer)
    ram_gb: Mapped[int | None] = mapped_column(Integer)
    color: Mapped[str | None] = mapped_column(String(60))
    condition: Mapped[str] = mapped_column(String(20))   # new | refurbished | used
    # new_retail | refurbished_retail | used_listing | buyback_quote
    price_type: Mapped[str] = mapped_column(String(30))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    mrp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    region: Mapped[str] = mapped_column(String(2))
    url: Mapped[str | None] = mapped_column(String(600))
    seller: Mapped[str | None] = mapped_column(String(120))
    seller_type: Mapped[str | None] = mapped_column(String(30))
    availability: Mapped[str | None] = mapped_column(String(20))  # in_stock | out_of_stock (only when supplied)
    delivery_note: Mapped[str | None] = mapped_column(String(200))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    raw_json: Mapped[str | None] = mapped_column(Text)
    match_score: Mapped[int] = mapped_column(Integer)
    match_category: Mapped[str] = mapped_column(String(20))  # exact | strong | variant_mismatch | similar | unmatched
    match_reasons: Mapped[str] = mapped_column(Text)        # JSON list
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True)
    is_mock: Mapped[bool] = mapped_column(Boolean)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    client: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SavedValuation(Base):
    __tablename__ = "saved_valuations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    delete_token_hash: Mapped[str] = mapped_column(String(64))
    request_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class RateLimitCounter(Base):
    __tablename__ = "rate_limit_counters"

    bucket: Mapped[str] = mapped_column(String(80), primary_key=True)
    window_start: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer)


class RequestLog(Base):
    """Aggregate-friendly request log. No keys, IPs, bodies or other personal data."""

    __tablename__ = "request_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    channel: Mapped[str] = mapped_column(String(10))  # partner | public | admin | other
    http_method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(100))
    status: Mapped[int] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(40))
    method_version: Mapped[str | None] = mapped_column(String(40))
    latency_ms: Mapped[int] = mapped_column(Integer)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text)
