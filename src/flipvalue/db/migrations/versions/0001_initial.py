"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_models",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("manufacturer", sa.String(80), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("catalogue_source", sa.String(300), nullable=False),
    )
    op.create_table(
        "model_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.String(80), sa.ForeignKey("device_models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("manufacturer_norm", sa.String(80), nullable=False),
        sa.Column("alias", sa.String(80), nullable=False),
        sa.Column("alias_norm", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.UniqueConstraint("manufacturer_norm", "alias_norm", name="uq_alias"),
    )
    op.create_index("ix_model_aliases_model_id", "model_aliases", ["model_id"])
    op.create_table(
        "model_variants",
        sa.Column("model_id", sa.String(80), sa.ForeignKey("device_models.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("storage_gb", sa.Integer(), primary_key=True),
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("collection_method", sa.String(200), nullable=False),
        sa.Column("url", sa.String(300), nullable=True),
        sa.Column("markets", sa.String(40), nullable=False),
        sa.Column("terms_note", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(60), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("accepted", sa.Integer(), nullable=False),
        sa.Column("rejected", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("triggered_by", sa.String(80), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
    )
    op.create_index("ix_ingestion_jobs_source_id", "ingestion_jobs", ["source_id"])
    op.create_table(
        "rejected_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("raw", sa.String(1000), nullable=False),
    )
    op.create_index("ix_rejected_records_job_id", "rejected_records", ["job_id"])
    op.create_table(
        "observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(60), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("ingestion_jobs.id"), nullable=False),
        sa.Column("model_id", sa.String(80), sa.ForeignKey("device_models.id"), nullable=False),
        sa.Column("storage_gb", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("grade", sa.String(10), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("observed_at", sa.Date(), nullable=False),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        sa.Column("external_ref", sa.String(200), nullable=True),
        sa.Column("dedup_key", sa.String(64), nullable=False, unique=True),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_observations_source_id", "observations", ["source_id"])
    op.create_index("ix_obs_lookup", "observations", ["model_id", "region", "grade", "storage_gb", "observed_at"])
    op.create_table(
        "api_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("client", sa.String(64), primary_key=True),
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_idempotency_records_created_at", "idempotency_records", ["created_at"])
    op.create_table(
        "saved_valuations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("delete_token_hash", sa.String(64), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_saved_valuations_created_at", "saved_valuations", ["created_at"])
    op.create_table(
        "rate_limit_counters",
        sa.Column("bucket", sa.String(80), primary_key=True),
        sa.Column("window_start", sa.Integer(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "request_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("http_method", sa.String(8), nullable=False),
        sa.Column("path", sa.String(100), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("method_version", sa.String(40), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
    )
    op.create_index("ix_request_log_at", "request_log", ["at"])
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("actor", sa.String(80), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
    )
    op.create_index("ix_audit_log_at", "audit_log", ["at"])


def downgrade() -> None:
    for table in ("audit_log", "request_log", "rate_limit_counters", "saved_valuations", "idempotency_records",
                  "api_clients", "observations", "rejected_records", "ingestion_jobs", "sources",
                  "model_variants", "model_aliases", "device_models"):
        op.drop_table(table)
