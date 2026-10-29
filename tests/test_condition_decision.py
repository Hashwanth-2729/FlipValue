"""Questionnaire -> grade/faults mapping and repair-versus-sell arithmetic."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from flipvalue.condition import Assessment, derive
from flipvalue.decision import DecisionInput, decide

GOOD = dict(powers_on="yes", usable_normally="yes", screen="perfect", body="like_new", battery="normal",
            charging="normal", cameras="working", audio="working", buttons="working", connectivity="working",
            liquid_damage="no")


def assess(**changes) -> Assessment:
    return Assessment(**{**GOOD, **changes})


@pytest.mark.parametrize("changes, grade", [
    ({}, "excellent"),
    ({"screen": "light_scratches"}, "good"),
    ({"body": "visible_wear"}, "fair"),
    ({"screen": "light_scratches", "body": "heavy_wear"}, "poor"),
    ({"body": "cracked_back"}, "poor"),
    ({"screen": "cracked", "screen_touch_works": "yes"}, "poor"),
])
def test_cosmetic_grades(changes, grade):
    d = derive(assess(**changes))
    assert d.grade == grade and d.faults == []


@pytest.mark.parametrize("changes, fault", [
    ({"screen": "display_fault"}, "display_damage"),
    ({"screen": "cracked", "screen_touch_works": "no"}, "display_damage"),
    ({"battery": "drains_fast"}, "battery_wear"),
    ({"charging": "not_charging"}, "charging_path"),
    ({"cameras": "issue"}, "camera_fault"),
    ({"audio": "issue"}, "audio_fault"),
    ({"connectivity": "issue"}, "connectivity_issue"),
])
def test_functional_faults_make_the_phone_faulty(changes, fault):
    d = derive(assess(**changes))
    assert d.grade == "faulty"
    assert fault in d.faults
    assert d.reasons[0].startswith("Graded faulty because")


def test_not_powering_on_and_buttons_are_faulty_without_a_fault_category():
    assert derive(assess(powers_on="no")).grade == "faulty"
    d = derive(assess(buttons="issue"))
    assert d.grade == "faulty" and d.faults == []


def test_liquid_damage_is_a_fault_but_not_a_grade_change_while_working():
    d = derive(assess(liquid_damage="yes", screen="light_scratches"))
    assert d.grade == "good" and d.faults == ["liquid_damage"]


def test_uncertainty_and_unused_inputs_are_reported():
    d = derive(assess(cameras="not_tested", usable_normally="unsure", liquid_damage="unsure",
                      previous_repairs=["screen"]))
    assert d.grade == "excellent"
    assert len(d.uncertainties) == 3
    assert d.not_used


def test_swollen_battery_carries_a_safety_note():
    assert derive(assess(battery="swollen")).safety


def test_touch_question_only_for_cracked_screens():
    with pytest.raises(ValidationError):
        assess(screen="cracked")
    with pytest.raises(ValidationError):
        assess(screen="perfect", screen_touch_works="yes")


def test_decision_arithmetic():
    r = decide(DecisionInput(currency="INR", as_is_value=Decimal(8000), after_repair_value=Decimal(22000),
                             repair_cost=Decimal(5000), selling_fee_pct=Decimal(10), selling_fixed_cost=Decimal(200),
                             replacement_price=Decimal(30000)))
    s = {x.key: x for x in r.scenarios}
    assert s["sell_as_is"].net == Decimal("7000.00")         # 8000 - 800 - 200
    assert s["repair_then_sell"].net == Decimal("14600.00")  # 22000 - 2200 - 200 - 5000
    assert s["repair_and_keep"].net == Decimal("-5000.00")
    assert s["sell_and_replace"].net == Decimal("-23000.00")
    assert r.repair_first_advantage == Decimal("7600.00")


def test_decision_with_missing_values_is_not_invented():
    r = decide(DecisionInput(currency="USD", as_is_value=Decimal(100)))
    s = {x.key: x for x in r.scenarios}
    assert s["sell_as_is"].available
    assert not s["repair_then_sell"].available
    assert s["repair_then_sell"].missing == ["after-repair value", "repair cost"]
    assert s["repair_then_sell"].net is None
    assert r.repair_first_advantage is None


def test_decision_records_repair_cost_basis():
    r = decide(DecisionInput(currency="INR", repair_cost=Decimal(10), repair_cost_basis="verified_quote"))
    assert any("verified quote" in a for a in r.assumptions)


def test_decision_rejects_negative_inputs():
    with pytest.raises(ValidationError):
        DecisionInput(currency="INR", repair_cost=Decimal(-1))
