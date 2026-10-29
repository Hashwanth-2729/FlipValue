"""Public website API (/api) and operator API (/admin/api)."""

from __future__ import annotations

import pytest

from conftest import add_observations
from test_condition_decision import GOOD

VALUE = "/api/valuations"


@pytest.fixture
def public_body() -> dict:
    return {"device": {"model_id": "samsung-galaxy-s21", "storage_gb": 128}, "region": "IN", "currency": "INR",
            "assessment": {**GOOD, "battery": "drains_fast"}, "repair_type": "battery_replacement"}


# --- public ------------------------------------------------------------------------------------


def test_meta_reports_mock_only_data(client):
    meta = client.get("/api/meta").json()

    assert meta["data_status"] == "mock_only"
    assert meta["real_observations"] == 0 and meta["mock_observations"] > 0
    assert meta["regions"] == {"IN": "INR", "US": "USD"}
    assert [s["id"] for s in meta["sources"]] == ["fixture-offers", "synthetic-dev"]
    assert all(s["is_mock"] for s in meta["sources"])


def test_meta_in_production_hides_mock(make_client):
    meta = make_client(environment="production", hash_salt="s" * 32,
                       allow_sqlite_in_production=True).get("/api/meta").json()

    assert meta["data_status"] == "none" and meta["mock_data_in_use"] is False and meta["sources"] == []


def test_catalogue_search_with_evidence_status(client):
    models = {m["id"]: m for m in client.get("/api/catalogue").json()}

    assert len(models) == 31
    assert models["samsung-galaxy-s21"]["oem_codes"] == ["SM-G991B", "SM-G991B/DS", "SM-G991U"]
    assert models["samsung-galaxy-s21"]["storage_gb"] == [128, 256]
    assert models["samsung-galaxy-s21"]["evidence"] == {"IN": "mock_only", "US": "mock_only"}
    assert models["apple-iphone-13"]["evidence"] == {"IN": "insufficient", "US": "insufficient"}
    assert [m["id"] for m in client.get("/api/catalogue", params={"q": "SM-S911"}).json()] == ["samsung-galaxy-s23"]
    assert client.get("/api/catalogue", params={"q": "nokia"}).json() == []
    assert client.get("/api/catalogue/nope").status_code == 404


def test_public_valuation_uses_the_same_engine_as_the_partner_api(client, headers, public_body):
    public = client.post(VALUE, json=public_body).json()
    partner = client.post("/v1/valuations", headers=headers, json={
        "device": {"manufacturer": "Samsung", "model": "SM-G991B", "storage_gb": 128}, "region": "IN",
        "currency": "INR", "condition": {"grade": "faulty", "faults": ["battery_wear"]},
        "repair_scenario": {"repair_type": "battery_replacement"}}).json()

    assert public["condition"]["grade"] == "faulty" and public["condition"]["faults"] == ["battery_wear"]
    assert public["condition"]["customer_reported"] is True
    assert public["as_is"]["value"] == partner["as_is"]["value"]
    assert public["after_repair"]["value"] == partner["after_repair"]["value"]
    assert public["assumed_grade_after_repair"] == "good"
    assert public["mock"] is True and public["as_is"]["sources"][0]["is_mock"] is True
    assert public["as_is"]["basis"] == "synthetic" and public["as_is"]["observation_count"] == 12
    assert public["explanation"] and public["status"] == "ok"


def test_public_valuation_unavailable_state_is_not_an_invented_price(client, public_body):
    public_body["device"] = {"model_id": "apple-iphone-13", "storage_gb": 128}

    response = client.post(VALUE, json=public_body)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unavailable"
    assert data["as_is"] is None and data["after_repair"] is None
    assert "Not enough recent price evidence" in data["as_is_unavailable_reason"]


def test_public_valuation_errors(client, public_body):
    public_body["device"]["model_id"] = "nope"
    assert client.post(VALUE, json=public_body).json()["error"]["code"] == "unsupported_model"
    public_body["device"] = {"model_id": "samsung-galaxy-s21"}
    assert client.post(VALUE, json=public_body).json()["error"]["code"] == "no_data_for_condition"
    public_body["device"]["storage_gb"] = 128
    public_body["currency"] = "USD"
    assert client.post(VALUE, json=public_body).json()["error"]["code"] == "unsupported_currency"
    public_body["assessment"]["screen"] = "shattered"
    assert client.post(VALUE, json=public_body).status_code == 422


def test_public_rate_limit_per_ip(make_client, public_body):
    client = make_client(public_rate_limit_per_minute=2)

    assert client.post(VALUE, json=public_body).status_code == 200
    assert client.post(VALUE, json=public_body).status_code == 200
    response = client.post(VALUE, json=public_body)
    assert response.status_code == 429 and "Retry-After" in response.headers
    assert client.get("/api/meta").status_code == 200  # reads have a separate, larger allowance


def test_decision_endpoint(client):
    response = client.post("/api/decision", json={"currency": "INR", "as_is_value": 8000,
                                                   "after_repair_value": 22000, "repair_cost": 5000,
                                                   "selling_fee_pct": 10})
    data = response.json()

    assert response.status_code == 200
    assert data["repair_first_advantage"] == 7600.0  # (22000-2200-5000) - (8000-800); a JSON number
    assert client.post("/api/decision", json={"currency": "EUR"}).status_code == 422


def test_saved_valuation_lifecycle(client, public_body):
    saved = client.post("/api/saved", json=public_body)
    assert saved.status_code == 201
    saved_id, token = saved.json()["id"], saved.json()["delete_token"]
    assert len(saved_id) >= 22

    fetched = client.get(f"/api/saved/{saved_id}").json()
    assert fetched["result"]["as_is"] == saved.json()["result"]["as_is"]
    assert client.get(f"/api/saved/{saved_id}/request").json()["assessment"]["battery"] == "drains_fast"

    assert client.delete(f"/api/saved/{saved_id}").status_code == 403
    assert client.delete(f"/api/saved/{saved_id}", headers={"X-Delete-Token": "wrong"}).status_code == 403
    assert client.delete(f"/api/saved/{saved_id}", headers={"X-Delete-Token": token}).status_code == 204
    assert client.get(f"/api/saved/{saved_id}").status_code == 404


def test_saved_valuation_contains_no_delete_token_or_personal_data(client, public_body):
    saved = client.post("/api/saved", json=public_body).json()

    fetched = client.get(f"/api/saved/{saved['id']}")
    assert saved["delete_token"] not in fetched.text


def test_trends_exclude_mock_data(client):
    data = client.get("/api/trends", params={"model_id": "samsung-galaxy-s21", "storage_gb": 128,
                                             "region": "IN", "grade": "good"}).json()

    assert data["available"] is False and data["series"] == {}
    assert "never shown as history" in data["reason"]


def test_trends_with_genuine_history(make_client, seeded_db, session_for):
    session = session_for(seeded_db)
    for i, days in enumerate((5, 35, 65)):
        add_observations(session, f"sales-{i}", "completed_sale", "samsung-galaxy-s21", 128, "IN", "good",
                         [100, 110, 120], days_ago=days)
    session.commit()

    data = make_client().get("/api/trends", params={"model_id": "samsung-galaxy-s21", "storage_gb": 128,
                                                    "region": "IN", "grade": "good"}).json()

    assert data["available"] is True
    assert [p["count"] for p in data["series"]["completed_sale"]] == [3, 3, 3]
    assert data["series"]["completed_sale"][0]["median"] == 110.0


# --- admin -------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/admin/api/sources", "/admin/api/jobs", "/admin/api/metrics",
                                  "/admin/api/audit"])
def test_admin_requires_admin_key(client, headers, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers=headers).status_code == 401  # partner key is not enough


def test_admin_import_flow_with_audit(client, admin_headers):
    source = {"id": "manual-in", "name": "Manual IN", "source_type": "completed_sale",
              "collection_method": "manual CSV", "markets": "IN", "terms_note": "permission on file",
              "verified": True}
    assert client.post("/admin/api/sources", json=source, headers=admin_headers).status_code == 201
    csv_text = ("manufacturer,model,storage_gb,region,currency,grade,price,observed_at,external_ref\n"
                "samsung,SM-G991B,128,IN,INR,good,21000,2026-09-01,a\n"
                "samsung,SM-G991B,128,IN,INR,mint,21000,2026-09-01,b\n")

    job = client.post("/admin/api/imports", json={"source_id": "manual-in", "csv_text": csv_text},
                      headers=admin_headers).json()

    assert (job["accepted"], job["rejected"]) == (1, 1)
    rejected = client.get(f"/admin/api/jobs/{job['id']}/rejected", headers=admin_headers).json()
    assert rejected[0]["line"] == 3 and "grade" in rejected[0]["reason"]
    sources = {s["id"]: s for s in client.get("/admin/api/sources", headers=admin_headers).json()}
    assert sources["manual-in"]["observation_count"] == 1 and sources["manual-in"]["freshness_days"] == 30
    actions = [a["action"] for a in client.get("/admin/api/audit", headers=admin_headers).json()]
    assert actions[:2] == ["ingestion.import", "source.register"]


def test_admin_cannot_create_synthetic_source_or_import_into_it(client, admin_headers):
    bad = {"id": "fake", "name": "x", "source_type": "synthetic", "collection_method": "x", "markets": "IN",
           "terms_note": "x", "verified": False}
    assert client.post("/admin/api/sources", json=bad, headers=admin_headers).status_code == 422
    assert client.post("/admin/api/imports", json={"source_id": "synthetic-dev", "csv_text": "x"},
                       headers=admin_headers).status_code == 422


def test_admin_alias_management(client, admin_headers, headers):
    response = client.post("/admin/api/models/samsung-galaxy-s21/aliases",
                           json={"alias": "SM-G991N", "kind": "oem_code"}, headers=admin_headers)
    assert response.status_code == 201
    duplicate = client.post("/admin/api/models/google-pixel-7/aliases",
                            json={"alias": "Galaxy S21", "kind": "name"}, headers=admin_headers)
    assert duplicate.status_code == 201  # different manufacturer, so no clash
    clash = client.post("/admin/api/models/samsung-galaxy-s23/aliases",
                        json={"alias": "sm-g991n", "kind": "oem_code"}, headers=admin_headers)
    assert clash.status_code == 409


def test_admin_metrics(client, admin_headers, headers, body):
    client.post("/v1/valuations", json=body, headers=headers)
    body["device"]["model"] = "nope"
    client.post("/v1/valuations", json=body, headers=headers)

    metrics = client.get("/admin/api/metrics", headers=admin_headers).json()

    assert metrics["requests_by_channel"]["partner"] == 2
    assert metrics["error_codes"] == {"unsupported_model": 1}
    assert metrics["method_versions"] == {"comparables-v1": 1}
    assert metrics["latency_ms_p50"] is not None


def test_admin_import_allows_larger_bodies_than_public(client, admin_headers):
    big = "x" * 100_000
    assert client.post("/api/decision", content=big, headers={"Content-Type": "application/json"}).status_code == 413
    response = client.post("/admin/api/imports", json={"source_id": "none", "csv_text": big}, headers=admin_headers)
    assert response.status_code == 404  # reached the handler: unknown source
