# Data sources

**Status (2026-10-27): no marketplace API is connected; a small set of real, manually checked prices exists.**
Adapters for Flipkart and Amazon are implemented and tested against documented response shapes (fixtures), but no
credentials exist in this environment, so **no live API call has been made** to any marketplace. Development also
runs on clearly labelled synthetic observations (`synthetic-dev`) and fixture offers (`fixture-offers`), both flagged
`is_mock`, excluded from every production response, and refused by `seed-mock` in production.

## FlipValue modelled estimates (2026-10-28)

At the owner's request, every catalogued phone now has modelled estimates: resale by grade, buyback, a monthly
depreciation curve since release, and one estimated price per store. They are generated from
`data/estimates/price_bands.csv`, which combines the owner's approximate price ranges with figures derived from the
manual checks below. Sources: `flipvalue-estimates`, `flipvalue-estimates-buyback` and `flipvalue-store-estimates`
(types `estimate` / `estimate_buyback`, not mock). They are always labelled as estimates and are never presented as
observed or retrieved prices. Store names show where such prices are typically found; no data was retrieved from
those stores. Method: VALUATION_METHODOLOGY.md, "Modelled estimates".

## Manual price checks (2026-10-27)

13 real offers were read by hand from individual public product pages on 2026-10-27 and imported with
`import-offers`. There was no crawling and no automated retrieval: Amazon's and Flipkart's terms forbid robots and
data extraction, and Cashify's prohibit systematic retrieval. Each row keeps its page URL. The files are in
`data/manual/`.

| Source id | File | Rows | From |
|---|---|---|---|
| `manual-retail-in` (new_retail) | `new_retail_2026-10-27.csv` | 2 | Flipkart product pages (Pixel 8 128 GB, iPhone 13 128 GB) |
| `manual-refurb-in` (refurbished_retail) | `refurbished_2026-10-27.csv` | 11 | Cashify, Budli, Easyphones refurbished listings (the original six models) |
| `manual-refurb-in` (refurbished_retail) | `refurbished_2026-10-28.csv` | 25 | Cashify refurbished listings, one per model added on 2026-10-28 (the default variant and grade each page showed) |

The 25 models added on 2026-10-28 have **one price each**, taken from one seller and one grade (mostly "Fair"). Ten
of those listings were out of stock. Out-of-stock offers appear in price comparison and history but are excluded from
the refurbished-retail value. A single offer gives `low` confidence.

Recording rules used:
* **Price** is the displayed selling price. Bank or card "Buy at ₹…" offer prices are excluded. On the iPhone 13 page,
  ₹49,900 was taken as the selling price and ₹47,405 as the offer price. Smartprix also lists Flipkart at ₹49,900.
* **MRP** is recorded only when it is labelled as MRP or matches the launch price (Pixel 8: ₹75,999). Refurbishers'
  strikethrough "original" prices are not treated as MRP.
* **Availability** is recorded as `out_of_stock` when the page said "Out of stock" or "Sold out", and left blank when
  the page did not say. Many refurbished units were sold out: they are real recent asking prices, not purchasable stock.
* **Excluded:** a Flipkart Galaxy S23 128 GB listing at ₹24,999 from a third-party seller. Its strikethrough was
  ₹89,999, but the S23 128 GB launched at ₹74,999 in India, and the price is below every refurbished S23 found. This
  points to an anomalous listing.
* Prices from aggregators (Smartprix, 91mobiles) were used only for cross-checking and were never imported. They
  disagreed with each other by up to 3×.

These rows will show as `stale` after `FLIPVALUE_OFFER_FRESH_HOURS` and stop being current after
`FLIPVALUE_OFFER_MAX_AGE_DAYS` (14). They stay in the price history. To refresh, re-check the same URLs and import a
new dated CSV.

FlipValue keeps two kinds of market data apart:

| Table | What | Used for |
|---|---|---|
| `observations` | Resale prices by grade: `completed_sale`, `listing`, `dealer_offer`, `trade_in`, … | Private-sale, after-repair and buyback estimates |
| `marketplace_offers` | Individual listings as retrieved: new retail, refurbished retail, used listings, buyback quotes | Price comparison, price history, refurbished-retail and MRP values, alerts |

## Access rules followed

1. Authorised APIs or affiliate feeds with the operator's own credentials, 2. documented partner integrations,
3. permitted public price lists, 4. compliant extraction only where permitted, 5. manual, source-attributed entries.
FlipValue never scrapes pages, bypasses access controls, CAPTCHAs or anti-bot measures. Each source records its
terms in `sources.terms_note`. Refresh frequency is capped per provider and product by
`FLIPVALUE_PROVIDER_MIN_REFRESH_MINUTES` (default 60, minimum 15).

## Marketplace providers (India)

Researched on 2026-10-25 from the providers' own documentation pages.

| Source | Type | Access found | Adapter | Status |
|---|---|---|---|---|
| **Flipkart Affiliate API** | new retail (refurbished when the title says so) | Registered affiliates only. `GET https://affiliate-api.flipkart.net/affiliate/1.0/search.json?query=&resultCount=` (max 10), headers `Fk-Affiliate-Id`, `Fk-Affiliate-Token`; items under `productInfoList[].productBaseInfoV1` with `flipkartSellingPrice`, `flipkartSpecialPrice`, `maximumRetailPrice`, `inStock`, `attributes.storage/color`, `productUrl`, and `productShippingInfoV1.sellerName/shippingCharges`. No rate limit or caching rule found on the reference page — read the API Terms of Use page when approved | `FlipkartAffiliate` | **Blocked: needs an approved Flipkart Affiliate account** → set `FLIPVALUE_FLIPKART_AFFILIATE_ID`, `FLIPVALUE_FLIPKART_AFFILIATE_TOKEN` |
| **Amazon.in** | new retail, refurbished/used offers | PA-API 5 was deprecated on 2026-04-30 and now answers 403. Successor: **Creators API** — OAuth2 client-credentials (scope `creatorsapi::default`, 1-hour tokens; token endpoint depends on the credential version Amazon assigns), `POST https://creatorsapi.amazon/catalog/v1/searchItems` with `x-marketplace: www.amazon.in`, prices from `offersV2.listings[].price.money`. Requires an Associates account approved for API access in that marketplace | `AmazonCreators` | **Blocked: needs Associates approval + Creators API credentials** → `FLIPVALUE_AMAZON_CREDENTIAL_ID`, `_CREDENTIAL_SECRET`, `_PARTNER_TAG`, `_TOKEN_URL`. Response field names follow the documented resource names and were **not verified against a live response** |
| **Cashify** | dealer buyback quotes | No public API. Terms of use prohibit systematic retrieval | `CashifyManual` (reports "manual only") | Quotes may be recorded by hand (with date and condition answers) and imported as CSV; or request a data agreement from Cashify |
| Manufacturer stores (Samsung, Apple, Google India) | new retail, trade-in | Not investigated in depth; no public price APIs known | none | Candidate for manual, source-attributed entries |
| Authorised refurbishers, OLX India | refurbished retail, used listings | Not investigated | none | Next research item |

What the adapters never invent: delivery cost (only a stated shipping charge), seller, stock status (only when the
provider supplies it), MRP (Amazon's "saving basis" is not treated as MRP), discount (computed only from a supplied
MRP), publication date.

## Resale-price sources investigated earlier (2026-10-21)

| Source | Market | Kind of price | Access | Decision |
|---|---|---|---|---|
| eBay Marketplace Insights (`item_sales`) | US | Completed sales (90 days) | Limited-release; eBay approval | Best US candidate; blocked on approval |
| Swappa | US | Listings | No official API | Ask for partner data |
| Back Market | US | Refurbished retail / buyback | Seller API only | Not available |

## Source types

`completed_sale`, `listing`, `dealer_offer`, `trade_in`, `refurbished_retail`, `new_retail`, `customer_quote`,
`synthetic`. Offer `price_type`: `new_retail`, `refurbished_retail`, `used_listing`, `buyback_quote`. They measure
different things and are never averaged together (VALUATION_METHODOLOGY.md).

## Connecting a provider (once approved)

1. Put the credentials in Secret Manager (production) or `.env` (local); restart.
2. `python -m flipvalue providers` — the provider should show `configured`.
3. `python -m flipvalue refresh-offers --model samsung-galaxy-s21 --storage 128` and inspect the result; then
   `GET /admin/api/data-quality` for rejects and match categories.
4. Schedule `python -m flipvalue refresh-offers` (e.g. Cloud Scheduler → Cloud Run Job) no more often than the
   provider's terms allow. The command exits non-zero if any provider failed.
5. Record the provider's terms (rate limits, caching, attribution) here and adjust
   `FLIPVALUE_PROVIDER_MIN_REFRESH_MINUTES` / `FLIPVALUE_OFFER_MAX_AGE_DAYS` to match.

## Adding a manual or other source

Register it (`python -m flipvalue register-source …` or `POST /admin/api/sources`) with an honest `terms_note`, then
import resale observations (`import`) or offers (`import-offers`) as CSV — formats in DATA_QUALITY.md.

## Catalogue

`data/catalogue/models.csv` holds 31 models and device facts only (names, OEM codes, storage sizes, release dates),
no prices.
* The first 6 models were curated by hand from manufacturer specifications on 2026-10-21.
* 25 more were added on 2026-10-28: Apple, Samsung, Google, OnePlus, Nothing, Xiaomi, Motorola and Vivo models from
  2019 to 2024. Their facts were compiled from general knowledge of public specifications and were **not** checked
  page by page. In particular, release dates may be global rather than Indian sale dates, and storage lists may
  include variants not sold in India. Their `catalogue_source` says so.

Re-verify all of them before production.
