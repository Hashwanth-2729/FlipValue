"""Accounts, self-service API keys, scopes, quotas, usage, /api/v1 endpoints, watchlists."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from flipvalue.db.models import ApiClient, AuditLog
from flipvalue.security import hash_key

WEB = {"X-FlipValue-Client": "web"}
PASSWORD = "correct horse battery"


def signup(client, email="dev@example.com"):
    r = client.post("/api/account/register", json={"email": email, "password": PASSWORD}, headers=WEB)
    assert r.status_code == 201, r.text
    return r


def new_key(client, scopes=("valuation:read", "market_prices:read", "price_history:read"), name="my app"):
    r = client.post("/api/account/keys", json={"name": name, "scopes": list(scopes)}, headers=WEB)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def dev(make_client):
    client = make_client()
    signup(client)
    return client


VALUATION = {"device": {"manufacturer": "Samsung", "model": "SM-G991B", "storage_gb": 128}, "region": "IN",
             "currency": "INR", "condition": {"grade": "faulty", "faults": ["display_damage"]},
             "repair_scenario": {"repair_type": "screen_replacement"}}


# --- accounts --------------------------------------------------------------------------------------------------


def test_account_signup_login_logout_and_cookie_flags(make_client):
    client = make_client()
    r = signup(client)
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie.replace("Strict", "strict")
    assert "Path=/api/account" in cookie
    assert client.get("/api/account/me").json()["email"] == "dev@example.com"

    assert client.post("/api/account/register", json={"email": "DEV@example.com", "password": PASSWORD},
                       headers=WEB).status_code == 422  # duplicate (case-insensitive)
    assert client.post("/api/account/logout", headers=WEB).status_code == 204
    assert client.get("/api/account/me").status_code == 401
    assert client.post("/api/account/login", json={"email": "dev@example.com", "password": "wrong password"},
                       headers=WEB).json()["error"]["code"] == "invalid_credentials"
    assert client.post("/api/account/login", json={"email": "dev@example.com", "password": PASSWORD},
                       headers=WEB).status_code == 200


def test_state_changes_require_the_web_client_header(dev):
    r = dev.post("/api/account/keys", json={"name": "x", "scopes": ["valuation:read"]})
    assert (r.status_code, r.json()["error"]["code"]) == (403, "forbidden")


def test_short_password_and_closed_signup(make_client):
    client = make_client()
    r = client.post("/api/account/register", json={"email": "a@example.com", "password": "short"}, headers=WEB)
    assert r.status_code == 422
    closed = make_client(developer_signup=False)
    assert closed.post("/api/account/register", json={"email": "b@example.com", "password": PASSWORD},
                       headers=WEB).json()["error"]["code"] == "signup_closed"


def test_login_attempts_are_rate_limited(make_client):
    client = make_client()
    codes = [client.post("/api/account/login", json={"email": "x@example.com", "password": "nope nope nope"},
                         headers=WEB).status_code for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[-1] == 429


# --- key lifecycle ---------------------------------------------------------------------------------------------


def test_key_is_shown_once_and_stored_only_as_a_hash(dev, session_for, seeded_db):
    created = new_key(dev, ["valuation:read"])
    raw = created["key"]
    assert raw.startswith("fv_") and len(raw) >= 43 and created["prefix"] == raw[:10]
    assert created["scopes"] == ["valuation:read"] and created["status"] == "active"
    assert created["rate_limit_per_minute"] == 60 and created["daily_quota"] == 1000

    listed = dev.get("/api/account/keys").json()
    assert "key" not in listed[0] and raw not in str(listed)
    session = session_for(seeded_db)
    row = session.scalars(select(ApiClient).where(ApiClient.id == created["id"])).one()
    assert row.key_hash == hash_key(raw) and raw not in (row.key_prefix, row.name, row.scopes)
    assert all(raw not in a.detail for a in session.scalars(select(AuditLog)))


def test_key_verification_valid_missing_invalid_revoked(dev):
    raw = new_key(dev)["key"]
    ok = dev.post("/api/v1/valuations", json=VALUATION, headers={"X-API-Key": raw})
    assert ok.status_code == 201
    assert dev.post("/api/v1/valuations", json=VALUATION).json()["error"]["code"] == "unauthorized"
    assert dev.post("/api/v1/valuations", json=VALUATION, headers={"X-API-Key": raw + "x"}).status_code == 401
    assert dev.post("/api/v1/valuations", json=VALUATION, headers={"X-API-Key": "x" * 500}).status_code == 401

    key_id = dev.get("/api/account/keys").json()[0]["id"]
    revoked = dev.delete(f"/api/account/keys/{key_id}", headers=WEB).json()
    assert revoked["status"] == "revoked"
    after = dev.post("/api/v1/valuations", json=VALUATION, headers={"X-API-Key": raw})
    assert after.status_code == 401  # rejected on the very next request
    # a revoked self-service key also stops working on the partner endpoint
    assert dev.post("/v1/valuations", json=VALUATION, headers={"X-API-Key": raw}).status_code == 401


def test_key_limit_per_account(make_client):
    client = make_client(max_keys_per_account=2)
    signup(client)
    new_key(client)
    new_key(client)
    r = client.post("/api/account/keys", json={"name": "3", "scopes": ["valuation:read"]}, headers=WEB)
    assert r.json()["error"]["code"] == "key_limit_reached"


def test_accounts_cannot_see_or_revoke_each_others_keys(make_client):
    alice, bob = make_client(), make_client()
    signup(alice, "alice@example.com")
    signup(bob, "bob@example.com")
    alice_key = new_key(alice)
    assert bob.get("/api/account/keys").json() == []
    assert bob.delete(f"/api/account/keys/{alice_key['id']}", headers=WEB).status_code == 404
    assert bob.get(f"/api/account/keys/{alice_key['id']}/usage").status_code == 404


# --- scopes, limits, usage -------------------------------------------------------------------------------------


def test_scopes_are_enforced_server_side(dev):
    raw = new_key(dev, ["market_prices:read"])["key"]
    h = {"X-API-Key": raw}
    r = dev.post("/api/v1/valuations", json=VALUATION, headers=h)
    assert (r.status_code, r.json()["error"]["code"]) == (403, "insufficient_scope")
    assert dev.get("/api/v1/price-history?product_id=samsung-galaxy-s21&storage_gb=128", headers=h).status_code == 403
    assert dev.get("/api/v1/market-prices?product_id=samsung-galaxy-s21&storage_gb=128", headers=h).status_code == 200
    assert dev.post("/v1/valuations", json=VALUATION, headers=h).json()["error"]["code"] == "insufficient_scope"
    assert dev.get("/api/v1/products/samsung-galaxy-s21", headers=h).status_code == 200  # no scope needed


def test_rate_limit_headers_and_exhaustion(make_client):
    client = make_client(developer_rate_limit_per_minute=3)
    signup(client)
    h = {"X-API-Key": new_key(client)["key"]}
    responses = [client.get("/api/v1/products", headers=h) for _ in range(4)]
    assert [r.status_code for r in responses] == [200, 200, 200, 429]
    assert [r.headers["X-RateLimit-Remaining"] for r in responses] == ["2", "1", "0", "0"]
    assert responses[0].headers["X-RateLimit-Limit"] == "3"
    assert responses[-1].json()["error"]["code"] == "rate_limited" and int(responses[-1].headers["Retry-After"]) > 0


def test_daily_quota(make_client):
    client = make_client(developer_daily_quota=2)
    signup(client)
    h = {"X-API-Key": new_key(client)["key"]}
    codes = [client.get("/api/v1/products", headers=h) for _ in range(3)]
    assert [r.status_code for r in codes] == [200, 200, 429]
    assert codes[-1].json()["error"]["code"] == "quota_exceeded" and codes[0].headers["X-Quota-Limit"] == "2"


def test_usage_is_counted_per_key_and_private(make_client):
    client = make_client()
    signup(client)
    first, second = new_key(client, name="one")["key"], new_key(client, name="two")["key"]
    client.get("/api/v1/products", headers={"X-API-Key": first})
    client.get("/api/v1/products/nope", headers={"X-API-Key": first})
    client.get("/api/v1/products", headers={"X-API-Key": second})

    usage = client.get("/api/v1/usage", headers={"X-API-Key": first}).json()
    assert usage["total"] == 2  # the usage call itself is recorded after it answers
    assert usage["by_endpoint"] == {"/api/v1/products": 1, "/api/v1/products/{id}": 1}
    assert usage["by_status"] == {"200": 1, "404": 1} and usage["limits"]["rate_limit_per_minute"] == 60

    keys = {k["name"]: k for k in client.get("/api/account/keys").json()}
    assert keys["one"]["requests_today"] == 3 and keys["two"]["requests_today"] == 1
    assert keys["one"]["last_used_at"] is not None
    portal = client.get(f"/api/account/keys/{keys['one']['id']}/usage").json()
    assert portal["total"] == 3 and portal["by_day"][0]["errors"] == 1


def test_operator_env_key_still_works_with_all_scopes(client, headers):
    r = client.post("/api/v1/valuations", json=VALUATION, headers={"X-API-Key": headers["X-API-Key"]})
    assert r.status_code == 201
    assert "X-Quota-Limit" not in r.headers  # operator keys have no daily quota by default


# --- endpoints -------------------------------------------------------------------------------------------------


def test_health_needs_no_key_and_reveals_no_secrets(make_client):
    client = make_client(flipkart_affiliate_id="aff", flipkart_affiliate_token="tok-secret-123")
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok" and body["api_version"] == "1"
    assert "tok-secret-123" not in str(body)


def test_valuation_separates_value_types_and_is_readable_only_by_its_owner(make_client):
    alice, bob = make_client(), make_client()
    signup(alice, "alice@example.com")
    signup(bob, "bob@example.com")
    a_key, a_key2, b_key = new_key(alice)["key"], new_key(alice)["key"], new_key(bob)["key"]

    v = alice.post("/api/v1/valuations", json=VALUATION, headers={"X-API-Key": a_key}).json()
    assert v["id"].startswith("val_") and v["currency"] == "INR" and v["mock"] is True
    assert v["private_sale"]["available"] and v["private_sale"]["low"] <= v["private_sale"]["value"]
    assert v["private_sale"]["confidence"] == "low"  # synthetic data is never more than low confidence
    assert v["after_repair"]["available"] and v["repair"]["assumed_grade_after_repair"] == "good"
    assert v["repair"]["value_uplift"] == pytest.approx(v["after_repair"]["value"] - v["private_sale"]["value"])
    assert v["buyback"]["available"] is False and "manually" in v["buyback"]["reason"]
    assert v["refurbished_retail"]["available"] and v["refurbished_retail"]["basis"] == "refurbished_offers"
    assert v["refurbished_retail"]["observation_count"] == 3
    assert v["original_retail"]["value"] == 69999 and v["original_retail"]["basis"] == "mrp"
    assert v["limitations"] and v["assumptions"]

    assert alice.get(f"/api/v1/valuations/{v['id']}", headers={"X-API-Key": a_key2}).json()["id"] == v["id"]
    hidden = bob.get(f"/api/v1/valuations/{v['id']}", headers={"X-API-Key": b_key})
    assert hidden.status_code == 404 and hidden.json()["error"]["code"] == "not_found"

    # random, not derived from the request: the same request gets a new id
    again = alice.post("/api/v1/valuations", json=VALUATION, headers={"X-API-Key": a_key}).json()
    assert again["id"] != v["id"] and again["private_sale"] == v["private_sale"]


@pytest.mark.parametrize("change, status, code", [
    ({"region": "XX"}, 422, "unsupported_region"),
    ({"currency": "USD"}, 422, "unsupported_currency"),
    ({"condition": {"grade": "mint", "faults": []}}, 422, "validation_error"),
    ({"device": {"storage_gb": 128}}, 422, "validation_error"),
    ({"device": {"manufacturer": "Nokia", "model": "3310"}}, 404, "unsupported_model"),
    ({"device": {"product_id": "samsung-galaxy-s21"}}, 404, "no_data_for_condition"),
    ({"surprise": 1}, 422, "validation_error"),
])
def test_valuation_validation(client, headers, change, status, code):
    body = {**VALUATION, **change}
    r = client.post("/api/v1/valuations", json=body, headers={"X-API-Key": headers["X-API-Key"]})
    assert (r.status_code, r.json()["error"]["code"]) == (status, code), r.text


def test_valuation_with_no_price_data_is_unavailable_not_invented(client, headers):
    body = {"device": {"product_id": "google-pixel-8", "storage_gb": 128}, "region": "IN", "currency": "INR",
            "condition": {"grade": "good", "faults": []}}
    v = client.post("/api/v1/valuations", json=body, headers={"X-API-Key": headers["X-API-Key"]}).json()
    assert v["status"] == "unavailable" and v["confidence"] == "insufficient"
    for kind in ("private_sale", "buyback", "refurbished_retail", "original_retail"):
        assert v[kind]["available"] is False and v[kind]["value"] is None and v[kind]["reason"]


def test_market_prices_with_unconfigured_adapters(client, headers):
    h = {"X-API-Key": headers["X-API-Key"]}
    r = client.get("/api/v1/market-prices?product_id=samsung-galaxy-s21&storage_gb=128", headers=h).json()
    states = {p["id"]: p["state"] for p in r["providers"]}
    assert states == {"flipkart-affiliate": "not_configured", "amazon-creators-in": "not_configured",
                      "cashify-manual": "manual_only"}
    assert r["mock_data_included"] is True and r["summary"]["new"]["lowest"] == 41990.0
    new = r["groups"]["new"]
    assert new[-1]["availability"] == "out_of_stock"  # sorted last regardless of price
    assert all(o["match"]["category"] in ("exact", "strong") and o["storage_gb"] == 128 for o in new)
    assert {o["match"]["category"] for o in r["alternatives"]} == {"variant_mismatch", "similar"}

    nothing = client.get("/api/v1/market-prices?product_id=google-pixel-8&storage_gb=128", headers=h).json()
    assert nothing["summary"]["new"]["count"] == 0 and nothing["groups"]["new"] == []
    assert client.get("/api/v1/market-prices?product_id=samsung-galaxy-s21", headers=h).json()["error"]["code"] \
        == "variant_required"


def test_production_excludes_fixture_offers(make_client, seeded_db, monkeypatch, headers):
    client = make_client(environment="production", hash_salt="s" * 32, allow_sqlite_in_production=True)
    r = client.get("/api/v1/market-prices?product_id=samsung-galaxy-s21&storage_gb=128",
                   headers={"X-API-Key": headers["X-API-Key"]}).json()
    assert r["groups"]["new"] == [] and r["mock_data_included"] is False


def test_price_history_endpoint(client, headers):
    r = client.get("/api/v1/price-history?product_id=samsung-galaxy-s21&storage_gb=128&condition=new",
                   headers={"X-API-Key": headers["X-API-Key"]}).json()
    assert r["available"] and r["observed_days"] == 4 and r["mock_data_included"]
    assert r["change"]["amount"] == -1000.0  # 42990 three days earlier -> 41990 today (fixture)
    assert r["resale_trend"] == {}  # synthetic data is never shown as history


def test_products(client, headers):
    h = {"X-API-Key": headers["X-API-Key"]}
    assert [p["id"] for p in client.get("/api/v1/products?q=pixel", headers=h).json()] == [
        "google-pixel-6a", "google-pixel-7", "google-pixel-7a", "google-pixel-8", "google-pixel-8a", "google-pixel-9"]
    p = client.get("/api/v1/products/apple-iphone-13", headers=h).json()
    assert p["storage_gb"] == [128, 256, 512]
    assert client.get("/api/v1/products/nope", headers=h).json()["error"]["code"] == "unsupported_model"


# --- watchlist -------------------------------------------------------------------------------------------------


def test_watchlist_and_alerts(dev, make_client):
    r = dev.post("/api/account/watchlist", json={"model_id": "samsung-galaxy-s21", "storage_gb": 128,
                                                 "condition": "new", "target_price": "40000"}, headers=WEB)
    assert r.status_code == 201
    item = r.json()
    assert item["lowest_current_price"] == 41990.0 and item["unread_alerts"] == 0
    dup = dev.post("/api/account/watchlist", json={"model_id": "samsung-galaxy-s21", "storage_gb": 128,
                                                   "condition": "new"}, headers=WEB)
    assert dup.status_code == 409
    assert dev.post("/api/account/watchlist", json={"model_id": "samsung-galaxy-s21", "storage_gb": 64,
                                                    "condition": "new"}, headers=WEB).status_code == 422
    assert dev.get("/api/account/alerts").json() == []  # nothing observed at or below the target

    other = make_client()
    signup(other, "other@example.com")
    assert other.get("/api/account/watchlist").json() == []
    assert other.delete(f"/api/account/watchlist/{item['id']}", headers=WEB).status_code == 404
    assert dev.delete(f"/api/account/watchlist/{item['id']}", headers=WEB).status_code == 204


def test_public_valuation_includes_value_types(client):
    from test_condition_decision import GOOD

    r = client.post("/api/valuations", json={"device": {"model_id": "samsung-galaxy-s21", "storage_gb": 128},
                                             "region": "IN", "currency": "INR", "assessment": GOOD}).json()
    types = r["value_types"]
    assert types["refurbished_retail"]["available"] and types["buyback"]["available"] is False


def test_admin_marketplace_endpoints(client, admin_headers, headers):
    q = client.get("/admin/api/data-quality", headers=admin_headers).json()
    assert q["offers"]["total_rows"] > 0 and "strong" in q["match_categories"]
    assert {p["id"] for p in q["providers"]} == {"flipkart-affiliate", "amazon-creators-in", "cashify-manual"}
    runs = client.post("/admin/api/offers/refresh", json={"model_id": "samsung-galaxy-s21"}, headers=admin_headers)
    assert {r["status"] for r in runs.json()} == {"not_configured"}  # nothing is fetched without credentials
    assert client.get("/admin/api/data-quality", headers={"X-API-Key": headers["X-API-Key"]}).status_code == 401

    client.post("/admin/api/sources", headers=admin_headers, json={
        "id": "shop-quotes", "name": "Shop quotes", "source_type": "dealer_offer", "collection_method": "manual",
        "markets": "IN", "terms_note": "quotes recorded with consent", "verified": False})
    csv_text = ("title,brand,storage_gb,condition,price_type,price,mrp,currency,url,seller,seller_type,availability,"
                "retrieved_at,external_ref\n"
                "Samsung Galaxy S21 128 GB,Samsung,128,used,buyback_quote,15000,,INR,,Shop,dealer,,2026-09-30,q1\n")
    job = client.post("/admin/api/offer-imports", headers=admin_headers,
                      json={"source_id": "shop-quotes", "region": "IN", "csv_text": csv_text}).json()
    assert (job["status"], job["accepted"]) == ("succeeded", 1)
    assert client.post("/admin/api/offer-imports", headers=admin_headers, json={
        "source_id": "fixture-offers", "region": "IN", "csv_text": csv_text}).status_code == 422


# --- FixMyTech: keyed endpoints return the same JSON as the public ones ------------------------------------------

S21 = {"product_id": "samsung-galaxy-s21", "storage_gb": 128, "region": "IN"}
DECISION = {"currency": "INR", "as_is_value": 15000, "after_repair_value": 20000, "repair_cost": 3000,
            "repair_cost_basis": "user_supplied", "selling_fee_pct": 5, "selling_fixed_cost": 0}


def _without(data: dict, *keys: str) -> dict:
    return {k: v for k, v in data.items() if k not in keys}


def test_fixmytech_keyed_endpoints_match_public(client, headers):
    h = {"X-API-Key": headers["X-API-Key"]}  # an environment partner key, as FixMyTech uses
    public = client.get("/api/trends", params={"model_id": S21["product_id"], "storage_gb": 128, "region": "IN",
                                                "grade": "good"}).json()
    for id_param in ("product_id", "model_id"):
        keyed = client.get("/api/v1/trends", headers=h, params={id_param: S21["product_id"], "storage_gb": 128,
                                                                  "region": "IN", "grade": "good"})
        assert keyed.status_code == 200 and keyed.json() == public

    public = client.post("/api/decision", json=DECISION).json()
    assert client.post("/api/v1/decision", json=DECISION, headers=h).json() == public

    catalogue = client.get("/api/catalogue", params={"q": "galaxy"}).json()
    products = client.get("/api/v1/products", params={"q": "galaxy"}, headers=h).json()
    assert [_without(p, "model_codes", "regions") for p in products] == catalogue
    assert products[0]["evidence"] and isinstance(products[0]["oem_codes"], list)

    public = client.get("/api/market/offers", params={"model_id": S21["product_id"], "storage_gb": 128}).json()
    keyed = client.get("/api/v1/market-prices", params=S21, headers=h).json()
    assert _without(keyed, "generated_at") == _without(public, "generated_at")
    assert set(keyed["groups"]) == {"new", "refurbished", "used", "buyback"}
    assert all(o["is_mock"] for items in keyed["groups"].values() for o in items)  # seeded fixtures are labelled


def test_fixmytech_errors_scopes_and_codes(dev, headers):
    h = {"X-API-Key": headers["X-API-Key"]}
    r = dev.get("/api/v1/trends", params={"product_id": "nokia-3310", "region": "IN"}, headers=h)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "unsupported_model")
    sparse = dev.get("/api/v1/trends", params={**S21, "grade": "excellent"}, headers=h).json()
    assert sparse["available"] is False and sparse["reason"] and sparse["series"] == {}
    assert dev.get("/api/v1/trends", params=S21, headers={"X-API-Key": "fv_wrong"}).status_code == 401

    narrow = {"X-API-Key": new_key(dev, ["market_prices:read"])["key"]}
    for r in (dev.get("/api/v1/trends", params=S21, headers=narrow),
              dev.post("/api/v1/decision", json=DECISION, headers=narrow)):
        assert (r.status_code, r.json()["error"]["code"]) == (403, "insufficient_scope")

    # Phones report OEM codes with suffixes; the catalogue lists SM-S901E only.
    assert [p["id"] for p in dev.get("/api/v1/products", params={"q": "SM-S901E/DS"}, headers=h).json()] == \
        ["samsung-galaxy-s22"]
    body = {**VALUATION, "device": {"manufacturer": "Samsung", "model": "SM-S901E/DS", "storage_gb": 128}}
    r = dev.post("/v1/valuations", json=body, headers=headers)
    assert r.json()["error"]["code"] != "unsupported_model"  # matched; this test database has no S22 prices
