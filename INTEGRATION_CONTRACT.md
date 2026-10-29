# FlipValue ↔ FixMyTech integration contract — as implemented

**Contract version:** `1.2-implemented` (FlipValue 0.2.0, updated 2026-10-25). Based on FixMyTech's `1.0-proposed`
(`FlipValue/My Friend's Project Status and Details/INTEGRATION_CONTRACT.md`). **Request and response schemas of
`POST /v1/valuations` are unchanged and backward compatible**; §9 lists behaviour changes and additions; §11
describes an optional richer endpoint. Machine-readable: `GET /openapi.json`. Source of truth in code:
`src/flipvalue/schemas.py`, `routes/partner.py`, `routes/developer.py`, `app.py`, `engine.py`.

FlipValue works without FixMyTech; FixMyTech is one authorised client of the same API other developers use. FlipValue
does not call FixMyTech and shares no database schema with it. FixMyTech makes its own repair-versus-replace decision
from its repair estimates and FlipValue's values.

## 1. Endpoint

`POST {FLIPVALUE_BASE_URL}/v1/valuations`, JSON. Side-effect free apart from idempotency records.

| Environment | `FLIPVALUE_BASE_URL` |
|---|---|
| Production (planned: Google Cloud Run, asia-south1) | The Cloud Run service URL, `https://flipvalue-api-…run.app`. **Not created yet**; it will be sent with the key once deployed. Call it directly (no CDN, no 60 s Hosting limit) |
| Also routed | `https://<firebase-project>.web.app/v1/valuations` via Firebase Hosting rewrites (not the recommended path for FixMyTech) |
| Local | `http://127.0.0.1:8091` |

The deployment (DEPLOYMENT.md) does **not** change the request, response, headers or error codes below. Cloud Run
adds Google's front end: TLS is always on, and a request taking over 30 s is cut by the platform (FlipValue's own
limit is 5 s → 503 `service_timeout`). Cold starts after idle periods can add a few seconds to the first request;
FixMyTech's 8 s timeout and retry on timeout already cover this.

## 2. Request headers

| Header | Required | Behaviour |
|---|---|---|
| `X-API-Key` | yes | Partner-role key with scope `valuation:read`. Missing/invalid/revoked/admin-role → 401; without the scope → 403 `insufficient_scope` (checked before the body is parsed). Keys issued by the operator for FixMyTech have all scopes |
| `Content-Type: application/json` | yes | Body ≤ 16 KiB (`Content-Length` required) |
| `FlipValue-API-Version` | no | Absent or `1`; anything else → 400 `unsupported_api_version` |
| `X-Request-ID` | no | Echoed as `X-Request-ID` and `error.request_id` if it matches `[A-Za-z0-9._:-]{1,100}`, else replaced by a UUID |
| `Idempotency-Key` | no | 1–100 chars. Same key + same body within 24 h → stored response replayed (`Idempotent-Replayed: true`); same key + different body → 422 `idempotency_key_reused` |

Response headers on every authenticated response: `X-Request-ID`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`,
`X-RateLimit-Reset` (seconds); for keys with a daily quota also `X-Quota-Limit`, `X-Quota-Remaining`,
`X-Quota-Reset`. Operator-issued keys (the kind FixMyTech receives) have no daily quota unless agreed.

## 3. Request body (unchanged)

```json
{"device": {"manufacturer": "samsung", "model": "SM-G991B", "storage_gb": 128, "age_months": 34},
 "region": "IN", "currency": "INR",
 "condition": {"grade": "faulty", "faults": ["battery_wear"]},
 "repair_scenario": {"repair_type": "battery_replacement"}}
```

| Field | Constraint |
|---|---|
| `device.manufacturer`, `device.model` | string 1–80 (trimmed). Matched case/space-insensitively against catalogue names and OEM codes |
| `device.storage_gb` | JSON integer 1–4096, optional — **required in practice for models with several storage sizes** (§9) |
| `device.age_months` | JSON integer 0–240, optional, not used (warning added) |
| `region` / `currency` | `IN`/`INR` or `US`/`USD` |
| `condition.grade` | `excellent` \| `good` \| `fair` \| `poor` \| `faulty` |
| `condition.faults` | array (≤ 20) of `software_instability`, `storage_pressure`, `battery_wear`, `charging_path`, `display_damage`, `camera_fault`, `audio_fault`, `connectivity_issue`, `liquid_damage` |
| `repair_scenario.repair_type` | `battery_replacement`, `charging_port_replacement`, `screen_replacement`, `camera_module_replacement`, `audio_component_replacement`, `liquid_damage_service`, `software_reset` |

Unknown fields → 422. `null` for an optional field is treated as omitted.

## 4. Success: 200

Actual response from a local server with **synthetic** data (2026-10-21):

```json
{
  "api_version": "1",
  "valuation_id": "val_e2a2d60e7ba7300e991e5fbf",
  "currency": "INR",
  "as_is": {"value": 8365.0, "low": 6966.0, "high": 9425.0},
  "after_repair": {"value": 21600.0, "low": 19777.0, "high": 22751.0},
  "data_timestamp": "2026-10-18T00:00:00Z",
  "method": "comparables-v1",
  "status": "ok",
  "warnings": [
    "MOCK DATA: these values come from synthetic development data and are not real market prices.",
    "Fault categories are not priced separately; the value reflects grade 'faulty' only.",
    "Device age is not used; the estimate reflects recent prices for this model.",
    "after_repair assumes the battery_replacement is done well and the phone then grades 'good'."
  ],
  "mock": true
}
```

| Field | Meaning |
|---|---|
| `as_is.value` | Median of comparable prices (gross, before selling fees, major units) |
| `as_is.low/high` | 10th–90th percentile with ≥ 10 observations, else min–max. Always present; `low ≤ value ≤ high` |
| `after_repair` | Same shape; comparables in the post-repair grade (`faulty`→`good`, others unchanged). `null` when no `repair_scenario`, or when it could not be valued (then `status: partial`) |
| `data_timestamp` | Newest observation used, midnight UTC |
| `method` | `comparables-v1` |
| `status` | `partial` if any estimate has limited evidence (< 10 observations, older than 90 days, or asking prices) or `after_repair` was requested but unavailable |
| `warnings` | ≤ 20 customer-readable strings (texts in §7) |
| `mock` | Always present. `true` only from synthetic data, which is impossible in production |
| `valuation_id` | Deterministic for the same request and evidence |

## 5. Errors

Envelope `{"error": {"code", "message", "request_id"}}`; `X-Request-ID` header on every response.

| HTTP | `code` | When |
|---|---|---|
| 400 | `unsupported_api_version` | Version header not `1` |
| 401 | `unauthorized` | Key missing, invalid, revoked or not a partner key |
| 403 | `insufficient_scope` | Key lacks `valuation:read` |
| 404 | `unsupported_model` | Manufacturer/model not in the catalogue |
| 404 | `no_data_for_condition` | Model known, but storage missing for a multi-variant model, storage not catalogued, or < 3 recent comparable prices |
| 411 | `length_required` | Chunked body without `Content-Length` |
| 413 | `payload_too_large` | Body > 16 KiB |
| 422 | `validation_error` | Invalid JSON, schema, enum, type, unknown field, bad `Idempotency-Key` length |
| 422 | `unsupported_region` / `unsupported_currency` | Region not IN/US; currency not that region's |
| 422 | `idempotency_key_reused` | Key reused with a different body |
| 429 | `rate_limited` | > 60 requests/minute per key (configurable per key); `Retry-After` seconds (1–60) |
| 429 | `quota_exceeded` | Only if the key has a daily quota; `Retry-After` until 00:00 UTC |
| 503 | `service_timeout` | Request exceeded 5 s; `Retry-After: 1`; safe to retry |
| 500 | `internal_error` | Unexpected error (no details exposed) |

## 6. Supported devices and markets

Markets: India (INR), United States (USD). Catalogue (`GET /api/catalogue` lists it): Samsung Galaxy S21
(`SM-G991B`, `SM-G991B/DS`, `SM-G991U`; 128/256 GB), Samsung Galaxy S23 (`SM-S911B`, `SM-S911B/DS`, `SM-S911U`;
128/256), Google Pixel 6a (128), Pixel 7 (128/256), Pixel 8 (128/256), Apple iPhone 13 (128/256/512).
Price evidence: **none real**. Synthetic data (development only) covers Galaxy S21 (IN 128/256, US 128), Pixel 7
(IN), Pixel 6a (IN, fair/faulty).

## 7. Warning texts

`MOCK DATA: …` · `{as_is|after_repair} is based on asking prices, not completed sales; actual sale prices are often
lower.` · `… is based on only N recent observations.` · `…: the newest observation is from YYYY-MM-DD.` ·
`Fault categories are not priced separately; the value reflects grade 'X' only.` · `Device age is not used; …` ·
`after_repair assumes the R is done well and the phone then grades 'G'.` · `No sufficient price data for grade 'G'
after R; after_repair is not available.`

## 8. Compatibility tests (run locally, automated in `tests/test_partner_api.py`)

| # | Test | Result |
|---|---|---|
| 1 | With `repair_scenario` → 200, `as_is` + `after_repair`, requested currency | pass |
| 2 | Without → `after_repair: null` | pass |
| 3 | Missing/wrong key → 401 | pass |
| 4 | Unknown model → 404 envelope | pass |
| 5 | Unknown grade/fault/repair → 422 | pass |
| 6 | Same `Idempotency-Key` twice → identical response | pass |
| 7 | `0 ≤ low ≤ value ≤ high`, ISO timestamps | pass |
| 8 | Production never returns `mock: true` | pass |

```bash
curl -s -X POST "$FLIPVALUE_BASE_URL/v1/valuations" -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"device":{"manufacturer":"samsung","model":"SM-G991B","storage_gb":128},"region":"IN","currency":"INR",
       "condition":{"grade":"faulty","faults":["battery_wear"]},"repair_scenario":{"repair_type":"battery_replacement"}}'
```

## 9. Changes from 1.0-proposed

| Change | Impact on FixMyTech |
|---|---|
| Values are medians of individual observations (`comparables-v1`) instead of a price table | None in shape |
| `storage_gb` needed for multi-variant models (404 `no_data_for_condition` otherwise) | Send storage whenever known |
| `status: partial` also signals limited evidence | Already handled (`partial` = low confidence) |
| `low`/`high` always present | None |
| `data_timestamp` = newest observation used | Display text only |
| New codes: `idempotency_key_reused` (422), `payload_too_large` (413), `length_required` (411), `service_timeout` (503), `internal_error` (500) | 503 is already retried; 413/411 should never occur with FixMyTech's requests |
| `mock` always present (false in production) | None |
| 1.2: keys carry scopes; `/v1/valuations` needs `valuation:read` (403 `insufficient_scope`) | None for operator-issued keys (all scopes). Map 403 to `auth_failed` |
| 1.2: rate-limit headers on every response; optional daily quota (429 `quota_exceeded`) | Optional: read `X-RateLimit-Remaining`. `quota_exceeded` should be treated like `rate_limited` but not retried within the day |
| 1.2: catalogue lookup `GET /api/v1/products?q=` and richer `POST /api/v1/valuations` (§11) | Optional |

## 10. Still open

Real data source (all marketplace and resale sources are blocked on approval/credentials — docs/DATA_SOURCES.md);
meaning of ranges for real data (planned: 10th–90th percentile of completed sales); the production URL and key
hand-over (deployment prepared, not performed).

## 11. Optional: richer valuation `POST /api/v1/valuations`

Same API key (scope `valuation:read`), same request body as §3 (also accepts `device.product_id` instead of
manufacturer + model). Returns **201** with separate value types instead of `as_is`/`after_repair` only:

| Field | Meaning |
|---|---|
| `private_sale` | Same estimate as `/v1` `as_is`, with `confidence`, `basis`, `observation_count`, dates, sources |
| `after_repair` | Same as `/v1` `after_repair` (null without `repair_scenario`) |
| `repair.value_uplift` | `after_repair.value − private_sale.value`, or null when either side lacks evidence |
| `buyback` | Dealer buyback / trade-in quotes, separately |
| `refurbished_retail`, `original_retail` | Current refurbished offers; retailer-supplied MRP |
| `confidence` | `high` / `medium` / `low` / `insufficient` |
| `assumptions`, `limitations`, `missing_data`, `how_to_improve`, `warnings` | Text for display |
| `status` | `ok`, `partial`, or `unavailable` — **no 404 for thin evidence**: unavailable values have `available: false` and a `reason` |

Differences from `/v1`: no `Idempotency-Key` support (creates a stored record each call, readable later via
`GET /api/v1/valuations/{id}`), `id` is random rather than deterministic, money fields are JSON numbers or `null`.
Full schema: docs/API_REFERENCE.md. FixMyTech does not need to switch; `/v1/valuations` stays supported for API
version 1.
