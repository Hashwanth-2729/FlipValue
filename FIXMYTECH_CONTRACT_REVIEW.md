# FlipValue's answers to the FixMyTech integration contract

For the FixMyTech maintainer. Reviewed against `INTEGRATION_CONTRACT.md` 1.0-proposed (FixMyTech v0.2.0).
**Updated 2026-10-21 for FlipValue 0.2.0**; the implemented contract is FlipValue's `INTEGRATION_CONTRACT.md`
(`1.1-implemented`). Verified locally only; nothing is deployed.

## Answers to the open questions (contract §9)

| # | Question | FlipValue's answer |
|---|---|---|
| 1 | Endpoint and auth header | As proposed: `POST /v1/valuations`, `X-API-Key` |
| 2 | Model identification | Catalogue with aliases: OEM codes and marketing names, matched ignoring case/extra spaces. Storage is part of identity: required for models with several sizes. Public list at `GET /api/catalogue` |
| 3 | Regions and currencies | `IN`→`INR`, `US`→`USD`; no conversion; others → 422 `unsupported_region` / `unsupported_currency` |
| 4 | Grades and faults | §6 definitions accepted. Faults do not change the value (no evidence for fault discounts); a warning says so |
| 5 | `after_repair` and ranges | `faulty`→`good`, other grades unchanged. Range = 10th–90th percentile of comparables (≥ 10), min–max (3–9) |
| 6 | Price type | Gross private/marketplace sale price before fees; completed sales preferred, asking prices only as labelled fallback |
| 7 | Rate limits and keys | 60/min per key (429 + `Retry-After`); keys issued by CLI, hashed, revocable, several active for rotation; handed over privately |
| 8 | Staging URL | None yet |

## Behaviour changes since the first review (0.1.0)

* **Comparables engine** replaces the price table: medians of individual observations, `method: comparables-v1`.
* **Storage required** for multi-variant models (was: a storage-agnostic row could match).
* **`status: partial`** now also flags limited evidence.
* **`low`/`high` always present**; `data_timestamp` = newest observation used.
* **Additions:** `idempotency_key_reused` (422, idempotency is now stored for 24 h), `payload_too_large` (413),
  `length_required` (411), `service_timeout` (503, retryable), `internal_error` (500). DB-issued keys; admin keys
  are refused on `/v1`.

## Still blocking live use

No real market data: production returns `no_data_for_condition` until an authorised source is imported, and
development responses are `mock: true` (which FixMyTech's live client correctly rejects).

See `PARTNER_HANDOFF_PROMPT.md` for the step-by-step integration instructions.
