# FlipValue API reference — version 1

Source of truth in code: `src/flipvalue/routes/developer.py`, `routes/account.py`, `schemas.py`,
`marketplace/service.py`. Machine-readable schema: `GET /openapi.json` (interactive at `/docs`). Every endpoint
listed here is implemented and covered by `tests/test_developer_api.py` unless marked otherwise.

FlipValue has four API surfaces:

| Prefix | For | Auth |
|---|---|---|
| `/api/v1/*` | Third-party developers (incl. FixMyTech if it wants the richer response) | `X-API-Key` with scopes |
| `/v1/valuations` | FixMyTech partner contract (INTEGRATION_CONTRACT.md) — frozen shape | `X-API-Key` with `valuation:read` |
| `/api/*` | FlipValue's own website (anonymous) and `/api/account/*` (signed-in users) | none / session cookie |
| `/admin/api/*` | Operators | admin-role `X-API-Key` |

## Getting a key

1. Open `/developers` on the website, create an account (email + password ≥ 10 chars).
2. Create a key: give it a name and choose scopes. The raw key (`fv_…`, 256 random bits) is shown **once**.
3. Store it in your server-side secret storage. Call the API only from your server.

Operators can also issue keys from the CLI: `python -m flipvalue keys create --name <client> --role partner
[--scopes valuation:read,...] [--rate-limit N] [--daily-quota N]`.

## Authentication, limits and common headers

| Header | Direction | Meaning |
|---|---|---|
| `X-API-Key` | request | Required on every `/api/v1` endpoint except `/api/v1/health` |
| `X-Request-ID` | both | Optional; echoed back (else generated). Quote it when reporting a problem |
| `X-RateLimit-Limit` / `-Remaining` / `-Reset` | response | Per-key requests per minute; seconds until the window resets |
| `X-Quota-Limit` / `-Remaining` / `-Reset` | response | Per-key requests per UTC day (self-service keys; operator keys have none by default) |
| `Retry-After` | response | On 429 and 503 |

Defaults: self-service keys 60 requests/minute and 1,000/day (`FLIPVALUE_DEVELOPER_RATE_LIMIT_PER_MIN`,
`FLIPVALUE_DEVELOPER_DAILY_QUOTA`); up to 5 active keys per account. Operator-issued keys use
`FLIPVALUE_RATE_LIMIT_PER_MIN` (60) and no daily quota unless set. Limits are counted in the database, so they hold
across server instances. One key shares one minute window and one daily quota across `/api/v1` and `/v1`.

### Scopes

| Scope | Grants |
|---|---|
| `valuation:read` | `POST /api/v1/valuations`, `GET /api/v1/valuations/{id}`, `POST /v1/valuations`, `POST /api/v1/decision` |
| `market_prices:read` | `GET /api/v1/market-prices` |
| `price_history:read` | `GET /api/v1/price-history`, `GET /api/v1/trends` |
| (any valid key) | `GET /api/v1/products`, `GET /api/v1/products/{id}`, `GET /api/v1/usage` |

Scopes are enforced on the server. Environment (bootstrap) partner keys have all three scopes.

## Errors

Every error: `{"error": {"code": "...", "message": "...", "request_id": "..."}}`.

| HTTP | `code` | Meaning / what to do |
|---|---|---|
| 401 | `unauthorized` | Key missing, wrong, revoked, or an admin key. Revocation applies to the next request |
| 403 | `insufficient_scope` | The key lacks the scope; create a key with it |
| 404 | `unsupported_model` | Product not in the catalogue (see `/api/v1/products`) |
| 404 | `not_found` | Valuation id unknown **or created by another account** (indistinguishable on purpose) |
| 404 | `no_data_for_condition` | Valuation: storage missing for a multi-variant model, or storage not catalogued |
| 411 / 413 | `length_required` / `payload_too_large` | Send `Content-Length`; body ≤ 16 KiB |
| 422 | `validation_error` | Schema, type, enum, unknown field |
| 422 | `unsupported_region` / `unsupported_currency` | Regions `IN`/`INR`, `US`/`USD`; no conversion |
| 422 | `variant_required` | Market endpoints: give `storage_gb` for multi-variant products |
| 429 | `rate_limited` | Per-minute limit; wait `Retry-After` |
| 429 | `quota_exceeded` | Daily quota used; resets 00:00 UTC |
| 503 | `service_timeout` | Took > 5 s; safe to retry |
| 500 | `internal_error` | No details exposed |

## Endpoints

### `GET /api/v1/health` — no key

```json
{"status": "ok", "api_version": "1", "service_version": "0.2.0", "environment": "development",
 "providers": {"flipkart-affiliate": "not_configured", "amazon-creators-in": "not_configured",
               "cashify-manual": "manual_only"}}
```

### `POST /api/v1/valuations` — `valuation:read` → 201

Request (identify the device by `product_id`, or by `manufacturer` + `model` name/OEM code):

```json
{"device": {"manufacturer": "Samsung", "model": "SM-G991B", "storage_gb": 128, "age_months": 30},
 "region": "IN", "currency": "INR",
 "condition": {"grade": "faulty", "faults": ["display_damage"]},
 "repair_scenario": {"repair_type": "screen_replacement"}}
```

Grades, fault categories and repair types are the same enums as the partner contract (INTEGRATION_CONTRACT.md §3).
Unknown fields → 422.

Response (shape; values below are from a local run on **synthetic** data, so `mock: true` and confidence `low`):

```json
{
  "id": "val_Qm9…", "object": "valuation", "api_version": "1", "created_at": "2026-10-25T17:12:03Z",
  "method": "comparables-v1", "status": "ok", "mock": true, "region": "IN", "currency": "INR",
  "product": {"id": "samsung-galaxy-s21", "manufacturer": "Samsung", "name": "Galaxy S21", "storage_gb": 128,
              "storage_inferred": false},
  "condition": {"grade": "faulty", "faults": ["display_damage"]},
  "private_sale":       {"type": "private_sale", "available": true, "value": 8365.0, "low": 6966.0, "high": 9425.0,
                         "basis": "synthetic", "confidence": "low", "observation_count": 12,
                         "oldest_observation": "2026-06-…", "newest_observation": "2026-10-…", "sources": […]},
  "buyback":            {"type": "buyback", "available": false, "confidence": "insufficient",
                         "reason": "No dealer buyback or trade-in quotes for this phone in grade 'faulty' …"},
  "refurbished_retail": {"type": "refurbished_retail", "available": true, "value": 24999.0, "low": 23990.0,
                         "high": 26499.0, "basis": "refurbished_offers", "confidence": "low", "observation_count": 3},
  "original_retail":    {"type": "original_retail", "available": true, "value": 69999.0, "basis": "mrp",
                         "confidence": "low", "observation_count": 2, "reason": "Only 2 current offer(s)."},
  "after_repair":       {"type": "after_repair", "available": true, "value": 21600.0, "low": 19777.0, "high": 22751.0, …},
  "repair": {"repair_type": "screen_replacement", "assumed_grade_after_repair": "good", "value_uplift": 13235.0,
             "confidence": "low", "note": "Difference between comparable prices in the two grades; …"},
  "confidence": "low", "data_timestamp": "2026-10-…",
  "assumptions": ["Grade 'faulty' as reported.", "After the screen replacement the phone grades 'good' …"],
  "limitations": ["Values are gross sale prices before selling fees …", "…"],
  "missing_data": [], "how_to_improve": ["More recent comparable observations would narrow the range."],
  "warnings": ["MOCK DATA: …", "Fault categories are not priced separately; …"]
}
```

| Field | Meaning |
|---|---|
| `private_sale` | What a private buyer pays: completed sales, else asking prices (labelled, confidence `low`) |
| `buyback` | Dealer buyback quotes, else retailer trade-in credit. Never mixed with private sales |
| `refurbished_retail` | Median of current refurbished offers for the exact variant — what a refurbisher charges, **not** what a seller receives |
| `original_retail` | Median retailer-supplied MRP for the exact variant. No unattributed launch prices |
| `after_repair` | Present only with `repair_scenario`; comparables in the post-repair grade |
| `repair.value_uplift` | `after_repair.value − private_sale.value`, or `null` if either is unavailable. Excludes repair cost |
| `confidence` | `high` (≥ 10 completed sales, newest ≤ 90 days) · `medium` · `low` · `insufficient`. Synthetic data is never above `low` |
| `status` | `ok`, `partial` (limited evidence or after-repair unavailable), `unavailable` (no private-sale estimate) |
| `id` | Random. Valuations are stored for 365 days and readable only by the same account (any of its keys) |

A value with too little evidence is returned with `available: false`, `value: null` and a `reason`.

### `GET /api/v1/valuations/{id}` — `valuation:read`

Returns the stored valuation. Another account's id → 404 `not_found`.

### `GET /api/v1/market-prices?product_id=&storage_gb=&region=IN` — `market_prices:read`

Current offers (latest retrieval of each listing within `FLIPVALUE_OFFER_MAX_AGE_DAYS`, default 14) for exactly this
product and storage.

```json
{"model_id": "samsung-galaxy-s21", "storage_gb": 128, "region": "IN", "currency": "INR",
 "groups": {"new": [Offer…], "refurbished": […], "used": […], "buyback": […]},
 "summary": {"new": {"count": 3, "lowest": 41990.0, "highest": 43490.0, "spread": 1500.0, "sources": […]}, …},
 "alternatives": [Offer…], "mrp": {"value": 69999.0, "count": 2}, "mock_data_included": false,
 "providers": [{"id": "flipkart-affiliate", "state": "not_configured", "requirement": "Set …", …}, …],
 "fresh_hours": 24, "max_age_days": 14, "generated_at": "…"}
```

`Offer`: `source{id,name,verified,is_mock}`, `title`, `brand`, `model_id`, `storage_gb`, `ram_gb`, `color`,
`condition`, `price_type`, `price`, `mrp`, `discount_pct` (only from a supplied MRP), `currency`, `url`, `seller`,
`seller_type`, `availability` (`in_stock`/`out_of_stock`/`null` = not supplied), `delivery_note`, `retrieved_at`,
`published_at`, `freshness` (`fresh` ≤ 24 h, else `stale`), `is_mock`, `match{category, score, reasons}`.

Groups contain only `exact`/`strong` matches of the requested storage, sorted by price with out-of-stock last.
`alternatives` holds other storage sizes and neighbouring models, labelled, never used for `lowest`. Provider
`state`: `operational`, `configured`, `failing`, `not_configured`, `manual_only`. When no source has data, groups are
empty — nothing is filled in.

### `GET /api/v1/price-history?product_id=&storage_gb=&condition=new&days=90` — `price_history:read`

Daily lowest observed price per source from stored retrievals; no interpolation.

```json
{"available": true, "observation_count": 6, "observed_days": 4,
 "series": {"Flipkart (Affiliate API)": [{"date": "2026-09-19", "lowest": 45990.0}, …]},
 "lowest": {"price": 41990.0, "date": "2026-10-01"}, "highest": {…},
 "change": {"from_date": "2026-09-28", "to_date": "2026-10-01", "amount": -1000.0, "pct": -2.3},
 "gaps": [{"from": "2026-09-19", "to": "2026-09-24", "days": 4}], "last_observation": "…",
 "reason": null, "resale_trend": {}}
```

`available: false` with a `reason` until prices were retrieved on at least two different days.
`resale_trend` = monthly medians of genuine resale observations (grade `good`), empty when there are none.

### `GET /api/v1/products?q=` and `GET /api/v1/products/{id}` — any key

The same entries as the website's `/api/catalogue`, plus two earlier fields: `{"id", "manufacturer", "name",
"release_date", "storage_gb": [128, 256], "oem_codes": ["SM-G991B", …], "evidence": {"IN": "estimated", "US": …},
"model_codes": [same as oem_codes], "regions": {"IN": "INR", "US": "USD"}}`. `q` matches names and model codes. A
code with a suffix (`SM-S901E/DS`) that matches nothing is retried without it. `POST /v1/valuations` matches codes
the same way.

### `GET /api/v1/trends?product_id=&storage_gb=&region=IN&grade=good` — `price_history:read`

Exactly the JSON of `GET /api/trends` (`model_id=` is accepted instead of `product_id=`): monthly resale prices since
release, one series per basis (`completed_sale`, `listing`, `trade_in`, and the labelled modelled `estimate`).
Without enough history: `available: false` and a `reason`. Unknown product: 404 `unsupported_model`.

### `POST /api/v1/decision` — `valuation:read`

Exactly the body and response of `POST /api/decision` (repair-or-sell scenarios from values you supply).

### `GET /api/v1/usage?days=30` — any key

Usage of the **calling key only**: `limits`, `current` (`minute_remaining`, `day_remaining`), `total`, `by_day`,
`by_endpoint` (ids grouped as `{id}`), `by_status`. A key can never read another key's usage.

## Account endpoints (website, cookie session)

`POST /api/account/register|login|logout`, `GET /api/account/me`, `GET|POST /api/account/keys`,
`DELETE /api/account/keys/{id}` (revoke), `GET /api/account/keys/{id}/usage`, `GET|POST /api/account/watchlist`,
`DELETE /api/account/watchlist/{id}`, `GET /api/account/alerts`, `POST /api/account/alerts/{id}/read`.
State-changing calls require the header `X-FlipValue-Client: web` (CSRF defence, docs/API_SECURITY.md). These are
for the FlipValue website, not for third-party servers.

## Operator endpoints added in this version

`GET /admin/api/providers`, `POST /admin/api/offers/refresh` (`{model_id, storage_gb?, region}`),
`POST /admin/api/offer-imports` (`{source_id, region, csv_text}`, format in DATA_QUALITY.md),
`GET /admin/api/data-quality?days=30`.
