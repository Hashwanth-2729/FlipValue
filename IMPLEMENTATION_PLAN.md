# Implementation plan: FlipValue website, valuation platform and FixMyTech API

Written 2026-10-21 after auditing the repository.

## Audit (what existed)

* Python 3.15 / FastAPI service, `src/flipvalue/`: `POST /v1/valuations` (X-API-Key from env, constant-time
  compare, in-memory token-bucket rate limit, `FlipValue-API-Version` check, error envelope, request IDs),
  `GET /health`, OpenAPI.
* Valuation = lookup of one `value/low/high` row per model/region/grade/storage in `data/mock/prices.csv`; no
  statistics, no age use, faults only warned about. Mock rows flagged `mock: true`; production refuses mock rows.
* 63 pytest tests, all passing (run 2026-10-21). No database, no frontend, no git repository, no Docker on this machine.
* Existing contract: FixMyTech's `INTEGRATION_CONTRACT.md` 1.0-proposed + our `FIXMYTECH_CONTRACT_REVIEW.md`.

Everything the README claimed was confirmed in code.

## Real-data investigation (summary; detail in docs/DATA_SOURCES.md)

No legitimately accessible feed of genuine resale prices was available in this session:
eBay Marketplace Insights (sold items) is a limited-release API needing eBay approval; Swappa publishes no
official API; Cashify's terms prohibit systematic retrieval; Back Market's API is for its sellers. **Real data is
blocked.** The pipeline is built for authorized feeds and manual imports; synthetic data is kept for development only.

## Architecture decisions

* **One Python service** serves the partner API (`/v1`), a public JSON API for the website (`/api`), a protected
  admin API (`/admin/api`) and the built website. One valuation engine (`engine.py`) serves all channels.
* **Database:** SQLAlchemy 2 + Alembic. SQLite for local development, PostgreSQL URL for deployment (same
  migrations; PostgreSQL untested here). Catalogue, sources, observations, ingestion jobs, rejected records, API
  clients (hashed keys), idempotency records, saved valuations, rate-limit counters, request log, audit log.
* **Valuation engine `comparables-v1`:** robust statistics over individual observations (median; 10th-90th
  percentile with ≥10 observations, min-max with 3-9; fewer than 3 = insufficient). Exact model and storage only. One
  price basis per estimate, never mixed: completed sales, else asking prices (labelled), synthetic only outside
  production. No invented fault or age adjustments; both disclosed.
* **Frontend:** React + TypeScript + Vite (no framework server needed; built files served by FastAPI, so one origin
  and no CORS in the default deployment). Plain CSS with design tokens, no UI kit. Vitest + Testing Library;
  Playwright against the real backend for end-to-end.
* **Guest-first:** no accounts in this release. Saved valuations are capability links (128-bit random id) with a
  separate delete token kept in the visitor's browser. Accounts are deferred, not faked.
* **Partner contract kept:** same endpoint, headers, fields and codes. Behaviour changes are listed in
  FIXMYTECH_CONTRACT_REVIEW.md (storage now required for multi-variant models; values are medians; new
  `idempotency_key_reused`, `payload_too_large`, `service_timeout`).

## Phases and vertical slice

1. DB models, migrations, catalogue loader, ingestion (adapters, normalisation, dedup, rejects, jobs).
2. Engine + partner API on the engine; keys in DB (hashed) + env; DB-backed rate limits; idempotency; size limit;
   timeouts; readiness; JSON logs; request metrics.
3. Public API: catalogue search, meta, valuation from a customer questionnaire, decision calculator, saved
   valuations, trends (genuine observations only).
4. Admin API + CLI (migrate, load catalogue, import, seed synthetic data, keys, purge).
5. Website: landing, device search, 5-step wizard, results, repair-vs-sell, trends, saved/history, info pages,
   minimal admin page.
6. Tests (pytest, Vitest, Playwright), Dockerfile, docs, partner handoff.

Outcome: phases 1–6 were implemented in this session; see IMPLEMENTATION_STATUS.md for what is tested, partial
or blocked.

---

## Audit and plan, 2026-10-25 (second session)

**Audit findings.** The repository already had a sound core: FastAPI + SQLAlchemy/Alembic + React, an evidence-based
comparables engine, the FixMyTech `/v1/valuations` contract (57 tests), hashed operator-issued keys, DB rate limits,
ingestion with provenance, honest mock labelling. Baseline: pytest 164 passed / 8 skipped, Vitest 20, tsc clean.
Missing or only implied: marketplace offers (no table, no adapters, no matching, no comparison UI), self-service
API keys (no accounts, scopes, per-key quotas, usage, portal), the `/api/v1` surface, watchlists/alerts, buyback /
refurbished / original-retail values. Nothing misleading had to be removed: no fabricated prices were presented as
real.

**Decisions.**
* Keep the stack and the frozen partner contract; add `/api/v1` as a separate surface sharing the engine and keys.
* Offers stored per retrieval in `marketplace_offers` (append-only), so history is a query and nothing is drawn from
  one price. Matching is rule-based with stored reasons; only exact/strong matches enter comparisons.
* Provider research first (Flipkart docs, Amazon's PA-API retirement and Creators API, Cashify terms); adapters
  built to the documented shapes, credentials only server-side, failures isolated per provider.
* Minimal accounts (scrypt + server sessions) instead of a third-party auth service, because the developer portal
  and watchlist need an owner and the stack has no auth framework; documented limitations (no email verification).
* SHA-256 verifiers for 256-bit keys (no slow hash needed), scopes and quotas in the existing middleware, usage
  events in the database.

**Phases done this session:** 1 audit · 2 adapters, provenance, matching, freshness · 3 value types and uplift ·
4 developer platform end to end · 5 comparison, history, watchlist · 6 new visual identity and pages ·
7 tests (pytest, Vitest, Playwright, live HTTP check) and documentation/handoff. Outcome: IMPLEMENTATION_STATUS.md.
