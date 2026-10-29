"""FlipValue modelled estimates: generation, use as a labelled last resort, trends and store price estimates."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from conftest import NOW, TODAY, add_observations
from flipvalue import catalogue
from flipvalue.db.models import DeviceModel, MarketplaceOffer, Observation
from flipvalue.estimates import ESTIMATE_TYPES, read_bands
from flipvalue.estimates import load_estimates as load
from test_condition_decision import GOOD

VALUE = "/api/valuations"
GOOD_GRADE = {**GOOD, "screen": "light_scratches"}  # GOOD itself (like new) grades "excellent"


@pytest.fixture
def estimated_db(catalogue_db, session_for) -> str:
    session = session_for(catalogue_db)
    load(session, TODAY)
    session.commit()
    return catalogue_db


def _value(client, model_id: str, storage: int) -> dict:
    r = client.post(VALUE, json={"device": {"model_id": model_id, "storage_gb": storage}, "region": "IN",
                                 "currency": "INR", "assessment": GOOD_GRADE})
    assert r.status_code == 200, r.text
    return r.json()


def test_every_catalogue_model_has_a_price_band(catalogue_db, session_for):
    session = session_for(catalogue_db)
    bands = {b.model_id for b in read_bands()}
    assert bands == set(session.scalars(select(DeviceModel.id)))
    for band in read_bands():
        assert band.used[1] <= band.refurb[1], f"{band.model_id}: used above refurbished"
        assert not band.new or band.new[0] <= band.launch, f"{band.model_id}: new above launch price"


def test_load_is_idempotent_and_labelled(catalogue_db, session_for):
    session = session_for(catalogue_db)
    first = load(session, TODAY)
    second = load(session, TODAY)
    assert first == second and first["models"] == 31 and first["store_offers"] > 0
    total = session.scalar(select(func.count(Observation.id)))
    assert total == first["resale_observations"] + first["buyback_observations"]
    assert not session.scalar(select(func.count(Observation.id)).where(Observation.is_mock.is_(True)))
    # Only matched (strong) offers are stored; none is mock.
    categories = set(session.scalars(select(MarketplaceOffer.match_category)))
    assert categories == {"strong"}


def test_valuation_uses_latest_month_estimate_and_says_so(make_client, estimated_db):
    v = _value(make_client(database_url=estimated_db), "apple-iphone-15", 128)
    est = v["as_is"]
    # Used band 36000-42000: good = midpoint, three points at -6% / 0 / +6%.
    assert (est["basis"], est["quality"], est["value"]) == ("estimate", "modelled", 39000.0)
    assert (est["low"], est["high"], est["observation_count"]) == (36660.0, 41340.0, 3)
    assert est["newest_observation"] == est["oldest_observation"] == "2026-10-01"
    assert v["status"] == "partial" and v["mock"] is False
    assert any(w.startswith("FlipValue estimate") for w in v["warnings"])
    assert "modelled instead of observed" in v["explanation"][0]
    buyback = v["value_types"]["buyback"]
    assert (buyback["basis"], buyback["value"], buyback["confidence"]) == ("estimate_buyback", 27300.0, "low")


def test_storage_and_grade_scale_the_estimate(make_client, estimated_db):
    client = make_client(database_url=estimated_db)
    base = _value(client, "apple-iphone-15", 128)["as_is"]["value"]
    bigger = _value(client, "apple-iphone-15", 256)["as_is"]["value"]
    assert bigger == pytest.approx(base * 1.08, abs=10)
    fair = client.post(VALUE, json={"device": {"model_id": "apple-iphone-15", "storage_gb": 128}, "region": "IN",
                                    "currency": "INR", "assessment": {**GOOD, "body": "visible_wear"}}).json()
    assert fair["as_is"]["value"] < base


def test_real_observations_win_over_estimates(make_client, estimated_db, session_for):
    session = session_for(estimated_db)
    add_observations(session, "shop", "listing", "apple-iphone-15", 128, "IN", "good", [30000, 31000, 32000])
    session.commit()
    est = _value(make_client(database_url=estimated_db), "apple-iphone-15", 128)["as_is"]
    assert (est["basis"], est["value"]) == ("listing", 31000.0)


def test_trend_covers_the_years_since_release(make_client, estimated_db):
    t = make_client(database_url=estimated_db).get("/api/trends", params={
        "model_id": "samsung-galaxy-s21", "storage_gb": 128, "region": "IN", "grade": "good"}).json()
    points = t["series"]["estimate"]
    assert t["available"] and points[0]["month"] == "2021-02" and points[-1]["month"] == "2026-10"
    assert points[0]["median"] == pytest.approx(69999 * 0.8, rel=0.02)   # 80% of the launch price
    assert points[-1]["median"] == 15000.0                                  # today's good-grade estimate
    medians = [p["median"] for p in points]
    assert medians[0] > medians[len(medians) // 2] > medians[-1]


def test_store_estimates_in_comparison_never_in_history_and_never_expire(make_client, estimated_db):
    later = NOW + timedelta(days=60)
    client = make_client(database_url=estimated_db, now=lambda: later)
    data = client.get("/api/market/offers", params={"model_id": "google-pixel-8", "storage_gb": 128}).json()
    assert data["estimates_included"] is True
    new = data["groups"]["new"]
    assert {o["seller"] for o in new} == {"Amazon", "Flipkart", "Croma", "Reliance Digital", "Google Store"}
    assert all(o["source"]["estimated"] and o["freshness"] == "estimate" and o["url"] is None for o in new)
    assert all(37000 <= o["price"] <= 39000 and o["mrp"] == 75999 for o in new)
    assert {o["seller"] for o in data["groups"]["buyback"]} == {"Cashify", "Budli"}
    history = client.get("/api/market/history", params={"model_id": "google-pixel-8", "storage_gb": 128}).json()
    assert history["observation_count"] == 0


def test_meta_and_catalogue_report_estimates(make_client, estimated_db):
    client = make_client(database_url=estimated_db)
    meta = client.get("/api/meta").json()
    assert (meta["data_status"], meta["real_observations"]) == ("estimated", 0)
    assert meta["estimated_observations"] > 0
    assert {m["evidence"]["IN"] for m in client.get("/api/catalogue").json()} == {"estimated"}


def test_estimate_types_are_registered_source_types():
    from flipvalue.ingestion.sources import SOURCE_TYPES

    assert set(ESTIMATE_TYPES) <= set(SOURCE_TYPES)


def test_unknown_model_in_bands_is_an_error(catalogue_db, session_for, tmp_path):
    from flipvalue.estimates import COLUMNS, EstimateError

    path = tmp_path / "bands.csv"
    path.write_text(",".join(COLUMNS) + "\nno-such-phone,10000,,,5000,6000,4000,5000,test\n", encoding="utf-8")
    with pytest.raises(EstimateError, match="not in the catalogue"):
        load(session_for(catalogue_db), TODAY, path)


def test_estimated_store_titles_match_every_variant(catalogue_db, session_for):
    session = session_for(catalogue_db)
    counts = load(session, TODAY)
    variants = sum(len(catalogue.variants(session, m)) for m in session.scalars(select(DeviceModel.id)))
    # Every variant gets refurbished (4), used (3) and buyback (2) offers at least.
    assert counts["store_offers"] >= variants * 9
