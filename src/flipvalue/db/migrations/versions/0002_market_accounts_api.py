"""marketplace offers, accounts, scoped API keys, usage events, API valuations, watchlists

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ALL_SCOPES = "valuation:read,market_prices:read,price_history:read"


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "account_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_account_sessions_account_id", "account_sessions", ["account_id"])
    op.create_index("ix_account_sessions_expires_at", "account_sessions", ["expires_at"])

    with op.batch_alter_table("api_clients") as batch:
        batch.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("scopes", sa.String(200), nullable=False, server_default=""))
        batch.add_column(sa.Column("rate_limit_per_minute", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("daily_quota", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("last_used_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key("fk_api_clients_account_id", "accounts", ["account_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_api_clients_account_id", ["account_id"])
    # Keys issued before scopes existed keep the access they had.
    op.execute(f"UPDATE api_clients SET scopes = '{ALL_SCOPES}' WHERE role = 'partner'")

    op.create_table(
        "api_usage_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client", sa.String(64), nullable=False),
        sa.Column("api_client_id", sa.Integer(), sa.ForeignKey("api_clients.id", ondelete="CASCADE"), nullable=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("http_method", sa.String(8), nullable=False),
        sa.Column("path", sa.String(100), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
    )
    op.create_index("ix_usage_client_at", "api_usage_events", ["client", "at"])
    op.create_index("ix_api_usage_events_api_client_id", "api_usage_events", ["api_client_id"])
    op.create_index("ix_api_usage_events_at", "api_usage_events", ["at"])

    op.create_table(
        "api_valuations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("owner", sa.String(64), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_api_valuations_owner", "api_valuations", ["owner"])
    op.create_index("ix_api_valuations_created_at", "api_valuations", ["created_at"])

    op.create_table(
        "marketplace_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(60), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("ingestion_jobs.id"), nullable=False),
        sa.Column("provider_product_id", sa.String(100), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("brand", sa.String(80), nullable=True),
        sa.Column("model_id", sa.String(80), sa.ForeignKey("device_models.id"), nullable=True),
        sa.Column("storage_gb", sa.Integer(), nullable=True),
        sa.Column("ram_gb", sa.Integer(), nullable=True),
        sa.Column("color", sa.String(60), nullable=True),
        sa.Column("condition", sa.String(20), nullable=False),
        sa.Column("price_type", sa.String(30), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("mrp", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("region", sa.String(2), nullable=False),
        sa.Column("url", sa.String(600), nullable=True),
        sa.Column("seller", sa.String(120), nullable=True),
        sa.Column("seller_type", sa.String(30), nullable=True),
        sa.Column("availability", sa.String(20), nullable=True),
        sa.Column("delivery_note", sa.String(200), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("match_score", sa.Integer(), nullable=False),
        sa.Column("match_category", sa.String(20), nullable=False),
        sa.Column("match_reasons", sa.Text(), nullable=False),
        sa.Column("dedup_key", sa.String(64), nullable=False, unique=True),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_marketplace_offers_source_id", "marketplace_offers", ["source_id"])
    op.create_index("ix_offer_lookup", "marketplace_offers", ["model_id", "storage_gb", "region", "retrieved_at"])

    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_id", sa.String(80), sa.ForeignKey("device_models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_gb", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(2), nullable=False),
        sa.Column("condition", sa.String(20), nullable=False),
        sa.Column("target_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("account_id", "model_id", "storage_gb", "condition", name="uq_watch"),
    )
    op.create_index("ix_watchlist_items_account_id", "watchlist_items", ["account_id"])
    op.create_table(
        "price_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("watch_id", sa.Integer(), sa.ForeignKey("watchlist_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("marketplace_offers.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_price_alerts_watch_id", "price_alerts", ["watch_id"])


def downgrade() -> None:
    for table in ("price_alerts", "watchlist_items", "marketplace_offers", "api_valuations", "api_usage_events"):
        op.drop_table(table)
    with op.batch_alter_table("api_clients") as batch:
        batch.drop_index("ix_api_clients_account_id")
        batch.drop_constraint("fk_api_clients_account_id", type_="foreignkey")
        for column in ("last_used_at", "daily_quota", "rate_limit_per_minute", "scopes", "account_id"):
            batch.drop_column(column)
    op.drop_table("account_sessions")
    op.drop_table("accounts")
