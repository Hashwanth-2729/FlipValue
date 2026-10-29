# Partner handoff: FixMyTech → FlipValue

Prepared 2026-10-19 from the FixMyTech code as implemented (version 0.1.0); **re-checked against v0.2.0 the same day:
the FlipValue interface did not change** (only the User-Agent version). What changed around it: FixMyTech now uses
official manufacturer repair prices (Samsung India, before GST) with source links, adds hands-on hardware tests, and
defaults to the Indian market, so most real requests will be `region: IN`, `currency: INR`. For the FlipValue maintainer and their
AI assistant. The binding interface details are in [INTEGRATION_CONTRACT.md](INTEGRATION_CONTRACT.md); this document
gives the context around them.

Legend: **Implemented** = exists and is tested in FixMyTech · **Proposed** = FixMyTech's proposal, depends on it ·
**Awaiting agreement** = needs a decision from FlipValue.

## 1. Product overview

FixMyTech is an independent consumer web app that diagnoses Android phone problems (USB scan through a local agent +
adaptive questions + rule-based evidence fusion), estimates repair costs, and compares *repair and keep*, *sell as-is
and replace*, *sell as-is now* and *repair then sell*. It needs resale values, which FlipValue provides: the value of
the phone **as it is** and **after a specified repair**.

## 2. Implemented architecture (relevant parts)

* Python 3.11+ / FastAPI backend; the FlipValue client runs **server-side only**
  (`src/fixmytech/integrations/flipvalue/client.py`). The browser never sees the key or calls FlipValue.
* One HTTP call per customer valuation request: `POST {FLIPVALUE_BASE_URL}/v1/valuations`.
* Request/response validated with Pydantic models (`schemas.py`). The same models generate
  `docs/flipvalue-contract.openapi.json`.
* A MOCK FlipValue (`mock_server.py`, port 8090) implements the proposed contract for FixMyTech's development and
  tests. Its numbers are a toy formula; every mock response says `"mock": true`.

## 3. FixMyTech endpoints that matter to FlipValue

FlipValue does not call FixMyTech. For context, the customer-facing FixMyTech endpoints that trigger or use valuations:

| Endpoint | Status | Role |
|---|---|---|
| `GET /api/v1/sessions/{id}/valuation` | Implemented | Shows stored valuation + suggested condition |
| `POST /api/v1/sessions/{id}/valuation` | Implemented | Builds the FlipValue request, calls FlipValue, stores the outcome |
| `POST /api/v1/sessions/{id}/decision` | Implemented | Uses `as_is` / `after_repair` (value + low/high) |
| `GET /api/v1/health` | Implemented | Shows FlipValue mode/config status (no secrets) |

## 4. Expected FlipValue API behaviour

| Element | Detail | Status |
|---|---|---|
| Endpoint | `POST /v1/valuations`, JSON | Proposed / awaiting agreement |
| Auth | `X-API-Key: <key>` header; 401/403 on failure | Implemented in client / awaiting agreement |
| Required request fields | `device.manufacturer`, `device.model`, `region`, `currency`, `condition.grade`, `condition.faults` | Implemented in client |
| Optional request fields | `device.storage_gb`, `device.age_months`, `repair_scenario.repair_type` (omitted when unknown) | Implemented in client |
| Response fields | `api_version`, `valuation_id`, `currency`, `as_is{value,low?,high?}`, `after_repair` (when repair requested), `data_timestamp`, `method`, `status` (`ok`/`partial`), `warnings[]` | Validated by client / proposed |
| Money | major units, JSON numbers, **gross sale price before selling fees**, `low ≤ value ≤ high`, ≥ 0 | Proposed |
| Currency | respond in the requested ISO 4217 currency; FixMyTech never converts | Proposed |
| Errors | `{"error":{"code","message","request_id"}}`; 400/422 invalid, 404 unsupported model, 429 + `Retry-After`, 503 unavailable | Proposed |
| Idempotency | same `Idempotency-Key` on retries; endpoint side-effect free | Implemented in client / proposed |
| Mock flag | real service must never return `mock: true` (live client rejects it) | Implemented |

## 5. Configuration variables (FixMyTech side)

`FLIPVALUE_MODE` (`disabled`|`mock`|`live`), `FLIPVALUE_BASE_URL`, `FLIPVALUE_API_KEY`, `FLIPVALUE_TIMEOUT_S` (8),
`FLIPVALUE_MAX_RETRIES` (2), `FLIPVALUE_API_VERSION` (1). Live mode requires https (except localhost).

## 6. Timeouts and retries (implemented)

8 s per attempt; retries only on timeouts, connection errors, 429, 502, 503, 504; max 2 retries; backoff 0.5 s then
1 s; `Retry-After` honoured up to 5 s. 400/401/403/404/422 and other 5xx are not retried.

## 7. Error handling (implemented)

FixMyTech maps failures to `flipvalue_auth_failed`, `flipvalue_unsupported_device`, `flipvalue_rejected_request`,
`flipvalue_rate_limited`, `flipvalue_timeout`, `flipvalue_unavailable`, `flipvalue_invalid_response`. In every case the
customer keeps their diagnosis and repair estimate, no value is invented, and they may enter values manually (labelled
"Entered by you").

## 8. Device and condition categories

* Device identity: manufacturer as reported by Android (`samsung`, `Google`, often lowercase) or typed by a customer;
  model often an OEM code (`SM-G991B`, `Pixel 7`). **Awaiting agreement:** how FlipValue wants models identified.
* Grades: `excellent`, `good`, `fair`, `poor`, `faulty` (definitions in the contract §6). **Awaiting agreement.**
* Fault categories (implemented, from FixMyTech's taxonomy): `software_instability`, `storage_pressure`,
  `battery_wear`, `charging_path`, `display_damage`, `camera_fault`, `audio_fault`, `connectivity_issue`,
  `liquid_damage`. They are **likely** faults (moderate/strong evidence), not technician-confirmed.

## 9. Repair types (implemented)

`battery_replacement`, `charging_port_replacement`, `screen_replacement`, `camera_module_replacement`,
`audio_component_replacement`, `liquid_damage_service`, `software_reset`.

## 10. Currency handling

FixMyTech markets (configurable `FIXMYTECH_MARKETS`): `IN` → `INR` (default; official repair prices available), `US` → `USD`. It requests values in that currency and
refuses to compare amounts in different currencies (`currency_mismatch`).

## 11. Data validation

FixMyTech validates every response (types, ranges, `low ≤ value ≤ high`, ISO currency and timestamp, status enum);
any violation → `flipvalue_invalid_response`, value discarded. FlipValue should validate requests equally strictly and
answer 422 with the error envelope.

## 12. Integration test examples

```bash
# success (with repair scenario)
curl -X POST "$FLIPVALUE_BASE_URL/v1/valuations" -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"device":{"manufacturer":"Samsung","model":"SM-G991B","storage_gb":128,"age_months":34},
       "region":"US","currency":"USD","condition":{"grade":"faulty","faults":["battery_wear"]},
       "repair_scenario":{"repair_type":"battery_replacement"}}'
# expect 200 with as_is and after_repair in USD

# bad key -> 401 ; unknown model -> 404 ; grade "mint" -> 422 ; omit repair_scenario -> after_repair null
```

FixMyTech's automated client tests: `tests/unit/test_flipvalue_client.py`, `tests/integration/test_backend_api.py`.

## 13. Known limitations (FixMyTech)

* Tested only against its own MOCK server; never against the real FlipValue.
* Fault categories are probabilistic suggestions, not confirmed defects.
* Device age is a customer estimate; storage may be missing.
* No currency conversion.

## 14. Outstanding decisions

See INTEGRATION_CONTRACT.md §9: endpoint/auth naming, model identification, regions/currencies, grade semantics,
`after_repair` semantics and range definition, price type (private sale vs trade-in), rate limits and key issuance,
staging URL.

## 15. Exact steps to connect FlipValue

1. FlipValue implements or adapts `POST /v1/valuations` to the contract (or proposes changes in writing).
2. Both sides agree the open questions; FixMyTech updates `schemas.py` + `INTEGRATION_CONTRACT.md` if needed.
3. FlipValue deploys to an HTTPS staging URL and issues an API key to FixMyTech (shared privately, never in git or chat logs).
4. FixMyTech sets `FLIPVALUE_MODE=live`, `FLIPVALUE_BASE_URL`, `FLIPVALUE_API_KEY` in `.env`.
5. Run the compatibility tests in the contract §8 from both sides; fix mismatches.
6. FixMyTech runs a full UI journey and checks the report shows "Live FlipValue".
7. Both update their status documents with what was actually verified.
