"""Valuation engine unit tests with hand-made observations (exact arithmetic)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from conftest import TODAY, add_observations
from flipvalue.db.models import DeviceModel
from flipvalue.engine import Engine, EngineError


@pytest.fixture
def session(catalogue_db, session_for):
    return session_for(catalogue_db)


def engine(include_mock: bool = True, freshness: int = 180) -> Engine:
    return Engine(freshness, include_mock=include_mock, clock=lambda: TODAY)


S21 = "samsung-galaxy-s21"


def test_median_and_decile_range_with_ten_or_more(session):
    add_observations(session, "sales", "completed_sale", S21, 128, "IN", "good",
                     [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000])

    est, _ = engine().estimate(session, S21, 128, "IN", "good")

    assert est.value == Decimal("550.00")
    assert (est.low, est.high, est.range_method) == (Decimal("190.00"), Decimal("910.00"), "p10_p90")
    assert est.quality == "evidence_backed"
    assert est.count == 10


def test_min_max_range_and_limited_quality_below_ten(session):
    add_observations(session, "sales", "completed_sale", S21, 128, "IN", "good", [300, 100, 200])

    est, _ = engine().estimate(session, S21, 128, "IN", "good")

    assert (est.value, est.low, est.high) == (Decimal("200.00"), Decimal("100.00"), Decimal("300.00"))
    assert est.range_method == "min_max"
    assert est.quality == "limited"


def test_fewer_than_three_is_no_estimate(session):
    add_observations(session, "sales", "completed_sale", S21, 128, "IN", "good", [100, 200])

    est, found = engine().estimate(session, S21, 128, "IN", "good")

    assert est is None and found == 2


def test_stale_observations_are_excluded(session):
    add_observations(session, "sales", "completed_sale", S21, 128, "IN", "good", [100, 200, 300],
                     days_ago=[10, 10, 200])

    est, found = engine(freshness=180).estimate(session, S21, 128, "IN", "good")

    assert est is None and found == 2


def test_old_but_fresh_enough_evidence_is_limited(session):
    add_observations(session, "sales", "completed_sale", S21, 128, "IN", "good", [100] * 10, days_ago=120)

    est, _ = engine().estimate(session, S21, 128, "IN", "good")

    assert est.quality == "limited"


def test_completed_sales_win_over_listings_and_are_never_mixed(session):
    add_observations(session, "sales", "completed_sale", S21, 128, "IN", "good", [100, 110, 120])
    add_observations(session, "ads", "listing", S21, 128, "IN", "good", [900, 950, 1000, 1050])

    est, _ = engine().estimate(session, S21, 128, "IN", "good")

    assert est.basis == "completed_sale"
    assert est.value == Decimal("110.00")


def test_listings_used_only_when_sales_insufficient(session):
    add_observations(session, "sales", "completed_sale", S21, 128, "IN", "good", [100, 110])
    add_observations(session, "ads", "listing", S21, 128, "IN", "good", [900, 950, 1000] * 4)

    est, _ = engine().estimate(session, S21, 128, "IN", "good")

    assert est.basis == "listing"
    assert est.quality == "limited"  # asking prices are never evidence-backed


def test_synthetic_only_when_allowed(session):
    add_observations(session, "synthetic-dev", "synthetic", S21, 128, "IN", "good", [100, 200, 300])

    assert engine(include_mock=True).estimate(session, S21, 128, "IN", "good")[0].is_mock
    assert engine(include_mock=False).estimate(session, S21, 128, "IN", "good")[0] is None


def test_trade_in_offers_never_count_as_resale(session):
    add_observations(session, "trade", "trade_in", S21, 128, "IN", "good", [50, 60, 70])

    assert engine().estimate(session, S21, 128, "IN", "good")[0] is None
    assert engine().estimate(session, S21, 128, "IN", "good", ("trade_in",))[0].value == Decimal("60.00")


def test_other_storage_region_and_grade_are_not_comparables(session):
    add_observations(session, "a", "completed_sale", S21, 256, "IN", "good", [1, 2, 3])
    add_observations(session, "b", "completed_sale", S21, 128, "US", "good", [1, 2, 3])
    add_observations(session, "c", "completed_sale", S21, 128, "IN", "fair", [1, 2, 3])

    assert engine().estimate(session, S21, 128, "IN", "good")[0] is None


def test_valuate_after_repair_and_warnings(session):
    add_observations(session, "sales", "completed_sale", S21, 128, "IN", "faulty", [50, 60, 70])
    add_observations(session, "sales2", "completed_sale", S21, 128, "IN", "good", [200, 210, 220])
    model = session.get(DeviceModel, S21)

    outcome = engine().valuate(session, model, 128, "IN", "INR", "faulty", ("battery_wear",),
                               "battery_replacement", age_months=20)

    assert outcome.as_is.value == Decimal("60.00")
    assert outcome.after_repair.value == Decimal("210.00")
    assert outcome.target_grade == "good"
    assert outcome.status == "partial"  # 3 observations each: limited
    assert not outcome.mock
    joined = " ".join(outcome.warnings)
    assert "not priced separately" in joined and "age is not used" in joined and "grades 'good'" in joined


def test_non_faulty_grade_keeps_grade_after_repair(session):
    add_observations(session, "sales", "completed_sale", S21, 128, "IN", "poor", [50, 60, 70])
    model = session.get(DeviceModel, S21)

    outcome = engine().valuate(session, model, 128, "IN", "INR", "poor", (), "screen_replacement")

    assert outcome.target_grade == "poor"
    assert outcome.after_repair == outcome.as_is


@pytest.mark.parametrize("region, currency, code", [("GB", "GBP", "unsupported_region"),
                                                    ("IN", "USD", "unsupported_currency")])
def test_market_errors(session, region, currency, code):
    with pytest.raises(EngineError) as exc:
        engine().valuate(session, session.get(DeviceModel, S21), 128, region, currency, "good")
    assert exc.value.code == code


def test_storage_resolution(session):
    e = engine()
    assert e.match_storage(session, session.get(DeviceModel, "google-pixel-6a"), None).storage_inferred
    with pytest.raises(EngineError, match="storage_gb is required"):
        e.match_storage(session, session.get(DeviceModel, S21), None)
    with pytest.raises(EngineError, match="not catalogued with 64 GB"):
        e.match_storage(session, session.get(DeviceModel, S21), 64)


def test_valuation_id_depends_on_evidence(session):
    add_observations(session, "sales", "completed_sale", S21, 128, "IN", "good", [100, 110, 120])
    model = session.get(DeviceModel, S21)
    request = {"x": 1}
    first = engine().valuate(session, model, 128, "IN", "INR", "good").valuation_id(request)
    add_observations(session, "more", "completed_sale", S21, 128, "IN", "good", [130])
    second = engine().valuate(session, model, 128, "IN", "INR", "good").valuation_id(request)

    assert first != second


def test_evidence_status(session):
    add_observations(session, "sales", "completed_sale", S21, 128, "IN", "good", [100] * 10)
    add_observations(session, "ads", "listing", "google-pixel-7", 128, "IN", "good", [100] * 3)
    add_observations(session, "synthetic-dev", "synthetic", "google-pixel-6a", 128, "IN", "fair", [1, 2, 3])

    status = engine().evidence_status(session)

    assert status[(S21, "IN")] == "evidence_backed"
    assert status[("google-pixel-7", "IN")] == "limited"
    assert status[("google-pixel-6a", "IN")] == "mock_only"
    assert (S21, "US") not in status
    assert ("google-pixel-6a", "IN") not in engine(include_mock=False).evidence_status(session)


def test_trend_uses_only_genuine_months_with_enough_data(session):
    add_observations(session, "sales", "completed_sale", S21, 128, "IN", "good", [100, 110, 120, 130],
                     days_ago=[0, 0, 0, 0])
    add_observations(session, "sales2", "completed_sale", S21, 128, "IN", "good", [90, 95], days_ago=[40, 40])
    add_observations(session, "synthetic-dev", "synthetic", S21, 128, "IN", "good", [1, 2, 3, 4])

    series = engine().trend(session, S21, 128, "IN", "good")

    assert list(series) == ["completed_sale"]
    assert series["completed_sale"] == [{"month": "2026-10", "median": Decimal("115.00"), "count": 4}]


# --- value types for /api/v1 (services.api_valuation) ----------------------------------------------------------


def _api_request(**device):
    from flipvalue.schemas import ApiValuationRequest

    return ApiValuationRequest.model_validate({
        "device": {"product_id": S21, "storage_gb": 128, **device}, "region": "IN", "currency": "INR",
        "condition": {"grade": "faulty", "faults": ["display_damage"]},
        "repair_scenario": {"repair_type": "screen_replacement"}})


def test_api_valuation_with_genuine_evidence_is_reproducible(session):
    from flipvalue.marketplace.service import OfferPolicy
    from flipvalue.services import api_valuation

    add_observations(session, "sales", "completed_sale", S21, 128, "IN", "faulty",
                     [10000 + 100 * i for i in range(10)])
    add_observations(session, "sales", "completed_sale", S21, 128, "IN", "good", [16000, 16500, 17000])
    add_observations(session, "dealer", "dealer_offer", S21, 128, "IN", "faulty", [7000, 7200, 7400])
    add_observations(session, "trade", "trade_in", S21, 128, "IN", "faulty", [9000, 9100, 9200])
    policy = OfferPolicy()

    first = api_valuation(session, engine(include_mock=False), _api_request(), policy, "val_a")
    second = api_valuation(session, engine(include_mock=False), _api_request(), policy, "val_b")

    assert first.model_dump(exclude={"id", "created_at"}) == second.model_dump(exclude={"id", "created_at"})
    assert (first.private_sale.value, first.private_sale.confidence) == (Decimal("10450.00"), "high")
    assert first.after_repair.confidence == "medium"  # 3 completed sales: real but thin
    assert first.repair.value_uplift == Decimal("6050.00") and first.repair.confidence == "medium"
    assert first.buyback.basis == "dealer_offer" and first.buyback.value == Decimal("7200.00")  # not trade-in
    assert first.mock is False and first.status == "partial"


def test_api_valuation_uplift_unavailable_without_post_repair_evidence(session):
    from flipvalue.marketplace.service import OfferPolicy
    from flipvalue.services import api_valuation

    add_observations(session, "sales", "listing", S21, 128, "IN", "faulty", [11000, 11500, 12000])
    v = api_valuation(session, engine(include_mock=False), _api_request(), OfferPolicy(), "val_c")

    assert v.private_sale.confidence == "low" and "asking prices" in v.private_sale.reason
    assert v.after_repair.available is False and v.repair.value_uplift is None
    assert v.repair.confidence == "insufficient"
