# Testing

## Commands

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python -m pytest                       # backend: unit + API + DB + CLI
.\.venv\Scripts\python -m ruff check src tests scripts # lint
npm --prefix frontend run typecheck
npm --prefix frontend test                             # Vitest + Testing Library (jsdom)
npm --prefix frontend run build                        # needed before e2e
cd frontend; npx playwright test                       # e2e in installed Microsoft Edge (E2E_CHANNEL to change)
```

PostgreSQL: set `FLIPVALUE_TEST_POSTGRES_URL=postgresql+psycopg://user:pw@host:port/postgres` (needs
`pip install -r requirements-deploy.txt`); `tests/test_postgres.py` creates and drops its own database.
Smoke test against a running instance: `python scripts/smoke_test.py --api-url <url> [--site-url <url>]`.

## Results

### 2026-10-25 (this session; Windows 11, Python 3.15.0 + SQLite, Node 24, Edge)

| Suite | Result |
|---|---|
| pytest | **222 passed**, 8 skipped (PostgreSQL tests: no PostgreSQL server in this session) |
| ruff | clean |
| tsc | clean |
| Vitest | **26 passed** |
| Playwright (real backend, fresh DB, synthetic + fixture data) | **9 passed** (8 desktop, 1 mobile 390 px) |
| Manual live check: local uvicorn + migrated dev DB (0001 → 0002 upgrade of an existing database), HTTP script: register → create scoped key → v1 valuation with rate-limit/quota headers → owner GET → scope denial → market prices → partner endpoint with the same key → usage → revoke → 401 | all as expected |

**Not run this session:** PostgreSQL (the 8 skipped tests), the production rehearsal, the Docker build,
`pip-audit`/`npm audit`, load tests, screen readers. **No real marketplace API was called**: provider tests use
`httpx.MockTransport` with fixture responses shaped like the documented APIs.

### 2026-10-22 (previous session)

pytest 172 passed on Python 3.13 + PostgreSQL 16.2; production rehearsal with the smoke test passed. These covered
migration 0001 only; migration 0002 has not been run on PostgreSQL yet.

## What each suite covers

* **Marketplace** (`tests/test_marketplace.py`): Flipkart success with documented fields and header credentials (not
  in the URL), empty results, malformed JSON / missing list, 401, 500, timeouts retried a bounded number of times,
  429 with `Retry-After` capped, missing credentials never calling the network, Amazon token caching and OffersV2
  parsing (no MRP inferred); matching (exact code, strong, variant mismatch, unknown storage, FE/Ultra/+ as
  different models, other brand, single-variant model, RAM not mistaken for storage); one failing provider not
  blocking others, unconfigured provider not called, minimum refresh interval; validation and duplicates; fresh,
  stale and expired; history needing two days, change and gaps, empty state; alerts only for observed qualifying
  prices and not repeated; curated CSV import and bad header; data-quality report; fixtures are mock and link-free.
* **Developer platform** (`tests/test_developer_api.py`): sign-up/in/out and cookie flags, CSRF header, short password,
  closed sign-up, login rate limit; key shown once and stored only as a hash (not in listings or audit log); valid,
  missing, invalid, oversized and revoked keys (incl. on `/v1`); key limit per account; accounts cannot see or revoke
  each other's keys or usage; scopes on every endpoint incl. `/v1`; rate-limit headers and exhaustion; daily quota;
  usage per key and privacy; env keys; health without secrets; v1 valuation value types, owner-only GET, random ids;
  validation (region, currency, grade, identity, unknown model, storage, unknown field); unavailable data; market
  prices with unconfigured adapters, sorting and alternatives; production excludes fixtures; history; products;
  watchlist (duplicate, bad storage, isolation); public valuation value types; admin data-quality, refresh without
  credentials, offer import.
* **Engine** (`tests/test_engine.py`): median/deciles/min–max, freshness, basis priority, no mixing, synthetic
  exclusion, trade-in separation, after-repair, evidence status, trends; v1 value types reproducible with genuine
  fixture observations (confidence high/medium, uplift, dealer offers before trade-in), uplift unavailable without
  post-repair evidence, asking prices → low confidence.
* **Existing suites**: partner contract (57 tests), public/admin API, ingestion, catalogue, migration drift, CLI,
  deploy configuration — unchanged and passing.
* **Frontend component tests**: price comparison (provider status, links with `noopener`, out-of-stock, alternatives,
  honest history state, stock filter, empty groups, fixture label), developer portal (sign-in gate with public docs,
  key creation shown once with CSRF header then hidden), watchlist (prefill, alert explanation) plus the earlier 20.
  These use test fixtures (`src/test/utils.tsx`, `market.test.tsx`), not the backend.
* **End-to-end**: previous journeys plus price comparison on fixture data and a full developer journey in the browser
  (create account → create key → call `/api/v1/valuations` with it → revoke in the UI → 401); no horizontal scroll at
  390 px on `/prices`, `/developers`, `/watchlist`.

## Not tested

Real marketplace data and live provider calls (credentials unavailable), Cloud SQL / Cloud Run / Firebase Hosting,
HTTPS, load, screen readers, browsers other than Edge/Chromium, and the real FixMyTech client against this server.
