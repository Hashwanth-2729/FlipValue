# Partner handoff: FlipValue → FixMyTech

For the FixMyTech maintainer and their AI assistant. Prepared 2026-10-25 from FlipValue as implemented (0.2.0,
contract `1.2-implemented`). Binding interface details: [INTEGRATION_CONTRACT.md](INTEGRATION_CONTRACT.md). A
copy-paste prompt for FixMyTech's assistant: [PARTNER_HANDOFF_PROMPT.md](PARTNER_HANDOFF_PROMPT.md). FixMyTech's own
handoff to FlipValue is in `FlipValue/My Friend's Project Status and Details/`.

Legend: **Working** = implemented and tested here · **Blocked** = needs something outside this repository.

## 1. What FlipValue is now

An independent consumer product (website + API) for the Indian market first: phone resale valuations from comparable
prices, separate buyback / refurbished-retail / original-retail values, cross-marketplace price comparison with
product matching, observed price history, watchlists, and a self-service developer platform with scoped API keys.
FixMyTech is one optional client; FlipValue does not depend on it.

## 2. Status that matters to FixMyTech

| Item | Status |
|---|---|
| `POST /v1/valuations` (your contract, unchanged shape) | **Working** — 57 contract tests + scope tests |
| Scoped keys, rate-limit headers, revocation on next request | **Working** |
| Optional richer `POST /api/v1/valuations` (value types, uplift, confidence) | **Working** |
| Real market data | **Blocked** — no authorised source connected (Flipkart Affiliate approval, Amazon Creators API approval, Cashify data agreement or manual quotes, eBay approval for US). Production therefore answers 404 `no_data_for_condition` (on `/v1`) or `available: false` (on `/api/v1`) |
| HTTPS deployment and production URL | **Blocked** — prepared for Cloud Run (asia-south1), not deployed; needs the owner's Google Cloud account |
| End-to-end test with the real FixMyTech client | **Blocked** — FixMyTech repository not available here |

## 3. Interface summary

* Base URL: production — not yet; local — `http://127.0.0.1:8091`. API version `1` (`FlipValue-API-Version: 1`).
* Auth: `X-API-Key: <key>`; key needs `valuation:read`. Keys for FixMyTech are issued by the FlipValue operator
  (`python -m flipvalue keys create --name fixmytech --role partner`) and sent privately, or created by the FixMyTech
  maintainer in the FlipValue developer portal (`/developers`).
* Request: `device{manufacturer, model, storage_gb?, age_months?}`, `region`, `currency`, `condition{grade, faults}`,
  `repair_scenario{repair_type}?`. Send `storage_gb` whenever known.
* Response (`/v1`): `as_is{value,low,high}`, `after_repair` or null, `status` (`ok`/`partial`), `warnings`,
  `data_timestamp`, `method`, `mock`, `valuation_id`. Gross sale price before selling fees, in the requested currency.
* Errors: envelope `{"error":{"code","message","request_id"}}`; 400, 401, 403 `insufficient_scope`, 404, 411, 413,
  422, 429 (`rate_limited`, `quota_exceeded`), 503 `service_timeout`, 500.
* Limits: 60 requests/minute per key by default; no daily quota on operator-issued keys.
* Timeouts: FlipValue answers within 5 s or returns 503 (safe to retry). FixMyTech's 8 s timeout, 2 retries and
  `Retry-After` ≤ 5 s handling are compatible.
* Device identity: exact (case- and space-insensitive) match on catalogue names and OEM codes; unknown codes → 404
  `unsupported_model`. Catalogue lookup: `GET /api/v1/products?q=`.
* Currency: `IN`→`INR`, `US`→`USD`; no conversion.
* Provenance: `data_timestamp` = newest observation used; `/api/v1` also returns sources, observation counts and dates.

## 4. Environment variables on the FixMyTech side

`FLIPVALUE_MODE=live`, `FLIPVALUE_BASE_URL=<https URL>`, `FLIPVALUE_API_KEY=<key>` (secret storage only),
`FLIPVALUE_TIMEOUT_S=8`, `FLIPVALUE_MAX_RETRIES=2`, `FLIPVALUE_API_VERSION=1`.

## 5. Example: success (local, synthetic data — so `mock: true`)

```bash
curl -s -X POST "$FLIPVALUE_BASE_URL/v1/valuations" -H "X-API-Key: $FLIPVALUE_API_KEY" \
  -H "Content-Type: application/json" -H "FlipValue-API-Version: 1" -H "Idempotency-Key: $(uuidgen)" \
  -d '{"device":{"manufacturer":"samsung","model":"SM-G991B","storage_gb":128},"region":"IN","currency":"INR",
       "condition":{"grade":"faulty","faults":["display_damage"]},"repair_scenario":{"repair_type":"screen_replacement"}}'
```

```json
{"api_version":"1","valuation_id":"val_…","currency":"INR",
 "as_is":{"value":8365.0,"low":6966.0,"high":9425.0},"after_repair":{"value":21600.0,"low":19777.0,"high":22751.0},
 "data_timestamp":"2026-10-…T00:00:00Z","method":"comparables-v1","status":"ok",
 "warnings":["MOCK DATA: …","Fault categories are not priced separately; …","after_repair assumes …"],"mock":true}
```

## 6. Example errors

```json
401 {"error":{"code":"unauthorized","message":"Missing or invalid X-API-Key.","request_id":"…"}}
403 {"error":{"code":"insufficient_scope","message":"This key does not have the valuation:read scope.","request_id":"…"}}
404 {"error":{"code":"no_data_for_condition","message":"storage_gb is required for Galaxy S21: prices differ by storage (128, 256 GB) …","request_id":"…"}}
429 {"error":{"code":"rate_limited","message":"Too many requests; retry later.","request_id":"…"}}   + Retry-After
```

## 7. What FixMyTech should do

1. Keep calling `/v1/valuations`; send `storage_gb` whenever known.
2. Map 403 `insufficient_scope` to `flipvalue_auth_failed`, 429 `quota_exceeded` to `flipvalue_rate_limited`
   (do not retry within the day).
3. Keep rejecting `mock: true` in live mode; never fabricate a value on 404.
4. Optionally use `/api/v1/valuations` for buyback/refurbished values and the repair uplift with confidence.
5. Calculate repair-versus-replace on the FixMyTech side from your repair estimate and these values.
6. Run your client tests against a local FlipValue (PARTNER_HANDOFF_PROMPT.md), then against staging once deployed,
   and record what was actually verified.

## 8. Still pending on FlipValue's side

Real data sources (approvals), deployment and key hand-over, more OEM aliases (send the codes you see), email
verification for self-service accounts.
