"""Behaviour on PostgreSQL (what Cloud SQL runs). Skipped unless FLIPVALUE_TEST_POSTGRES_URL is set, e.g.

    FLIPVALUE_TEST_POSTGRES_URL=postgresql+psycopg://postgres:@127.0.0.1:5432/postgres pytest tests/test_postgres.py

Each run creates and drops its own database.
"""

from __future__ import annotations

import os
import threading
import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text

from conftest import FIXED_TIME, TODAY
from flipvalue import cli
from flipvalue.app import create_app
from flipvalue.catalogue import load_catalogue
from flipvalue.config import Settings
from flipvalue.db.models import Base
from flipvalue.db.session import make_engine, make_sessionmaker, transaction, upgrade
from flipvalue.security import RateLimiter

PG_URL = os.environ.get("FLIPVALUE_TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set FLIPVALUE_TEST_POSTGRES_URL to run against PostgreSQL")
URL = "/v1/valuations"


@pytest.fixture(scope="module")
def pg_url():
    admin = create_engine(PG_URL, isolation_level="AUTOCOMMIT")
    name = f"flipvalue_test_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(PG_URL).set(database=name).render_as_string(hide_password=False)
    upgrade(url)
    engine = make_engine(url)
    sessions = make_sessionmaker(engine)
    with transaction(sessions) as session:
        load_catalogue(session, cli.CATALOGUE)
    cli.seed_mock(sessions, Settings(), TODAY, replace=True)
    engine.dispose()
    yield url
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def pg_client(pg_url, api_key, admin_key):
    def _make(**overrides) -> TestClient:
        options = {"api_keys": (api_key,), "admin_keys": (admin_key,), "database_url": pg_url,
                   "rate_limit_per_minute": 1000, "public_rate_limit_per_minute": 1000, "frontend_dist": None}
        options.update(overrides)
        return TestClient(create_app(Settings(**options), clock=lambda: TODAY, wall_clock=lambda: FIXED_TIME))

    return _make


def test_migrations_match_models_on_postgres(pg_url):
    engine = make_engine(pg_url)
    with engine.connect() as conn:
        assert conn.dialect.name == "postgresql"
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    engine.dispose()


def test_same_valuation_as_sqlite(pg_client, make_client, headers, body):
    """The engine gives identical results on both databases (same synthetic data, same reference date)."""
    pg = pg_client().post(URL, json=body, headers=headers)
    lite = make_client().post(URL, json=body, headers=headers)

    assert pg.status_code == 200, pg.text
    assert pg.json() == lite.json()


def test_partner_errors_and_idempotency_on_postgres(pg_client, headers, body):
    client = pg_client()
    retry = {**headers, "Idempotency-Key": f"pg-{uuid.uuid4().hex}"}
    first, second = client.post(URL, json=body, headers=retry), client.post(URL, json=body, headers=retry)
    assert first.json() == second.json() and second.headers["Idempotent-Replayed"] == "true"
    body["condition"]["grade"] = "poor"
    assert client.post(URL, json=body, headers=retry).json()["error"]["code"] == "idempotency_key_reused"
    body["device"]["model"] = "SM-X999Z"
    assert client.post(URL, json=body, headers=headers).status_code == 404
    assert client.post(URL, json=body, headers={"X-API-Key": "wrong"}).status_code == 401


def test_saved_valuation_lifecycle_on_postgres(pg_client):
    from test_condition_decision import GOOD

    client = pg_client()
    saved = client.post("/api/saved", json={"device": {"model_id": "google-pixel-6a"}, "region": "IN",
                                            "currency": "INR", "assessment": GOOD}).json()
    assert client.get(f"/api/saved/{saved['id']}").status_code == 200
    deleted = client.delete(f"/api/saved/{saved['id']}", headers={"X-Delete-Token": saved["delete_token"]})
    assert deleted.status_code == 204


def test_rate_limiter_is_exact_under_concurrency(pg_url):
    """Several Cloud Run instances share one counter: 20 concurrent hits against a limit of 10 allow exactly 10."""
    engine = make_engine(pg_url, pool_size=10, max_overflow=10)
    limiter = RateLimiter(make_sessionmaker(engine), clock=lambda: FIXED_TIME)
    bucket = f"concurrency-{uuid.uuid4().hex}"
    results: list[int | None] = []
    lock = threading.Lock()

    def hit() -> None:
        outcome = limiter.hit(bucket, 10)
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=hit) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    engine.dispose()

    assert len(results) == 20
    assert results.count(None) == 10


def test_concurrent_requests_on_postgres(pg_client, headers, body):
    client = pg_client()
    statuses: list[int] = []

    def call() -> None:
        statuses.append(client.post(URL, json=body, headers=headers).status_code)

    threads = [threading.Thread(target=call) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert statuses == [200] * 12


def test_production_mode_on_postgres(pg_client, headers, body):
    client = pg_client(environment="production", hash_salt="s" * 32)

    assert client.get("/ready").json()["status"] == "ready"
    assert client.post(URL, json=body, headers=headers).json()["error"]["code"] == "no_data_for_condition"


def test_cli_on_postgres(pg_url, monkeypatch, capsys):
    monkeypatch.setenv("FLIPVALUE_DATABASE_URL", pg_url)
    assert cli.main(["release"]) == 0  # the deploy step is idempotent: already at head, catalogue re-applied
    assert cli.main(["keys", "create", "--name", "pg", "--role", "partner"]) == 0
    assert cli.main(["purge"]) == 0
    assert "database migrated" in capsys.readouterr().out
