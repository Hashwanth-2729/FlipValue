# Handoff prompt for the FixMyTech developer's AI assistant

Copy everything between the lines into the Claude Code session working in the **FixMyTech** repository. Send
`INTEGRATION_CONTRACT.md` from the FlipValue repository with it if you can; the prompt is self-contained otherwise.
**Never paste an API key into the prompt or any file in git.** The FlipValue maintainer sends the key privately.

---

You are working in the **FixMyTech** repository. FixMyTech's FlipValue client (`src/fixmytech/integrations/flipvalue/`)
was written against FixMyTech's own mock of FlipValue (contract `1.0-proposed`). The real FlipValue service now
exists. Your job: make FixMyTech work against it, without weakening FixMyTech's existing validation or
"never invent values" rules. Do not change FlipValue; report any mismatch instead.

## What FlipValue is (as implemented, 0.2.0, contract 1.2-implemented, 2026-10-25)

An independent Python/FastAPI product (website + developer API) that does not depend on FixMyTech; FixMyTech is one
authorised API client. `POST /v1/valuations` is implemented to FixMyTech's request and response schemas
**unchanged**. New since 1.1: API keys carry scopes (yours needs `valuation:read`; operator-issued keys have all
scopes), every response carries `X-RateLimit-*` headers, and an optional richer endpoint
`POST /api/v1/valuations` returns private-sale, buyback, refurbished-retail, original-retail and after-repair values
separately with a confidence class and the repair uplift (see FlipValue's `INTEGRATION_CONTRACT.md` §11 and
`docs/API_REFERENCE.md`). You do not need to switch to it. Values come from a comparable-observations engine (`comparables-v1`): median of
recent prices for the exact model, storage, market and grade; range = 10th–90th percentile (≥ 10 prices) or
min–max (3–9); fewer than 3 → no estimate.

**Critical: FlipValue has no real market data yet.** Locally it runs on synthetic development data and every
response then has `"mock": true` — FixMyTech's live mode correctly rejects that. With `FLIPVALUE_ENV=production`
FlipValue never uses synthetic data, so until real data is imported every valuation returns 404
`no_data_for_condition`. Treat that as the expected "unavailable" path, not a bug.

**Deployment:** prepared for Google Cloud Run (region asia-south1) behind Firebase Hosting, but **not deployed yet —
there is no URL**. When it is, the FlipValue maintainer will send the Cloud Run base URL
(`https://flipvalue-api-…run.app`) and the partner key privately. Use that URL directly as `FLIPVALUE_BASE_URL`
(HTTPS, so FixMyTech's live-mode HTTPS rule is satisfied). The interface does not change with the deployment. First
requests after idle time may be slower (Cloud Run cold start); your 8 s timeout with retries covers it.

## Interface

`POST {FLIPVALUE_BASE_URL}/v1/valuations` with your existing headers: `X-API-Key`, `Content-Type`, `Accept`,
`X-Request-ID` (echoed back), `Idempotency-Key` (same body → identical replayed response with header
`Idempotent-Replayed: true`; same key with a different body → 422 `idempotency_key_reused`),
`FlipValue-API-Version: 1` (other values → 400), `User-Agent`.

Request body exactly as your `schemas.py` sends it. Constraints FlipValue enforces: unknown fields → 422;
`storage_gb`/`age_months` must be JSON integers; region/currency must be `IN`/`INR` or `US`/`USD`.

Response 200 (real local output with synthetic data):

```json
{"api_version": "1", "valuation_id": "val_e2a2d60e7ba7300e991e5fbf", "currency": "INR",
 "as_is": {"value": 8365.0, "low": 6966.0, "high": 9425.0},
 "after_repair": {"value": 21600.0, "low": 19777.0, "high": 22751.0},
 "data_timestamp": "2026-10-18T00:00:00Z", "method": "comparables-v1", "status": "ok",
 "warnings": ["MOCK DATA: these values come from synthetic development data and are not real market prices.",
              "Fault categories are not priced separately; the value reflects grade 'faulty' only.",
              "Device age is not used; the estimate reflects recent prices for this model.",
              "after_repair assumes the battery_replacement is done well and the phone then grades 'good'."],
 "mock": true}
```

* `low`/`high` are always present. `mock` is always present (false in production).
* `after_repair` is `null` when no `repair_scenario` was sent, **or** when the post-repair grade has too little
  evidence; then `status` is `partial` and a warning explains it.
* `status: partial` also means limited evidence (fewer than 10 observations, data older than 90 days, or asking
  prices instead of sales). Show it as lower confidence.
* `data_timestamp` = newest observation used. Values are gross sale prices before fees (your fee logic is correct).
* After repair: `faulty` is valued as `good`; other grades keep their grade.
* Faults and age never change the value; warnings say so. Show warnings verbatim as you already do.

Errors (envelope `{"error": {"code", "message", "request_id"}}`):

| HTTP | code | Your mapping |
|---|---|---|
| 400 | `unsupported_api_version` | rejected_request |
| 401 | `unauthorized` | auth_failed |
| 403 | `insufficient_scope` | auth_failed (the key lacks `valuation:read`) |
| 404 | `unsupported_model` | unsupported_device |
| 404 | `no_data_for_condition` | unsupported_device — **use the message**: it says whether storage is missing or evidence is thin |
| 411 / 413 | `length_required` / `payload_too_large` | should never happen; rejected_request |
| 422 | `validation_error`, `unsupported_region`, `unsupported_currency`, `idempotency_key_reused` | rejected_request |
| 429 | `rate_limited` (+ `Retry-After` 1–60 s) | rate_limited, retried |
| 429 | `quota_exceeded` (only keys with a daily quota) | rate_limited, **not** retried until the next UTC day |
| 503 | `service_timeout` (+ `Retry-After: 1`) | unavailable, retried |
| 500 | `internal_error` | unavailable, not retried |

FlipValue answers in milliseconds locally and times itself out at 5 s, inside your 8 s per-attempt timeout. Your
retry rules (429/502/503/504, timeouts; max 2; Retry-After ≤ 5 s) are compatible. Default limit 60 requests/minute
per key.

## Supported devices and markets

Markets IN/INR, US/USD. Catalogue: Samsung Galaxy S21 (`SM-G991B`, `SM-G991B/DS`, `SM-G991U`; 128/256 GB), Galaxy
S23 (`SM-S911B`, `SM-S911B/DS`, `SM-S911U`; 128/256), Google Pixel 6a (128), Pixel 7 (128/256), Pixel 8 (128/256),
Apple iPhone 13 (128/256/512). Matching ignores case and extra spaces on manufacturer and model. Other OEM codes
(e.g. regional variants) return 404 until FlipValue adds the alias — report the codes you see.

## Required changes in FixMyTech

1. **Send `storage_gb` whenever it is known.** For multi-variant models FlipValue returns 404 without it. If the
   phone report lacks storage, ask the customer before calling FlipValue (or accept the 404 path).
2. Confirm your response model accepts `mock: false` always present and `low`/`high` always present (it should).
3. Confirm your client maps the new codes above (incl. 403 `insufficient_scope` and 429 `quota_exceeded`); nothing
   else in your schemas needs to change. Unknown response headers must be ignored.
4. Keep rejecting `mock: true` in live mode. Do not add any fallback that fabricates a value on 404.
5. Update your `INTEGRATION_CONTRACT.md` to reference FlipValue's `1.1-implemented` and your status docs with what
   you actually verified.

## Test it locally (both repositories on one machine)

In the FlipValue repository (PowerShell; Python 3.11+):

```powershell
python -m venv .venv; .\.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:PYTHONPATH="src"
.\.venv\Scripts\python -m flipvalue setup-dev                      # migrate + catalogue + synthetic data
.\.venv\Scripts\python -m flipvalue keys create --name fixmytech --role partner   # prints the key once
.\.venv\Scripts\python -m uvicorn flipvalue.app:create_app --factory --port 8091
```

In FixMyTech: `FLIPVALUE_MODE=live`, `FLIPVALUE_BASE_URL=http://127.0.0.1:8091`, `FLIPVALUE_API_KEY=<key>` in
`.env` (never committed). Expected: every successful call is rejected by your live client because `mock` is
true — that proves the safety check. To exercise the success path, temporarily point your *mock-mode* tests at this
server, or run FlipValue with `FLIPVALUE_ENV=production` plus `FLIPVALUE_HASH_SALT=<32+ chars>` to see the
production 404 path. Run your `tests/unit/test_flipvalue_client.py` and `tests/integration/test_backend_api.py`,
then the contract's compatibility tests with curl.

## Test against the deployed service (once a URL exists)

Set `FLIPVALUE_MODE=live`, `FLIPVALUE_BASE_URL=<Cloud Run URL>`, `FLIPVALUE_API_KEY=<key>` in FixMyTech's secret
storage. FlipValue's own smoke test can be pointed at it too:
`FLIPVALUE_SMOKE_API_KEY=<key> python scripts/smoke_test.py --api-url <Cloud Run URL>` (in the FlipValue repo).

## Outstanding

Real market data (FlipValue is blocked on authorised access: Flipkart Affiliate API and Amazon Creators API need
approved accounts; Cashify's terms forbid scraping, so only manual quotes; eBay Marketplace Insights needs approval
for the US), the production deployment and key hand-over, alias list for more OEM codes. FixMyTech should keep
making its own repair-versus-replace decision from its repair estimate and FlipValue's values; FlipValue does not
make that decision for you.

## Report back honestly

What you changed, which tests you ran and their real results, every mismatch with FlipValue's behaviour, and what
was verified only against the local server.

---
