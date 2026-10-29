# FixMyTech ↔ FlipValue integration contract

**Contract version:** `1.0-proposed` · **Status:** PROPOSED by FixMyTech, **pending agreement with the FlipValue
maintainer.** Nothing here asserts that FlipValue already implements it.

**Revision note (FixMyTech v0.2.0, 2026-10-19):** the interface is unchanged from v0.1 (same endpoint, fields,
headers, errors and retry rules). Only the `User-Agent` version changed. FixMyTech's default market is now India
(`region: IN`, `currency: INR`), where it has official repair-price data; US/USD is still requested for US sessions.

Source of truth in code: `src/fixmytech/integrations/flipvalue/schemas.py` (request/response models) and
`client.py` (transport behaviour). Machine-readable: [`docs/flipvalue-contract.openapi.json`](docs/flipvalue-contract.openapi.json).

Legend: **[I]** implemented in FixMyTech's client · **[P]** proposed, FixMyTech depends on it · **[A]** awaiting partner
decision (FixMyTech can adapt).

## 1. Endpoint

| Item | Value | |
|---|---|---|
| Base URL | configured by `FLIPVALUE_BASE_URL` (FixMyTech never hard-codes it) | [I] |
| Transport | HTTPS required in live mode (plain HTTP only for `localhost`/`127.0.0.1`) | [I] |
| Endpoint | `POST /v1/valuations` | [P][A] |
| Version | path prefix `/v1`; FixMyTech also sends `FlipValue-API-Version: 1`; response field `api_version` | [P] |
| Semantics | Side-effect free (a quote, not a listing). Safe to retry with the same `Idempotency-Key` | [P] |

## 2. Request headers (sent by FixMyTech)

| Header | Value | |
|---|---|---|
| `X-API-Key` | secret API key issued by FlipValue to FixMyTech | [I][A] |
| `Content-Type` | `application/json` | [I] |
| `Accept` | `application/json` | [I] |
| `X-Request-ID` | UUID v4 per logical request (for log correlation) | [I] |
| `Idempotency-Key` | same UUID; identical on every retry of that request | [I] |
| `FlipValue-API-Version` | `1` | [I] |
| `User-Agent` | `FixMyTech/0.2` | [I] |

## 3. Request body

```json
{
  "device": {"manufacturer": "Samsung", "model": "SM-G991B", "storage_gb": 128, "age_months": 34},
  "region": "US",
  "currency": "USD",
  "condition": {"grade": "faulty", "faults": ["battery_wear"]},
  "repair_scenario": {"repair_type": "battery_replacement"}
}
```

| Field | Type / constraint | Required | Notes |
|---|---|---|---|
| `device.manufacturer` | string 1-80 | yes | As reported by the phone (`ro.product.manufacturer`, often lowercase) or typed by the customer [A: normalisation] |
| `device.model` | string 1-80 | yes | Often an OEM model code (`SM-G991B`) rather than a marketing name [A: FlipValue must map codes or tell us what it needs] |
| `device.storage_gb` | int 1-4096 | no (omitted if unknown) | |
| `device.age_months` | int 0-240 | no (omitted if unknown) | Customer estimate |
| `region` | ISO 3166-1 alpha-2 | yes | FixMyTech currently uses `US`, `IN` |
| `currency` | ISO 4217, `^[A-Z]{3}$` | yes | Currency FixMyTech wants values in (`USD` for US, `INR` for IN). FixMyTech does no conversion |
| `condition.grade` | `excellent` \| `good` \| `fair` \| `poor` \| `faulty` | yes | Definitions in §6 [A] |
| `condition.faults` | array of fault categories (§6), may be empty | yes | Faults with *moderate or strong* diagnostic support; these are likely, **not confirmed** |
| `repair_scenario` | object or omitted | no | When present, FlipValue should also return `after_repair` |
| `repair_scenario.repair_type` | one of the repair types in §6 | yes if object present | |

Optional fields that are unknown are **omitted** (not sent as `null`). FixMyTech sends no serial numbers, IMEIs or
personal data.

## 4. Successful response: `200 OK`

```json
{
  "api_version": "1",
  "valuation_id": "val_8f2c...",
  "currency": "USD",
  "as_is": {"value": 180.00, "low": 150.00, "high": 210.00},
  "after_repair": {"value": 260.00, "low": 235.00, "high": 285.00},
  "data_timestamp": "2026-10-18T00:00:00Z",
  "method": "comparable-sales-v2",
  "status": "ok",
  "warnings": []
}
```

| Field | Type / constraint | Required | FixMyTech use |
|---|---|---|---|
| `api_version` | string | yes | logged/stored |
| `valuation_id` | string ≤ 100 | yes | shown in report |
| `currency` | ISO 4217 | yes | must equal the decision currency, else the comparison is refused (`currency_mismatch`) |
| `as_is.value` | number ≥ 0 | yes | sell-as-is and replace scenarios |
| `as_is.low` / `.high` | number, `low ≤ value ≤ high` | no | uncertainty range (point value used if absent) |
| `after_repair` | same shape, or `null`/absent | yes when `repair_scenario` sent [P] | repair-and-keep / repair-and-resell |
| `data_timestamp` | ISO 8601 datetime | yes | "data as of" in UI |
| `method` | string ≤ 200 (model version / method name) | yes | shown in report |
| `status` | `ok` \| `partial` | yes | `partial` = some values missing/low confidence |
| `warnings` | array of strings, ≤ 20 | no (default `[]`) | shown verbatim |
| `mock` | boolean, default `false` | no | **must be absent/false from the real service**; FixMyTech in live mode rejects `true` |

Extra fields are ignored (forward compatible). **Money semantics [P]:** values are in major currency units as JSON
numbers, and are **gross expected sale prices before selling fees**. FixMyTech applies the customer's fee assumption
itself; netting fees on FlipValue's side would double count them.

Validation failures (missing fields, negative values, `low > value`, bad currency code, non-JSON) are treated as
`flipvalue_invalid_response` and **no values are used**.

## 5. Errors

Body (recommended [P]): `{"error": {"code": "string", "message": "human readable", "request_id": "string"}}`.
FixMyTech reads `message` for 400/404/422 if present; the status code drives behaviour:

| HTTP | Meaning | FixMyTech behaviour | Retried? |
|---|---|---|---|
| 400, 422 | Invalid request | `flipvalue_rejected_request` | no |
| 401, 403 | Bad/missing key | `flipvalue_auth_failed` | no |
| 404 | Device/model not supported | `flipvalue_unsupported_device` | no |
| 429 | Rate limited; `Retry-After` seconds recommended | `flipvalue_rate_limited` | yes |
| 502, 503, 504 | Temporarily unavailable | `flipvalue_unavailable` | yes |
| other 5xx | Server error | `flipvalue_unavailable` | no |
| timeout / connection error | - | `flipvalue_timeout` / `flipvalue_unavailable` | yes |
| other / malformed 200 | - | `flipvalue_invalid_response` | no |

## 6. Shared vocabularies

**Condition grades [A]:** `excellent` like new, fully working · `good` light wear, fully working · `fair` visible
scratches/dents, fully working · `poor` heavy wear or cracked back, still working · `faulty` at least one function does
not work properly. FixMyTech suggests `faulty` when a hardware fault has moderate/strong support; the customer can change it.

**Fault categories [I]:** `software_instability`, `storage_pressure`, `battery_wear`, `charging_path`,
`display_damage`, `camera_fault`, `audio_fault`, `connectivity_issue`, `liquid_damage`.

**Repair types [I]:** `battery_replacement`, `charging_port_replacement`, `screen_replacement`,
`camera_module_replacement`, `audio_component_replacement`, `liquid_damage_service`, `software_reset`.

`after_repair` should value the phone *after the named repair is done well* (the mock assumes the result is "good"
condition) [A].

## 7. Timeouts, retries, limits (FixMyTech side) [I]

* Per-attempt timeout `FLIPVALUE_TIMEOUT_S` (default 8 s); up to `FLIPVALUE_MAX_RETRIES` (default 2) retries.
* Backoff 0.5 s, 1 s (doubling, capped at 5 s); `Retry-After` honoured up to 5 s. Worst case ≈ 26 s.
* FixMyTech limits each customer session to 20 valuation calls per hour.
* FlipValue rate limits and quotas: [A].

## 8. Compatibility tests

Both sides should pass these (FixMyTech's are automated in `tests/unit/test_flipvalue_client.py`):

1. Valid request with `repair_scenario` → 200 with `as_is` and `after_repair`, `currency` = requested currency.
2. Same without `repair_scenario` → `after_repair` null/absent.
3. Missing or wrong `X-API-Key` → 401.
4. Unknown model → 404 with error envelope.
5. Unknown `condition.grade` / fault / repair type → 422.
6. Same `Idempotency-Key` twice → same result (or same `valuation_id`).
7. Response always satisfies `low ≤ value ≤ high`, values ≥ 0, ISO timestamps.
8. Real service never sets `mock: true`.

Reference implementation for behaviour: the MOCK server `src/fixmytech/integrations/flipvalue/mock_server.py`
(failure injection via model names `MOCK-TIMEOUT`, `MOCK-503`, `MOCK-429`, `MOCK-UNKNOWN`, `MOCK-INVALID`).

## 9. Open questions for the FlipValue maintainer

1. Endpoint path and auth header name acceptable? (`POST /v1/valuations`, `X-API-Key`)
2. How should models be identified: OEM codes, marketing names, or a FlipValue catalogue id (and a lookup endpoint)?
3. Supported regions and currencies; behaviour when a currency is not supported (proposed: 422 `unsupported_currency`).
4. Grade definitions and how fault categories affect the as-is value.
5. Semantics of `after_repair` (assumed repair quality/grade) and of ranges (e.g. 10th-90th percentile?).
6. Are values private-sale, marketplace or trade-in prices? (FixMyTech assumes gross private/marketplace sale price.)
7. Rate limits, quotas, and how API keys are issued/rotated.
8. Staging URL for integration testing.
