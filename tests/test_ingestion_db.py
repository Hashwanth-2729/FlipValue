"""Catalogue, ingestion pipeline, migrations and CLI."""

from __future__ import annotations

from datetime import timedelta

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select

from conftest import TODAY
from flipvalue import catalogue, cli
from flipvalue.db.models import Base, Observation, RejectedRecord
from flipvalue.db.session import make_engine
from flipvalue.ingestion.adapters import CsvImportAdapter
from flipvalue.ingestion.runner import run_ingestion
from flipvalue.ingestion.sources import SourceError, SourceSpec, register_source

HEADER = "manufacturer,model,storage_gb,region,currency,grade,price,observed_at,external_ref\n"


@pytest.fixture
def session(catalogue_db, session_for):
    s = session_for(catalogue_db)
    register_source(s, SourceSpec(id="manual-in", name="Manual IN", source_type="completed_sale",
                                  collection_method="manual", markets="IN", terms_note="permission on file",
                                  verified=True))
    return s


def ingest(session, rows: str):
    return run_ingestion(session, "manual-in", CsvImportAdapter(HEADER + rows), "test", production=False,
                         today=TODAY)


def test_valid_rows_are_stored_with_provenance(session):
    job = ingest(session, "samsung,SM-G991B,128,IN,INR,good,21000,2026-09-01,sale-1\n"
                          "Google,Pixel 6a,,IN,INR,fair,10500.50,2026-09-02,\n")

    assert (job.status, job.accepted, job.rejected) == ("succeeded", 2, 0)
    rows = session.scalars(select(Observation).order_by(Observation.id)).all()
    assert rows[0].model_id == "samsung-galaxy-s21" and rows[0].source_id == "manual-in"
    assert rows[0].job_id == job.id and rows[0].external_ref == "sale-1" and not rows[0].is_mock
    assert rows[1].storage_gb == 128  # single-variant model


@pytest.mark.parametrize("row, reason", [
    ("Acme,X1,128,IN,INR,good,1,2026-09-01,\n", "not in catalogue"),
    ("samsung,SM-G991B,128,US,USD,good,1,2026-09-01,\n", "not registered for market US"),
    ("samsung,SM-G991B,128,IN,USD,good,1,2026-09-01,\n", "not a supported pair"),
    ("samsung,SM-G991B,128,IN,INR,mint,1,2026-09-01,\n", "grade must be"),
    ("samsung,SM-G991B,,IN,INR,good,1,2026-09-01,\n", "storage_gb is required"),
    ("samsung,SM-G991B,64,IN,INR,good,1,2026-09-01,\n", "storage_gb must be one of"),
    ("samsung,SM-G991B,128,IN,INR,good,-5,2026-09-01,\n", "price must be"),
    ("samsung,SM-G991B,128,IN,INR,good,abc,2026-09-01,\n", "not a number"),
    ("samsung,SM-G991B,128,IN,INR,good,1.234,2026-09-01,\n", "2 decimal"),
    ("samsung,SM-G991B,128,IN,INR,good,1,01/09/2026,\n", "YYYY-MM-DD"),
    ("samsung,SM-G991B,128,IN,INR,good,1,2026-12-01,\n", "future"),
    ("samsung,SM-G991B,128,IN,INR,good,1,2019-01-01,\n", "5 years"),
])
def test_invalid_rows_are_rejected_and_recorded(session, row, reason):
    job = ingest(session, row)

    assert (job.accepted, job.rejected) == (0, 1)
    rejected = session.scalars(select(RejectedRecord)).one()
    assert reason in rejected.reason and rejected.line == 2


def test_duplicates_are_counted_not_stored(session):
    row = "samsung,SM-G991B,128,IN,INR,good,21000,2026-09-01,sale-1\n"
    first = ingest(session, row + row)
    second = ingest(session, row)

    assert (first.accepted, first.duplicates, second.accepted, second.duplicates) == (1, 1, 0, 1)


def test_bad_header_fails_the_job(session):
    job = run_ingestion(session, "manual-in", CsvImportAdapter("a,b\n1,2\n"), "test", production=False, today=TODAY)

    assert job.status == "failed" and "header" in job.message


def test_synthetic_sources_are_refused_in_production(session):
    from flipvalue.ingestion.sources import SYNTHETIC_DEV

    register_source(session, SYNTHETIC_DEV)
    with pytest.raises(ValueError, match="production"):
        run_ingestion(session, "synthetic-dev", CsvImportAdapter(HEADER), "t", production=True)


@pytest.mark.parametrize("change, message", [
    ({"source_type": "rumour"}, "source_type"),
    ({"markets": "GB"}, "markets"),
    ({"terms_note": " "}, "terms_note"),
    ({"id": "bad id!"}, "source id"),
])
def test_source_registration_is_validated(session, change, message):
    spec = dict(id="x", name="x", source_type="listing", collection_method="m", markets="IN", terms_note="t",
                verified=False)
    with pytest.raises(SourceError, match=message):
        register_source(session, SourceSpec(**{**spec, **change}))


def test_catalogue_search_and_aliases(session):
    assert [m.id for m in catalogue.search(session, "sm-g991")] == ["samsung-galaxy-s21"]
    assert {m.id for m in catalogue.search(session, "pixel")} == {"google-pixel-6a", "google-pixel-7",
                                                                  "google-pixel-7a", "google-pixel-8",
                                                                  "google-pixel-8a", "google-pixel-9"}
    assert catalogue.search(session, "%") == []
    assert catalogue.find_model(session, "SAMSUNG", "sm-g991u").id == "samsung-galaxy-s21"
    assert catalogue.find_model(session, "Google", "SM-G991B") is None


def test_catalogue_rejects_conflicting_alias(tmp_path, session):
    path = tmp_path / "c.csv"
    path.write_text(",".join(catalogue.COLUMNS) + "\n"
                    "a,Acme,One,,128,AC-1,src\n"
                    "b,Acme,Two,,128,AC-1,src\n", encoding="utf-8")
    with pytest.raises(catalogue.CatalogueError, match="used by both"):
        catalogue.load_catalogue(session, path)


def test_migrations_match_models(catalogue_db):
    engine = make_engine(catalogue_db)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []


def test_cli_keys_and_seed_refused_in_production(monkeypatch, catalogue_db, capsys):
    monkeypatch.setenv("FLIPVALUE_DATABASE_URL", catalogue_db)
    assert cli.main(["keys", "create", "--name", "fixmytech", "--role", "partner"]) == 0
    key = capsys.readouterr().out.splitlines()[1]
    assert key.startswith("fv_") and len(key) > 40
    cli.main(["keys", "list"])
    listing = capsys.readouterr().out
    assert "fixmytech" in listing and key not in listing  # only the prefix is shown
    assert cli.main(["keys", "revoke", "1"]) == 0

    monkeypatch.setenv("FLIPVALUE_ENV", "production")
    monkeypatch.setenv("FLIPVALUE_HASH_SALT", "s" * 32)
    monkeypatch.setenv("FLIPVALUE_ALLOW_SQLITE_IN_PRODUCTION", "true")
    assert cli.main(["seed-mock"]) == 2


def test_cli_import_and_purge(monkeypatch, catalogue_db, tmp_path, capsys):
    monkeypatch.setenv("FLIPVALUE_DATABASE_URL", catalogue_db)
    assert cli.main(["register-source", "--id", "shop-quotes", "--name", "Shop quotes", "--source-type",
                     "dealer_offer", "--collection-method", "manual", "--markets", "IN",
                     "--terms-note", "quotes given to us with consent"]) == 0
    observed = (TODAY - timedelta(days=1)).isoformat()
    csv_path = tmp_path / "obs.csv"
    csv_path.write_text(HEADER + f"samsung,SM-G991B,128,IN,INR,good,20000,{observed},q1\n", encoding="utf-8")
    assert cli.main(["import", "--source", "shop-quotes", str(csv_path)]) == 0
    assert "1 accepted" in capsys.readouterr().out
    assert cli.main(["purge"]) == 0
