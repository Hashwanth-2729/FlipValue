from __future__ import annotations

import secrets
import shutil
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from flipvalue.app import create_app
from flipvalue.catalogue import load_catalogue
from flipvalue.cli import CATALOGUE, seed_mock
from flipvalue.config import Settings
from flipvalue.db.models import IngestionJob, Observation
from flipvalue.db.session import make_engine, make_sessionmaker, transaction, upgrade
from flipvalue.ingestion.sources import SourceSpec, register_source

TODAY = date(2026, 10, 1)
NOW = datetime(2026, 10, 1, 18, 0)  # fixture offers are seeded at TODAY 12:00, so they are 6 hours old
# Rate-limit windows are fixed minutes; a fixed wall clock 10 s into a minute keeps tests off window boundaries.
FIXED_TIME = 1_790_000_000.0 - (1_790_000_000 % 60) + 10


def _url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _build(path: Path, seed: bool) -> None:
    upgrade(_url(path))
    engine = make_engine(_url(path))
    sessions = make_sessionmaker(engine)
    with transaction(sessions) as session:
        load_catalogue(session, CATALOGUE)
    if seed:
        seed_mock(sessions, Settings(), TODAY, replace=True)
    engine.dispose()


@pytest.fixture(scope="session")
def templates(tmp_path_factory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("templates")
    paths = {"seeded": root / "seeded.db", "catalogue": root / "catalogue.db"}
    _build(paths["seeded"], seed=True)
    _build(paths["catalogue"], seed=False)
    return paths


def _copy(template: Path, target: Path) -> str:
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(template) + suffix)
        if src.exists():
            shutil.copy(src, str(target) + suffix)
    return _url(target)


@pytest.fixture
def seeded_db(templates, tmp_path) -> str:
    return _copy(templates["seeded"], tmp_path / "test.db")


@pytest.fixture
def catalogue_db(templates, tmp_path) -> str:
    return _copy(templates["catalogue"], tmp_path / "test.db")


@pytest.fixture
def api_key() -> str:
    # Generated per test run; no key is ever stored in the repository.
    return secrets.token_urlsafe(32)


@pytest.fixture
def admin_key() -> str:
    return secrets.token_urlsafe(32)


@pytest.fixture
def make_client(api_key, admin_key, seeded_db) -> Callable[..., TestClient]:
    def _make(database_url: str | None = None, clock: Callable[[], date] = lambda: TODAY,
              wall_clock: Callable[[], float] = lambda: FIXED_TIME, providers=None,
              now: Callable[[], datetime] = lambda: NOW, **overrides) -> TestClient:
        options = {"api_keys": (api_key,), "admin_keys": (admin_key,), "database_url": database_url or seeded_db,
                   "rate_limit_per_minute": 1000, "public_rate_limit_per_minute": 1000, "frontend_dist": None}
        options.update(overrides)
        return TestClient(create_app(Settings(**options), clock=clock, wall_clock=wall_clock, providers=providers,
                                     now=now))

    return _make


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key, "FlipValue-API-Version": "1"}


@pytest.fixture
def admin_headers(admin_key: str) -> dict[str, str]:
    return {"X-API-Key": admin_key}


@pytest.fixture
def body() -> dict:
    """The contract's example request, in the Indian market FixMyTech defaults to."""
    return {
        "device": {"manufacturer": "samsung", "model": "SM-G991B", "storage_gb": 128, "age_months": 34},
        "region": "IN",
        "currency": "INR",
        "condition": {"grade": "faulty", "faults": ["battery_wear"]},
        "repair_scenario": {"repair_type": "battery_replacement"},
    }


@pytest.fixture
def session_for() -> Iterator[Callable[[str], Session]]:
    engines = []

    def _open(url: str) -> Session:
        engine = make_engine(url)
        engines.append(engine)
        return make_sessionmaker(engine)()

    yield _open
    for engine in engines:
        engine.dispose()


def add_observations(session: Session, source_id: str, source_type: str, model_id: str, storage_gb: int,
                     region: str, grade: str, prices: list[int | str], *, days_ago: int | list[int] = 10,
                     today: date = TODAY) -> list[int]:
    """Insert hand-made observations for exact-arithmetic tests."""
    register_source(session, SourceSpec(id=source_id, name=source_id, source_type=source_type,
                                        collection_method="test fixture", markets="IN,US",
                                        terms_note="test fixture", verified=False))
    job = IngestionJob(source_id=source_id, status="succeeded", triggered_by="test", accepted=0, rejected=0,
                       duplicates=0)
    session.add(job)
    session.flush()
    ages = days_ago if isinstance(days_ago, list) else [days_ago] * len(prices)
    currency = {"IN": "INR", "US": "USD"}[region]
    ids = []
    for i, (price, age) in enumerate(zip(prices, ages, strict=True)):
        obs = Observation(source_id=source_id, job_id=job.id, model_id=model_id, storage_gb=storage_gb,
                          region=region, currency=currency, grade=grade, price=Decimal(str(price)),
                          observed_at=today - timedelta(days=age), collected_at=job.started_at,
                          dedup_key=secrets.token_hex(16), is_mock=source_type == "synthetic",
                          external_ref=f"{source_id}-{i}")
        session.add(obs)
        session.flush()
        ids.append(obs.id)
    return ids
