"""Partner API (POST /v1/valuations) against INTEGRATION_CONTRACT.md."""

from __future__ import annotations

import re
import time
from datetime import datetime

import pytest

from conftest import add_observations
from flipvalue import services
from flipvalue.db.session import transaction
from flipvalue.security import issue_key, revoke_key

URL = "/v1/valuations"


def assert_contract_shape(data: dict, currency: str) -> None:
    """Independent of our own models: the checks FixMyTech's client applies to every 200 response."""
    assert isinstance(data["api_version"], str)
    assert isinstance(data["valuation_id"], str) and 0 < len(data["valuation_id"]) <= 100
    assert data["currency"] == currency
    assert data["status"] in ("ok", "partial")
    assert isinstance(data["method"], str) and len(data["method"]) <= 200
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", data["data_timestamp"])
    datetime.fromisoformat(data["data_timestamp"])
    assert isinstance(data["warnings"], list) and len(data["warnings"]) <= 20
    assert all(isinstance(w, str) for w in data["warnings"])
    assert isinstance(data.get("mock", False), bool)
    for band in (data["as_is"], data["after_repair"]):
        if band is None:
            continue
        assert isinstance(band["value"], (int, float)) and band["value"] >= 0
        if band.get("low") is not None:
            assert 0 <= band["low"] <= band["value"]
        if band.get("high") is not None:
            assert band["value"] <= band["high"]


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert error["message"]
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error


# --- success -------------------------------------------------------------------------------


def test_success_with_repair_scenario(client, headers, body):
    response = client.post(URL, json=body, headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert_contract_shape(data, "INR")
    assert data["method"] == "comparables-v1"
    assert data["status"] == "ok"
    # faulty is valued from 'good' comparables after the repair
    assert data["after_repair"]["value"] > data["as_is"]["value"]
    assert data["mock"] is True
    assert data["warnings"][0].startswith("MOCK DATA")


def test_success_in_usd_for_us(client, headers, body):
    body.update(region="US", currency="USD")
    body["condition"]["grade"] = "fair"

    data = client.post(URL, json=body, headers=headers).json()

    assert_contract_shape(data, "USD")
    assert data["after_repair"] == data["as_is"]  # a repair does not change a working phone's grade


def test_without_repair_scenario_after_repair_is_null(client, headers, body):
    del body["repair_scenario"]

    response = client.post(URL, json=body, headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert "after_repair" in data and data["after_repair"] is None
    assert_contract_shape(data, "INR")


def test_faults_and_age_are_disclosed_not_priced(client, headers, body):
    with_fault = client.post(URL, json=body, headers=headers).json()
    body["condition"]["faults"] = []
    del body["device"]["age_months"]
    without = client.post(URL, json=body, headers=headers).json()

    assert with_fault["as_is"] == without["as_is"]
    assert any("not priced separately" in w for w in with_fault["warnings"])
    assert any("age is not used" in w for w in with_fault["warnings"])
    assert not any("not priced separately" in w or "age is not used" in w for w in without["warnings"])


def test_model_matching_ignores_case_and_accepts_marketing_name(client, headers, body):
    first = client.post(URL, json=body, headers=headers).json()
    body["device"].update(manufacturer="SAMSUNG", model="  galaxy   s21 ")

    second = client.post(URL, json=body, headers=headers).json()

    assert second["as_is"] == first["as_is"]


def test_single_variant_model_needs_no_storage(client, headers, body):
    body["device"] = {"manufacturer": "Google", "model": "Pixel 6a"}
    del body["repair_scenario"]

    response = client.post(URL, json=body, headers=headers)

    assert response.status_code == 200, response.text


def test_storage_variants_are_not_mixed(client, headers, body):
    del body["repair_scenario"]
    v128 = client.post(URL, json=body, headers=headers).json()
    body["device"]["storage_gb"] = 256
    v256 = client.post(URL, json=body, headers=headers).json()

    assert v128["as_is"] != v256["as_is"]


def test_few_observations_give_partial_with_min_max_range(client, headers, body):
    body["device"].update(manufacturer="Google", model="Pixel 7", storage_gb=256)

    data = client.post(URL, json=body, headers=headers).json()

    assert data["status"] == "partial"
    assert any("only 6 recent observations" in w for w in data["warnings"])
    assert_contract_shape(data, "INR")


def test_missing_after_repair_evidence_gives_partial(client, headers, body):
    body["device"] = {"manufacturer": "google", "model": "Pixel 6a"}

    data = client.post(URL, json=body, headers=headers).json()

    assert data["status"] == "partial"
    assert data["after_repair"] is None
    assert data["as_is"]["value"] > 0
    assert any("after_repair is not available" in w for w in data["warnings"])


def test_real_completed_sales_replace_synthetic_data(make_client, seeded_db, session_for, headers, body):
    session = session_for(seeded_db)
    add_observations(session, "test-sales", "completed_sale", "samsung-galaxy-s21", 128, "IN", "faulty",
                     [7000, 7200, 7400, 7600, 7800, 8000, 8200, 8400, 8600, 8800, 9000])
    session.commit()
    del body["repair_scenario"]

    data = make_client().post(URL, json=body, headers=headers).json()

    assert data["mock"] is False
    assert not any(w.startswith("MOCK") for w in data["warnings"])
    assert data["as_is"] == {"value": 8000.0, "low": 7200.0, "high": 8800.0}
    assert data["data_timestamp"] == "2026-09-21T00:00:00Z"


def test_production_never_uses_mock_data(make_client, headers, body):
    client = make_client(environment="production", hash_salt="s" * 32, allow_sqlite_in_production=True)

    response = client.post(URL, json=body, headers=headers)

    assert_error(response, 404, "no_data_for_condition")
    assert "mock" not in response.text.lower()


def test_idempotent_repeat_replays_the_same_response(client, headers, body):
    retry_headers = {**headers, "Idempotency-Key": "4f0c2a43-9d5e-4c8b-9a51-2f7c4e0d1b11"}

    first = client.post(URL, json=body, headers=retry_headers)
    second = client.post(URL, json=body, headers=retry_headers)

    assert first.json() == second.json()
    assert second.headers.get("Idempotent-Replayed") == "true"
    body["condition"]["grade"] = "poor"
    assert client.post(URL, json=body, headers=headers).json()["valuation_id"] != first.json()["valuation_id"]


def test_identical_requests_get_identical_ids_without_idempotency_key(client, headers, body):
    first = client.post(URL, json=body, headers=headers).json()
    second = client.post(URL, json=body, headers=headers).json()

    assert first["valuation_id"] == second["valuation_id"]


def test_reused_idempotency_key_with_different_body_is_422(client, headers, body):
    retry_headers = {**headers, "Idempotency-Key": "same-key"}
    client.post(URL, json=body, headers=retry_headers)
    body["condition"]["grade"] = "poor"

    assert_error(client.post(URL, json=body, headers=retry_headers), 422, "idempotency_key_reused")


def test_request_id_is_echoed(client, headers, body):
    response = client.post(URL, json=body, headers={**headers, "X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


def test_unsafe_request_id_is_replaced(client, headers, body):
    response = client.post(URL, json=body, headers={**headers, "X-Request-ID": "<script>"})

    assert response.headers["X-Request-ID"] != "<script>"


# --- 401 -----------------------------------------------------------------------------------


@pytest.mark.parametrize("key", [None, "", "wrong-key", "x" * 64])
def test_bad_or_missing_key_is_401(client, body, key):
    headers = {} if key is None else {"X-API-Key": key}

    assert_error(client.post(URL, json=body, headers=headers), 401, "unauthorized")


def test_bad_key_is_rejected_before_body_is_read(client):
    assert_error(client.post(URL, content=b"not json", headers={"X-API-Key": "wrong"}), 401, "unauthorized")


def test_admin_key_cannot_call_partner_api(client, admin_headers, body):
    assert_error(client.post(URL, json=body, headers=admin_headers), 401, "unauthorized")


def test_database_keys_work_and_can_be_revoked(make_client, seeded_db, session_for, body):
    session = session_for(seeded_db)
    client_row, key = issue_key(session, "fixmytech", "partner")
    session.commit()
    client = make_client()

    assert client.post(URL, json=body, headers={"X-API-Key": key}).status_code == 200
    revoke_key(session, client_row.id)
    session.commit()
    assert_error(client.post(URL, json=body, headers={"X-API-Key": key}), 401, "unauthorized")


# --- 404 -----------------------------------------------------------------------------------


def test_unknown_model_is_404(client, headers, body):
    body["device"]["model"] = "SM-X999Z"

    error = assert_error(client.post(URL, json=body, headers=headers), 404, "unsupported_model")
    assert "SM-X999Z" in error["message"]


def test_known_model_under_wrong_manufacturer_is_404(client, headers, body):
    body["device"]["manufacturer"] = "Google"

    assert_error(client.post(URL, json=body, headers=headers), 404, "unsupported_model")


def test_grade_without_evidence_is_404(client, headers, body):
    body["device"] = {"manufacturer": "Google", "model": "Pixel 6a"}
    body["condition"]["grade"] = "poor"

    error = assert_error(client.post(URL, json=body, headers=headers), 404, "no_data_for_condition")
    assert "3 needed" in error["message"]


def test_too_few_observations_is_404(client, headers, body):
    body["device"] = {"manufacturer": "Google", "model": "Pixel 6a"}
    body["condition"]["grade"] = "good"  # only 2 synthetic observations

    assert_error(client.post(URL, json=body, headers=headers), 404, "no_data_for_condition")


def test_catalogued_model_without_any_data_is_404(client, headers, body):
    body["device"] = {"manufacturer": "samsung", "model": "SM-S911B", "storage_gb": 128}

    assert_error(client.post(URL, json=body, headers=headers), 404, "no_data_for_condition")


def test_multi_variant_model_without_storage_is_404(client, headers, body):
    del body["device"]["storage_gb"]

    error = assert_error(client.post(URL, json=body, headers=headers), 404, "no_data_for_condition")
    assert "storage_gb is required" in error["message"]


def test_uncatalogued_storage_is_404(client, headers, body):
    body["device"]["storage_gb"] = 512

    assert_error(client.post(URL, json=body, headers=headers), 404, "no_data_for_condition")


# --- 422 -----------------------------------------------------------------------------------


def test_invalid_grade_is_422(client, headers, body):
    body["condition"]["grade"] = "mint"

    error = assert_error(client.post(URL, json=body, headers=headers), 422, "validation_error")
    assert error["message"].startswith("condition.grade:")


@pytest.mark.parametrize(
    "mutate, field",
    [
        (lambda b: b["condition"].update(faults=["broken"]), "condition.faults.0"),
        (lambda b: b["repair_scenario"].update(repair_type="polish"), "repair_scenario.repair_type"),
        (lambda b: b["repair_scenario"].clear(), "repair_scenario.repair_type"),
        (lambda b: b["condition"].pop("faults"), "condition.faults"),
        (lambda b: b["device"].pop("model"), "device.model"),
        (lambda b: b["device"].update(storage_gb=0), "device.storage_gb"),
        (lambda b: b["device"].update(storage_gb="128"), "device.storage_gb"),
        (lambda b: b["device"].update(age_months=241), "device.age_months"),
        (lambda b: b["device"].update(manufacturer="   "), "device.manufacturer"),
        (lambda b: b.update(currency="inr"), "currency"),
        (lambda b: b.update(region="IND"), "region"),
        (lambda b: b.update(imei="123"), "imei"),
    ],
)
def test_invalid_fields_are_422(client, headers, body, mutate, field):
    mutate(body)

    error = assert_error(client.post(URL, json=body, headers=headers), 422, "validation_error")
    assert error["message"].startswith(f"{field}:")


def test_unsupported_region_is_422(client, headers, body):
    body.update(region="GB", currency="GBP")

    assert_error(client.post(URL, json=body, headers=headers), 422, "unsupported_region")


def test_currency_not_matching_region_is_422(client, headers, body):
    body["currency"] = "USD"

    error = assert_error(client.post(URL, json=body, headers=headers), 422, "unsupported_currency")
    assert "INR" in error["message"]


def test_non_json_body_is_422(client, headers):
    response = client.post(URL, content=b"{not json", headers={**headers, "Content-Type": "application/json"})

    assert assert_error(response, 422, "validation_error")["message"] == "Request body is not valid JSON."


# --- abuse controls and failures -----------------------------------------------------------


def test_rate_limit_is_429_with_retry_after(make_client, headers, body):
    client = make_client(rate_limit_per_minute=2)

    assert client.post(URL, json=body, headers=headers).status_code == 200
    assert client.post(URL, json=body, headers=headers).status_code == 200
    response = client.post(URL, json=body, headers=headers)

    assert_error(response, 429, "rate_limited")
    assert 1 <= int(response.headers["Retry-After"]) <= 60


def test_rate_limit_is_shared_between_app_instances(make_client, headers, body):
    """Two server processes on one database share the counter."""
    a, b = make_client(rate_limit_per_minute=2), make_client(rate_limit_per_minute=2)

    a.post(URL, json=body, headers=headers)
    b.post(URL, json=body, headers=headers)

    assert_error(a.post(URL, json=body, headers=headers), 429, "rate_limited")


def test_oversized_body_is_413(client, headers, body):
    body["device"]["model"] = "x" * 20_000

    assert_error(client.post(URL, json=body, headers=headers), 413, "payload_too_large")


def test_slow_valuation_times_out_with_retryable_503(make_client, headers, body, monkeypatch):
    original = services.partner_valuation

    def slow(*args, **kwargs):
        time.sleep(1.5)
        return original(*args, **kwargs)

    monkeypatch.setattr("flipvalue.routes.partner.partner_valuation", slow)
    client = make_client(request_timeout_s=0.5)

    response = client.post(URL, json=body, headers=headers)

    assert_error(response, 503, "service_timeout")
    assert response.headers["Retry-After"] == "1"
    monkeypatch.undo()
    assert client.post(URL, json=body, headers=headers).status_code == 200  # recovers


def test_unsupported_api_version_is_400(client, headers, body):
    response = client.post(URL, json=body, headers={**headers, "FlipValue-API-Version": "2"})

    assert_error(response, 400, "unsupported_api_version")


def test_unknown_route_uses_error_envelope(client, headers):
    assert_error(client.get("/v1/nothing", headers=headers), 404, "not_found")


def test_security_headers(client, headers, body):
    response = client.post(URL, json=body, headers=headers)

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_requests_are_logged_without_secrets(client, headers, body, seeded_db, session_for, api_key):
    client.post(URL, json=body, headers=headers)
    body["device"]["model"] = "nope"
    client.post(URL, json=body, headers=headers)

    from flipvalue.db.models import RequestLog

    rows = session_for(seeded_db).query(RequestLog).all()
    assert [(r.channel, r.status, r.error_code) for r in rows] == [
        ("partner", 200, None), ("partner", 404, "unsupported_model")]
    assert rows[0].method_version == "comparables-v1"
    assert all(api_key not in repr(r.__dict__) for r in rows)


def test_openapi_documents_endpoint_and_key(client):
    spec = client.get("/openapi.json").json()

    operation = spec["paths"]["/v1/valuations"]["post"]
    assert {"401", "404", "422", "429", "503"} <= set(operation["responses"])
    assert spec["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-API-Key"
    band = spec["components"]["schemas"]["ValueBand"]
    assert band["required"] == ["value"]
    request_schema = spec["components"]["schemas"]["ValuationRequest"]
    assert set(request_schema["required"]) == {"device", "region", "currency", "condition"}


def test_liveness_and_readiness(client, make_client, tmp_path):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200

    empty = make_client(database_url=f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    response = empty.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] is False


def test_transaction_helper_rolls_back(seeded_db):
    from flipvalue.db.models import AuditLog
    from flipvalue.db.session import make_engine, make_sessionmaker

    sessions = make_sessionmaker(make_engine(seeded_db))
    with pytest.raises(RuntimeError), transaction(sessions) as session:
        session.add(AuditLog(actor="t", action="t", detail="t"))
        session.flush()
        raise RuntimeError
    with transaction(sessions) as session:
        assert session.query(AuditLog).filter_by(actor="t").count() == 0
