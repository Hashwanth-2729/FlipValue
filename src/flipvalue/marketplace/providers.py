"""Marketplace provider adapters. Each one searches an authorised source and returns RawOffers.

Adapters never scrape: they call documented APIs with the operator's own credentials, or (Cashify) report that no
authorised automated access exists. Credentials stay on the server. One failing provider never stops the others
(service.refresh runs each separately). See docs/DATA_SOURCES.md for access requirements.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx

from flipvalue.ingestion.sources import SourceSpec

MAX_RETRIES = 2
MAX_RETRY_AFTER_S = 5.0
RETRYABLE_STATUS = (429, 502, 503, 504)


class ProviderError(Exception):
    """A provider call that produced no usable result. `code` is shown to operators and in provider status."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code  # not_configured | timeout | rate_limited | unauthorized | http_error | malformed
        self.message = message


@dataclass
class RawOffer:
    """One offer as the provider reported it, mapped to FlipValue fields. Nothing is guessed: unknown = None."""

    title: str
    price: Decimal
    currency: str
    condition: str                     # new | refurbished | used
    price_type: str                    # new_retail | refurbished_retail | used_listing | buyback_quote
    provider_product_id: str | None = None
    brand: str | None = None
    mrp: Decimal | None = None
    url: str | None = None
    seller: str | None = None
    seller_type: str | None = None     # marketplace_seller | retailer | manufacturer | refurbisher | dealer
    availability: str | None = None    # in_stock | out_of_stock
    storage_gb: int | None = None
    ram_gb: int | None = None
    color: str | None = None
    delivery_note: str | None = None
    published_at: datetime | None = None
    raw: dict[str, Any] | None = None


@dataclass
class ProviderResult:
    offers: list[RawOffer] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (raw reference, reason)


class Provider(Protocol):
    spec: SourceSpec
    automated: bool  # False: the source has no authorised automated access

    def configured(self) -> bool: ...

    def requirement(self) -> str:
        """What is needed to enable this provider (shown when it is not configured)."""
        ...

    def search(self, query: str, region: str) -> ProviderResult: ...


def money(value: Any) -> Decimal | None:
    """A positive amount from a provider number or string, else None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount > 0 else None


def condition_from_title(title: str) -> str:
    lowered = title.casefold()
    if any(word in lowered for word in ("refurbished", "renewed", "certified pre-owned")):
        return "refurbished"
    if "pre-owned" in lowered or "(used)" in lowered:
        return "used"
    return "new"


PRICE_TYPE = {"new": "new_retail", "refurbished": "refurbished_retail", "used": "used_listing"}


def call_with_retries(send: Callable[[], httpx.Response], sleep: Callable[[float], None] = time.sleep,
                      max_retries: int = MAX_RETRIES) -> httpx.Response:
    """Bounded retries for timeouts, connection errors and 429/502/503/504 (Retry-After honoured up to 5 s)."""
    attempt = 0
    while True:
        try:
            response = send()
        except httpx.TimeoutException as exc:
            if attempt >= max_retries:
                raise ProviderError("timeout", "The provider did not answer in time.") from exc
            wait = 0.5 * 2 ** attempt
        except httpx.TransportError as exc:
            if attempt >= max_retries:
                raise ProviderError("http_error", f"Could not connect to the provider ({type(exc).__name__}).") \
                    from exc
            wait = 0.5 * 2 ** attempt
        else:
            if response.status_code not in RETRYABLE_STATUS:
                return response
            if attempt >= max_retries:
                if response.status_code == 429:
                    raise ProviderError("rate_limited", "The provider's rate limit was reached.")
                raise ProviderError("http_error", f"The provider answered HTTP {response.status_code}.")
            try:
                wait = min(MAX_RETRY_AFTER_S, float(response.headers.get("retry-after", "")))
            except ValueError:
                wait = 0.5 * 2 ** attempt
        sleep(wait)
        attempt += 1


def _check_status(response: httpx.Response) -> None:
    if response.status_code in (401, 403):
        raise ProviderError("unauthorized", f"The provider refused the credentials (HTTP {response.status_code}).")
    if response.status_code >= 400:
        raise ProviderError("http_error", f"The provider answered HTTP {response.status_code}.")


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError("malformed", "The provider's response is not valid JSON.") from exc


# --- Flipkart Affiliate API ------------------------------------------------------------------------------------


FLIPKART = SourceSpec(
    id="flipkart-affiliate",
    name="Flipkart (Affiliate API)",
    source_type="new_retail",
    collection_method="Flipkart Affiliate API 1.0 keyword search "
                      "(affiliate-api.flipkart.net/affiliate/1.0/search.json)",
    markets="IN",
    terms_note="Flipkart Affiliate Program API terms; requires a registered affiliate's tracking id and API token. "
               "Prices are Flipkart's at retrieval time; links carry the affiliate id.",
    verified=True,
    url="https://affiliate.flipkart.com/api-docs/af_overview.html",
)


class FlipkartAffiliate:
    """GET /affiliate/1.0/search.json?query=&resultCount=<=10 with Fk-Affiliate-Id / Fk-Affiliate-Token headers.

    Response (documented): productInfoList[] -> productBaseInfoV1 {productId, title, productBrand, productUrl,
    maximumRetailPrice, flipkartSellingPrice, flipkartSpecialPrice {amount, currency}, inStock, attributes {color,
    storage}} and productShippingInfoV1 {shippingCharges, sellerName}.
    """

    spec = FLIPKART
    automated = True
    BASE_URL = "https://affiliate-api.flipkart.net/affiliate/1.0/search.json"

    def __init__(self, affiliate_id: str, token: str, *, client: httpx.Client | None = None,
                 timeout_s: float = 8.0, sleep: Callable[[float], None] = time.sleep) -> None:
        self._id, self._token = affiliate_id, token
        self._client = client or httpx.Client(timeout=timeout_s)
        self._sleep = sleep

    def configured(self) -> bool:
        return bool(self._id and self._token)

    def requirement(self) -> str:
        return "Set FLIPVALUE_FLIPKART_AFFILIATE_ID and FLIPVALUE_FLIPKART_AFFILIATE_TOKEN (Flipkart Affiliate " \
               "Program account → API token)."

    def search(self, query: str, region: str) -> ProviderResult:
        if not self.configured():
            raise ProviderError("not_configured", self.requirement())
        if region != "IN":
            return ProviderResult()
        response = call_with_retries(lambda: self._client.get(
            self.BASE_URL, params={"query": query, "resultCount": 10},
            headers={"Fk-Affiliate-Id": self._id, "Fk-Affiliate-Token": self._token}), self._sleep)
        _check_status(response)
        payload = _json(response)
        items = payload.get("productInfoList") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ProviderError("malformed", "The response has no productInfoList.")
        result = ProviderResult()
        for item in items:
            try:
                result.offers.append(self._offer(item))
            except (KeyError, TypeError, ValueError) as exc:
                ref = str((item or {}).get("productBaseInfoV1", {}).get("productId", "?")) \
                    if isinstance(item, dict) else "?"
                result.rejected.append((ref, f"malformed product: {exc}"[:300]))
        return result

    @staticmethod
    def _offer(item: dict[str, Any]) -> RawOffer:
        base = item["productBaseInfoV1"]
        shipping = item.get("productShippingInfoV1") or {}
        special, selling = base.get("flipkartSpecialPrice") or {}, base.get("flipkartSellingPrice") or {}
        chosen = special if money(special.get("amount")) else selling
        price = money(chosen.get("amount"))
        if price is None:
            raise ValueError("no selling price")
        title = str(base["title"]).strip()
        attributes = base.get("attributes") or {}
        in_stock = base.get("inStock")
        charge = money((shipping.get("shippingCharges") or {}).get("amount"))
        condition = condition_from_title(title)
        return RawOffer(
            title=title, price=price, currency=str(chosen.get("currency") or ""), condition=condition,
            price_type=PRICE_TYPE[condition], provider_product_id=str(base.get("productId") or "") or None,
            brand=base.get("productBrand") or None, mrp=money((base.get("maximumRetailPrice") or {}).get("amount")),
            url=base.get("productUrl") or None, seller=shipping.get("sellerName") or None,
            seller_type="marketplace_seller" if shipping.get("sellerName") else None,
            availability=None if in_stock is None else ("in_stock" if in_stock else "out_of_stock"),
            storage_gb=_gb(attributes.get("storage")), color=attributes.get("color") or None,
            delivery_note=f"Shipping charge {charge} INR" if charge else None,
            raw=item,
        )


def _gb(value: Any) -> int | None:
    if not value:
        return None
    text = str(value).upper().replace(" ", "")
    for unit, factor in (("TB", 1024), ("GB", 1)):
        if text.endswith(unit) and text[: -len(unit)].isdigit():
            return int(text[: -len(unit)]) * factor
    return None


# --- Amazon Creators API (successor of PA-API 5) ---------------------------------------------------------------


AMAZON = SourceSpec(
    id="amazon-creators-in",
    name="Amazon.in (Creators API)",
    source_type="new_retail",
    collection_method="Amazon Creators API catalog/v1/searchItems, marketplace www.amazon.in, OffersV2 resources",
    markets="IN",
    terms_note="Amazon Associates Operating Agreement and Creators API terms; requires an approved Associates "
               "account (partner tag) and Creators API credentials. PA-API 5 was retired on 2026-04-30.",
    verified=True,
    url="https://affiliate-program.amazon.in/creatorsapi/docs/en-us/migrating-to-creatorsapi-from-paapi",
)


class AmazonCreators:
    """OAuth2 client-credentials token, then POST https://creatorsapi.amazon/catalog/v1/searchItems.

    NOT verified against a live account: the token endpoint depends on the credential version Amazon assigns, so
    it is configuration (FLIPVALUE_AMAZON_TOKEN_URL). Response parsing follows the documented OffersV2 resource
    names (offersV2.listings[].price.money.amount) and rejects items that do not have them.
    """

    spec = AMAZON
    automated = True
    API_URL = "https://creatorsapi.amazon/catalog/v1/searchItems"
    MARKETPLACE = "www.amazon.in"
    RESOURCES = ["itemInfo.title", "itemInfo.byLineInfo", "offersV2.listings.price", "offersV2.listings.availability",
                 "offersV2.listings.condition", "offersV2.listings.merchantInfo"]

    def __init__(self, credential_id: str, credential_secret: str, partner_tag: str, token_url: str, *,
                 client: httpx.Client | None = None, timeout_s: float = 8.0,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time) -> None:
        self._cid, self._secret, self._tag, self._token_url = credential_id, credential_secret, partner_tag, token_url
        self._client = client or httpx.Client(timeout=timeout_s)
        self._sleep, self._clock = sleep, clock
        self._token: tuple[str, float] | None = None

    def configured(self) -> bool:
        return bool(self._cid and self._secret and self._tag and self._token_url)

    def requirement(self) -> str:
        return "Set FLIPVALUE_AMAZON_CREDENTIAL_ID, FLIPVALUE_AMAZON_CREDENTIAL_SECRET, FLIPVALUE_AMAZON_PARTNER_TAG " \
               "and FLIPVALUE_AMAZON_TOKEN_URL (approved Amazon.in Associates account with Creators API access)."

    def _access_token(self) -> str:
        if self._token and self._token[1] > self._clock() + 30:
            return self._token[0]
        response = call_with_retries(lambda: self._client.post(self._token_url, data={
            "grant_type": "client_credentials", "client_id": self._cid, "client_secret": self._secret,
            "scope": "creatorsapi::default"}), self._sleep)
        _check_status(response)
        payload = _json(response)
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str):
            raise ProviderError("malformed", "The token response has no access_token.")
        self._token = (token, self._clock() + float(payload.get("expires_in", 3600)))
        return token

    def search(self, query: str, region: str) -> ProviderResult:
        if not self.configured():
            raise ProviderError("not_configured", self.requirement())
        if region != "IN":
            return ProviderResult()
        token = self._access_token()
        response = call_with_retries(lambda: self._client.post(
            self.API_URL, headers={"Authorization": f"Bearer {token}", "x-marketplace": self.MARKETPLACE},
            json={"keywords": query, "partnerTag": self._tag, "marketplace": self.MARKETPLACE,
                  "searchIndex": "Electronics", "resources": self.RESOURCES}), self._sleep)
        _check_status(response)
        payload = _json(response)
        result_block = payload.get("searchResult") if isinstance(payload, dict) else None
        items = result_block.get("items") if isinstance(result_block, dict) else None
        if items is None and isinstance(result_block, dict):
            return ProviderResult()  # a search with no hits
        if not isinstance(items, list):
            raise ProviderError("malformed", "The response has no searchResult.items.")
        result = ProviderResult()
        for item in items:
            try:
                result.offers.extend(self._offers(item))
            except (KeyError, TypeError, ValueError) as exc:
                ref = str(item.get("asin", "?")) if isinstance(item, dict) else "?"
                result.rejected.append((ref, f"malformed item: {exc}"[:300]))
        return result

    @staticmethod
    def _offers(item: dict[str, Any]) -> list[RawOffer]:
        info = item.get("itemInfo") or {}
        title = str(info["title"]["displayValue"]).strip()
        brand = ((info.get("byLineInfo") or {}).get("brand") or {}).get("displayValue")
        listings = (item.get("offersV2") or {}).get("listings") or []
        if not listings:
            raise ValueError("no offersV2 listings")
        offers = []
        for listing in listings:
            amount = (listing.get("price") or {}).get("money") or {}
            price = money(amount.get("amount"))
            if price is None:
                continue
            stated = str(((listing.get("condition") or {}).get("value")) or "").casefold()
            condition = {"new": "new", "used": "used", "refurbished": "refurbished"}.get(stated) \
                or condition_from_title(title)
            availability = str(((listing.get("availability") or {}).get("type")) or "").upper()
            merchant = (listing.get("merchantInfo") or {}).get("name")
            offers.append(RawOffer(
                title=title, price=price, currency=str(amount.get("currency") or ""), condition=condition,
                price_type=PRICE_TYPE[condition], provider_product_id=item.get("asin"), brand=brand,
                url=item.get("detailPageURL"), seller=merchant, seller_type="marketplace_seller" if merchant else None,
                availability={"IN_STOCK": "in_stock", "OUT_OF_STOCK": "out_of_stock"}.get(availability),
                raw=item,
            ))
        if not offers:
            raise ValueError("no listing has a price")
        return offers


# --- Cashify: no authorised automated access -------------------------------------------------------------------


CASHIFY = SourceSpec(
    id="cashify-manual",
    name="Cashify buyback quotes (manually recorded)",
    source_type="dealer_offer",
    collection_method="Quotes recorded by hand from cashify.in with date and conditions; imported as CSV",
    markets="IN",
    terms_note="Cashify's terms of use prohibit systematic retrieval, so nothing is fetched automatically. Each "
               "quote is entered manually with the date and the condition answers used.",
    verified=False,
    url="https://www.cashify.in/sell-old-mobile-phone",
)


class CashifyManual:
    spec = CASHIFY
    automated = False

    def configured(self) -> bool:
        return False

    def requirement(self) -> str:
        return "No authorised automated access (Cashify's terms prohibit systematic retrieval). Record quotes " \
               "manually via /admin → Import offers, or obtain a data agreement from Cashify."

    def search(self, query: str, region: str) -> ProviderResult:
        raise ProviderError("not_configured", self.requirement())
