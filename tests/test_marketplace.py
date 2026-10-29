"""Marketplace adapters, product matching, offer storage, comparison, history, alerts and data quality.

Provider responses here are deterministic FIXTURES shaped like the documented APIs (served by httpx.MockTransport);
no real marketplace was called.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select

from conftest import NOW
from flipvalue.db.models import Account, DeviceModel, MarketplaceOffer, PriceAlert, RejectedRecord, WatchlistItem
from flipvalue.ingestion.sources import SourceSpec, register_source
from flipvalue.marketplace import service
from flipvalue.marketplace.matching import match_listing, storage_from_title
from flipvalue.marketplace.providers import (
    AmazonCreators,
    CashifyManual,
    FlipkartAffiliate,
    ProviderError,
    ProviderResult,
    RawOffer,
    call_with_retries,
)

POLICY = service.OfferPolicy(clock=lambda: NOW)


@pytest.fixture
def session(catalogue_db, session_for):
    s = session_for(catalogue_db)
    yield s
    s.rollback()


def flipkart_item(pid: str, title: str, price: int | None, mrp: int | None = None, in_stock: bool | None = True,
                  storage: str | None = None) -> dict:
    base = {"productId": pid, "title": title, "productBrand": title.split()[0].title(),
            "productUrl": f"https://dl.flipkart.com/dl/x/p/{pid}?affid=test",
            "flipkartSellingPrice": {"amount": price, "currency": "INR"},
            "attributes": {"storage": storage or "", "color": "Gray"}}
    if mrp:
        base["maximumRetailPrice"] = {"amount": mrp, "currency": "INR"}
    if in_stock is not None:
        base["inStock"] = in_stock
    return {"productBaseInfoV1": base, "productShippingInfoV1": {"sellerName": "RetailNet",
                                                                 "shippingCharges": {"amount": 0}}}


def flipkart(handler, **kw) -> FlipkartAffiliate:
    return FlipkartAffiliate("aff-id", "aff-token", client=httpx.Client(transport=httpx.MockTransport(handler)),
                             sleep=lambda _: None, **kw)


# --- adapters --------------------------------------------------------------------------------------------------


def test_flipkart_success_maps_documented_fields_and_sends_credentials_as_headers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers, url=str(request.url))
        return httpx.Response(200, json={"productInfoList": [
            flipkart_item("MOBG1", "SAMSUNG Galaxy S21 5G (Phantom Gray, 128 GB)", 41990, 69999, True, "128 GB"),
            flipkart_item("MOBG2", "SAMSUNG Galaxy S21 5G (Phantom White, 128 GB)", None),
        ]})

    result = flipkart(handler).search("Samsung Galaxy S21 128 GB", "IN")

    assert seen["fk-affiliate-id"] == "aff-id" and seen["fk-affiliate-token"] == "aff-token"
    assert "resultCount=10" in seen["url"] and "aff-token" not in seen["url"]
    [offer] = result.offers
    assert (offer.price, offer.mrp, offer.currency, offer.storage_gb) == (Decimal("41990"), Decimal("69999"), "INR",
                                                                           128)
    assert (offer.availability, offer.seller, offer.condition, offer.price_type) == (
        "in_stock", "RetailNet", "new", "new_retail")
    assert result.rejected == [("MOBG2", "malformed product: no selling price")]


def test_flipkart_empty_results():
    result = flipkart(lambda r: httpx.Response(200, json={"productInfoList": []})).search("nothing", "IN")
    assert result.offers == [] and result.rejected == []


@pytest.mark.parametrize("response, code", [
    (httpx.Response(200, text="<html>not json</html>"), "malformed"),
    (httpx.Response(200, json={"products": []}), "malformed"),
    (httpx.Response(401, json={}), "unauthorized"),
    (httpx.Response(500, json={}), "http_error"),
])
def test_flipkart_errors_are_classified(response, code):
    with pytest.raises(ProviderError) as exc:
        flipkart(lambda r: response).search("x", "IN")
    assert exc.value.code == code


def test_timeouts_and_429_are_retried_a_bounded_number_of_times():
    calls = []

    def timeout(request):
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderError) as exc:
        flipkart(timeout).search("x", "IN")
    assert exc.value.code == "timeout" and len(calls) == 3  # 1 + 2 retries

    waits = []
    responses = iter([httpx.Response(429, headers={"Retry-After": "60"}), httpx.Response(200, text="ok")])
    response = call_with_retries(lambda: next(responses), waits.append)
    assert response.status_code == 200 and waits == [5.0]  # Retry-After capped at 5 s

    with pytest.raises(ProviderError) as exc:
        flipkart(lambda r: httpx.Response(429)).search("x", "IN")
    assert exc.value.code == "rate_limited"


def test_missing_credentials_never_call_the_network():
    def fail(request):  # pragma: no cover - must not be reached
        raise AssertionError("network called")

    for provider in (FlipkartAffiliate("", "", client=httpx.Client(transport=httpx.MockTransport(fail))),
                     AmazonCreators("", "", "", "", client=httpx.Client(transport=httpx.MockTransport(fail))),
                     CashifyManual()):
        assert not provider.configured()
        with pytest.raises(ProviderError) as exc:
            provider.search("x", "IN")
        assert exc.value.code == "not_configured" and "FLIPVALUE_" in provider.requirement() or \
            "Cashify" in provider.requirement()


def test_amazon_gets_a_token_then_parses_offers_v2():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/auth/o2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer tok"
        assert request.headers["x-marketplace"] == "www.amazon.in"
        return httpx.Response(200, json={"searchResult": {"items": [
            {"asin": "B0TEST", "detailPageURL": "https://www.amazon.in/dp/B0TEST?tag=t-21",
             "itemInfo": {"title": {"displayValue": "Samsung Galaxy S21 5G (Phantom Gray, 8GB, 128GB Storage)"},
                          "byLineInfo": {"brand": {"displayValue": "Samsung"}}},
             "offersV2": {"listings": [{"price": {"money": {"amount": 42500, "currency": "INR"}},
                                        "availability": {"type": "IN_STOCK"}, "condition": {"value": "New"},
                                        "merchantInfo": {"name": "Appario"}}]}},
            {"asin": "B0BAD", "itemInfo": {"title": {"displayValue": "No offers"}}},
        ]}})

    provider = AmazonCreators("cid", "secret", "tag-21", "https://api.amazon.co.uk/auth/o2/token",
                              client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None)
    result = provider.search("Samsung Galaxy S21", "IN")
    provider.search("again", "IN")

    assert [r.url.path for r in requests].count("/auth/o2/token") == 1  # token cached
    [offer] = result.offers
    assert (offer.price, offer.seller, offer.availability, offer.provider_product_id) == (
        Decimal("42500"), "Appario", "in_stock", "B0TEST")
    assert offer.mrp is None  # Amazon's "saving basis" is not an MRP; nothing is inferred
    assert result.rejected[0][0] == "B0BAD"


# --- matching --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("title, storage, category", [
    ("SAMSUNG Galaxy S21 5G (Phantom Gray, 128 GB)", None, "strong"),
    ("Samsung Galaxy S21 SM-G991B 128GB", None, "exact"),
    ("SAMSUNG Galaxy S21 5G (Phantom Gray, 256 GB)", None, "variant_mismatch"),
    ("SAMSUNG Galaxy S21 5G (Phantom Gray)", None, "variant_unknown"),
    ("SAMSUNG Galaxy S21 FE 5G (Graphite, 128 GB)", None, "similar"),
    ("SAMSUNG Galaxy S21 Ultra (Black, 128 GB)", None, "similar"),
    ("SAMSUNG Galaxy S21+ 5G (128 GB)", None, "similar"),
    ("Apple iPhone 13 (128 GB)", None, "unmatched"),
    ("SAMSUNG Galaxy S21 5G", 128, "strong"),
])
def test_matching_for_galaxy_s21_128(session, title, storage, category):
    target = session.get(DeviceModel, "samsung-galaxy-s21")
    m = match_listing(session, title, None, storage, target, 128)
    assert m.category == category, m.reasons
    assert m.reasons


def test_matching_single_variant_model_and_ram_is_not_storage(session):
    m = match_listing(session, "Google Pixel 6a (Chalk)", "Google", None)
    assert (m.model_id, m.category, m.storage_gb) == ("google-pixel-6a", "strong", 128)
    assert storage_from_title("Pixel 7 (12 GB RAM, 256 GB)") == 256
    assert match_listing(session, "Google Pixel 7 Pro (128 GB)", "Google", None).category == "similar"
    m = match_listing(session, "Google Pixel 7a (128 GB)", "Google", None)  # a catalogued variant is its own model
    assert (m.model_id, m.category) == ("google-pixel-7a", "strong")


# --- storing, refresh isolation, comparison --------------------------------------------------------------------


class Stub:
    """A provider double: fixed offers or a fixed failure."""

    automated = True

    def __init__(self, sid: str, offers=(), error: ProviderError | None = None, configured=True):
        self.spec = SourceSpec(id=sid, name=sid, source_type="new_retail", collection_method="test", markets="IN",
                               terms_note="test fixture", verified=True)
        self._offers, self._error, self._configured = list(offers), error, configured
        self.calls = 0

    def configured(self):
        return self._configured

    def requirement(self):
        return "credentials"

    def search(self, query, region):
        self.calls += 1
        if self._error:
            raise self._error
        return ProviderResult(offers=list(self._offers))


def offer(title, price, condition="new", **kw) -> RawOffer:
    return RawOffer(title=title, price=Decimal(price), currency="INR", condition=condition,
                    price_type={"new": "new_retail", "refurbished": "refurbished_retail"}[condition],
                    provider_product_id=kw.pop("pid", title), url=kw.pop("url", "https://example.com/p"), **kw)


def test_one_failing_provider_does_not_block_the_others(session):
    model = session.get(DeviceModel, "samsung-galaxy-s21")
    good = Stub("good", [offer("Samsung Galaxy S21 5G (128 GB)", 41000), offer("Samsung Galaxy S21 (256 GB)", 45000),
                         offer("Samsung Galaxy S21 FE (128 GB)", 30000), offer("Apple iPhone 13 128 GB", 50000)])
    broken = Stub("broken", error=ProviderError("timeout", "slow"))
    absent = Stub("absent", configured=False)

    runs = {r.source_id: r for r in service.refresh(session, [broken, good, absent], model, 128, "IN", "test", POLICY,
                                                    NOW)}

    assert (runs["broken"].status, runs["broken"].error_code) == ("failed", "timeout")
    assert runs["absent"].status == "not_configured" and absent.calls == 0
    assert (runs["good"].status, runs["good"].accepted, runs["good"].rejected) == ("succeeded", 3, 1)
    rejected = session.scalars(select(RejectedRecord.reason)).all()
    assert any(r.startswith("unrelated product") for r in rejected)

    result = service.compare(session, model, 128, "IN", POLICY, NOW)
    assert [o["price"] for o in result["groups"]["new"]] == [41000.0]
    assert {o["match"]["category"] for o in result["alternatives"]} == {"variant_mismatch", "similar"}

    # a second refresh inside the minimum interval does not call the provider again
    again = service.refresh(session, [good], model, 128, "IN", "test", POLICY, NOW + timedelta(minutes=5))
    assert again[0].status == "skipped_recent" and good.calls == 1


def test_validation_and_duplicates(session):
    model = session.get(DeviceModel, "samsung-galaxy-s21")
    dup = offer("Samsung Galaxy S21 (128 GB)", 41000)
    provider = Stub("p", [dup, dup, offer("Samsung Galaxy S21 (128 GB)", 0), offer("Samsung Galaxy S21 (128 GB)", 41000,
                                                                                   pid="other", url="http://insecure"),
                          RawOffer(title="Samsung Galaxy S21 (128 GB)", price=Decimal(400), currency="USD",
                                   condition="new", price_type="new_retail")])
    [run] = service.refresh(session, [provider], model, 128, "IN", "test", POLICY, NOW)
    assert (run.accepted, run.duplicates, run.rejected) == (1, 1, 3)
    reasons = " | ".join(session.scalars(select(RejectedRecord.reason)))
    assert "price must be > 0" in reasons and "https" in reasons and "currency USD" in reasons


def test_freshness_stale_and_expired(session):
    model = session.get(DeviceModel, "samsung-galaxy-s21")
    service.refresh(session, [Stub("p", [offer("Samsung Galaxy S21 (128 GB)", 41000)])], model, 128, "IN", "t",
                    POLICY, NOW - timedelta(days=3))
    [item] = service.compare(session, model, 128, "IN", POLICY, NOW)["groups"]["new"]
    assert item["freshness"] == "stale"
    assert service.compare(session, model, 128, "IN", POLICY, NOW + timedelta(days=20))["groups"]["new"] == []


def test_history_needs_two_days_and_reports_gaps(session):
    model = session.get(DeviceModel, "samsung-galaxy-s21")
    provider = Stub("p", [offer("Samsung Galaxy S21 (128 GB)", 44000)])
    service.refresh(session, [provider], model, 128, "IN", "t", POLICY, NOW - timedelta(days=5))
    one = service.history(session, model, 128, "IN", "new", 90, POLICY, NOW)
    assert not one["available"] and one["observation_count"] == 1 and "two different days" in one["reason"]

    provider._offers = [offer("Samsung Galaxy S21 (128 GB)", 42000)]
    service.refresh(session, [provider], model, 128, "IN", "t", POLICY, NOW)
    two = service.history(session, model, 128, "IN", "new", 90, POLICY, NOW)
    assert two["available"] and two["change"]["amount"] == -2000.0 and two["change"]["pct"] == -4.5
    assert two["gaps"] == [{"from": (NOW - timedelta(days=5)).date().isoformat(), "to": NOW.date().isoformat(),
                            "days": 4}]
    assert two["lowest"]["price"] == 42000.0 and two["highest"]["price"] == 44000.0

    empty = service.history(session, session.get(DeviceModel, "google-pixel-8"), 128, "IN", "new", 90, POLICY, NOW)
    assert not empty["available"] and empty["series"] == {} and "No price" in empty["reason"]


def test_alerts_only_for_actually_observed_qualifying_prices(session):
    model = session.get(DeviceModel, "samsung-galaxy-s21")
    account = Account(email="a@example.com", password_hash="x")
    session.add(account)
    session.flush()
    watch = WatchlistItem(account_id=account.id, model_id=model.id, storage_gb=128, region="IN", condition="new",
                          target_price=Decimal("40000"))
    session.add(watch)
    session.flush()
    provider = Stub("p", [offer("Samsung Galaxy S21 (128 GB)", 41000), offer("Samsung Galaxy S21 (256 GB)", 39000)])
    service.refresh(session, [provider], model, None, "IN", "t", POLICY, NOW)
    assert session.scalar(select(func.count(PriceAlert.id))) == 0  # above target / wrong variant

    provider._offers = [offer("Samsung Galaxy S21 (128 GB)", 39500), offer("Samsung Galaxy S21 (128 GB)", 39900,
                                                                          pid="b")]
    service.refresh(session, [provider], model, None, "IN", "t", POLICY, NOW + timedelta(hours=2))
    alerts = session.scalars(select(PriceAlert)).all()
    assert [a.price for a in alerts] == [Decimal("39500")]  # the dearer one does not alert again


def test_curated_csv_import_and_data_quality(session):
    source = register_source(session, SourceSpec(id="cashify-manual", name="Cashify quotes", source_type="dealer_offer",
                                                 collection_method="manual", markets="IN", terms_note="manual",
                                                 verified=False))
    header = ",".join(service.OFFER_COLUMNS)
    text = (f"{header}\n"
            "Samsung Galaxy S21 128 GB,Samsung,128,used,buyback_quote,15000,,INR,https://www.cashify.in/x,Cashify,"
            "dealer,,2026-09-30,q1\n"
            "Samsung Galaxy S21 128 GB,Samsung,128,used,buyback_quote,abc,,INR,,Cashify,dealer,,2026-09-30,q2\n"
            "Samsung Galaxy S21 128 GB,Samsung,128,broken,buyback_quote,1,,INR,,Cashify,dealer,,2026-09-30,q3\n")
    job = service.import_offers_csv(session, source, text, "IN", "test")
    assert (job.status, job.accepted, job.rejected) == ("succeeded", 1, 2)
    model = session.get(DeviceModel, "samsung-galaxy-s21")
    result = service.compare(session, model, 128, "IN", POLICY, NOW)
    assert [o["price"] for o in result["groups"]["buyback"]] == [15000.0]

    bad = service.import_offers_csv(session, source, "a,b\n1,2\n", "IN", "test")
    assert bad.status == "failed" and "header" in bad.message

    report = service.data_quality(session, [CashifyManual()], POLICY, NOW)
    assert report["retrievals_by_source"]["cashify-manual"]["failed"] == 1
    assert report["offers"]["total_rows"] == 1 and report["match_categories"] == {"strong": 1}
    assert report["providers"][0]["state"] == "manual_only"
    assert {"id": "cashify-manual", "missing": ["url", "not verified"]} in report["sources_missing_metadata"]


def test_fixture_offers_are_mock_and_have_no_links(seeded_db, session_for):
    s = session_for(seeded_db)
    offers = s.scalars(select(MarketplaceOffer)).all()
    assert offers and all(o.is_mock and o.url is None for o in offers)
    assert datetime(2026, 9, 1) < max(o.retrieved_at for o in offers) <= NOW
