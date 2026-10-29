# Prompt for the FlipValue maintainer's AI assistant

Copy everything between the two lines below and give it to the AI coding assistant working in the FlipValue
repository. Send `INTEGRATION_CONTRACT.md` and `docs/flipvalue-contract.openapi.json` from the FixMyTech repository
alongside it if you can; the prompt is self-contained if you can't. **Do not paste API keys or other secrets into the
prompt.**

---

You are working in the **FlipValue** repository. FlipValue is an independent device-valuation service maintained by
my partner. A separate application, **FixMyTech**, maintained by another student, needs to call FlipValue's API. Your
job is to make FlipValue provide that API correctly and safely, without breaking anything FlipValue already does.
You have no other context about FixMyTech beyond what is written here, so rely on this prompt and on what you find in
the FlipValue code.

## What FixMyTech is (as actually implemented)

FixMyTech is a Python/FastAPI web app that diagnoses Android phone problems (a local agent reads read-only data over
USB/ADB, the customer answers adaptive questions, and a rule-based engine ranks likely faults with their evidence). It
estimates repair costs and compares four options: repair and keep, sell as-is and replace, sell as-is now, and repair
then sell. For that it needs two resale values from FlipValue: the phone's value **as it is**, and its value **after a
specified repair**.

FixMyTech's FlipValue client is already implemented and tested, but only against FixMyTech's own *mock* of FlipValue.
It has never talked to the real FlipValue. The interface below is FixMyTech's **proposal**, not an agreed contract.

## The interface FixMyTech's client currently implements

**Call:** `POST {BASE_URL}/v1/valuations` over HTTPS (plain HTTP is accepted by FixMyTech only for localhost).

**Headers sent:** `X-API-Key: <key>`, `Content-Type: application/json`, `Accept: application/json`,
`X-Request-ID: <uuid4>`, `Idempotency-Key: <same uuid4, identical on retries>`, `FlipValue-API-Version: 1`,
`User-Agent: FixMyTech/0.2`.

**Request body** (optional fields are omitted when unknown, never sent as null):

```json
{
  "device": {"manufacturer": "Samsung", "model": "SM-G991B", "storage_gb": 128, "age_months": 34},
  "region": "US",
  "currency": "USD",
  "condition": {"grade": "faulty", "faults": ["battery_wear"]},
  "repair_scenario": {"repair_type": "battery_replacement"}
}
```

* `device.manufacturer` string 1-80, required. Often lowercase as Android reports it (`samsung`).
* `device.model` string 1-80, required. Often an OEM model code (`SM-G991B`), sometimes a marketing name (`Pixel 7`).
* `device.storage_gb` int 1-4096, optional. `device.age_months` int 0-240, optional (customer estimate).
* `region` ISO 3166-1 alpha-2 (FixMyTech uses `IN` by default, and `US`). `currency` ISO 4217 (`INR`, `USD`).
  Indian customers are the main audience, so supporting `IN`/`INR` matters most.
* `condition.grade` one of `excellent` (like new), `good` (light wear, fully working), `fair` (visible scratches/dents,
  fully working), `poor` (heavy wear or cracked back, still working), `faulty` (at least one function not working).
* `condition.faults` array (may be empty) of: `software_instability`, `storage_pressure`, `battery_wear`,
  `charging_path`, `display_damage`, `camera_fault`, `audio_fault`, `connectivity_issue`, `liquid_damage`. These are
  *likely* faults from diagnosis, not confirmed defects.
* `repair_scenario` optional; `repair_type` one of: `battery_replacement`, `charging_port_replacement`,
  `screen_replacement`, `camera_module_replacement`, `audio_component_replacement`, `liquid_damage_service`,
  `software_reset`.

**Successful response (200)** that FixMyTech validates strictly:

```json
{
  "api_version": "1",
  "valuation_id": "val_123",
  "currency": "USD",
  "as_is": {"value": 180.0, "low": 150.0, "high": 210.0},
  "after_repair": {"value": 260.0, "low": 235.0, "high": 285.0},
  "data_timestamp": "2026-10-18T00:00:00Z",
  "method": "comparable-sales-v2",
  "status": "ok",
  "warnings": []
}
```

* Required: `api_version` (string), `valuation_id` (≤100 chars), `currency` (3 uppercase letters, should equal the
  requested currency), `as_is.value` (≥0), `data_timestamp` (ISO 8601), `method` (≤200 chars, method/model version),
  `status` (`ok` or `partial`).
* Optional: `as_is.low`/`high` with `low ≤ value ≤ high`; `after_repair` (same shape; expected when `repair_scenario`
  was sent, `null` otherwise); `warnings` (≤20 strings). Extra fields are ignored.
* Values are major currency units as JSON numbers and should be the **gross expected sale price before selling fees**
  (FixMyTech applies fees itself; netting them here would double count).
* Never return `"mock": true` from the real service: FixMyTech rejects such responses in live mode.
* Any violation (missing field, negative value, `low > value`, non-JSON) makes FixMyTech discard the response.

**Errors:** body `{"error": {"code": "...", "message": "...", "request_id": "..."}}`. FixMyTech behaviour by status:
400/422 → invalid request (not retried); 401/403 → auth failed (not retried); 404 → model not supported (not
retried); 429 with `Retry-After` → retried; 502/503/504, timeouts, connection errors → retried; other 5xx → not
retried. FixMyTech waits up to 8 s per attempt, at most 2 retries, backoff 0.5 s then 1 s, `Retry-After` capped at 5 s.
So FlipValue should answer within a few seconds and must treat repeated `Idempotency-Key`s as the same request (the
endpoint must have no side effects).

## Your tasks

1. **Inspect the FlipValue repository first.** Before changing anything, read its README, dependencies, existing API
   (framework, routes, auth), valuation logic, data sources, tests and deployment setup. Summarise what exists.
2. **Preserve FlipValue's independent functionality.** Existing endpoints, UIs and behaviour must keep working. Add the
   integration alongside them (e.g. a new versioned route) rather than rewriting.
3. **Compare FlipValue with the interface above** and write `FIXMYTECH_CONTRACT_REVIEW.md` listing, field by field:
   what already matches, what you will implement, and every **mismatch or questionable assumption** (endpoint path,
   auth header, model identification, supported regions/currencies, grade meanings, how faults affect value, what
   `after_repair` assumes, what `low`/`high` represent, private-sale vs trade-in prices). **Flag mismatches explicitly;
   do not silently guess.** Where FlipValue's real design is better, propose the change rather than bending it.
4. **Implement or adapt `POST /v1/valuations`** to the interface (or to the agreed variant you propose in step 3).
5. **Secure API-key authentication:** keys from environment/secret storage, never in code or git; constant-time
   comparison; 401/403 with the error envelope; support for more than one key so keys can be rotated. Add rate
   limiting appropriate to FlipValue's hosting (return 429 + `Retry-After`).
6. **Real valuation logic:** use FlipValue's actual valuation method and data. Do **not** fabricate prices or return
   placeholder numbers as if real. If FlipValue cannot value a model, return 404 with the error envelope; if it can
   only partly value it, return `status: "partial"` with a warning. Implement `after_repair` based on the repair type and
   document the assumptions. Document data sources, freshness (`data_timestamp`), coverage and limitations.
7. **Validation and structured errors:** strict request validation (unknown grades, faults, repair types, bad currency
   or region → 422 with a helpful message); consistent error envelope with a request id; no stack traces or secrets in
   responses or logs.
8. **OpenAPI and examples:** publish an OpenAPI spec for the endpoint and working example requests (curl or HTTPie)
   for: success with and without `repair_scenario`, bad key, unknown model, invalid grade, rate limit.
9. **Tests:** unit tests for validation and valuation logic; API tests for success and every error path (401, 404,
   422, 429, idempotent repeat, response invariants `0 ≤ low ≤ value ≤ high`, currency matches request, `mock` never
   true). Add a contract test that validates responses against the JSON shape above.
10. **Integrate against FixMyTech's real requirements:** provide a staging HTTPS URL if possible and a way to issue a
    key to FixMyTech privately. FixMyTech connects by setting `FLIPVALUE_MODE=live`, `FLIPVALUE_BASE_URL`,
    `FLIPVALUE_API_KEY`.
11. **Test both successful and failed integration paths** end to end if you can run FixMyTech, or at least with the
    curl examples and your tests.
12. **Update documentation** (README, API docs, data limitations, configuration, `.env.example` without secrets).
13. **Report honestly** at the end: what you implemented, which tests you ran and their real results, what was verified
    only locally, every remaining contract mismatch or open question for FixMyTech, and the exact steps for FixMyTech to
    connect. Never claim that something works unless you ran it.

## Constraints

* Do not put API keys, passwords or private configuration in code, docs, commits or this conversation.
* Do not invent endpoints or behaviour that FlipValue's code does not support without saying so.
* Keep changes reviewable; explain significant design decisions briefly.

---
