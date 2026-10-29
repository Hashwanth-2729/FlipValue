# Architecture

## Overview

Deployed shape (prepared, see [../DEPLOYMENT.md](../DEPLOYMENT.md)): Firebase Hosting serves the built website and
rewrites `/api`, `/v1`, `/admin/api` to a Cloud Run service running this FastAPI app; Cloud SQL for PostgreSQL holds
the data; Secret Manager holds secrets. Locally, one FastAPI process serves everything:

```
 Browser ──HTTPS──▶ FlipValue service (FastAPI)
                     ├─ /                 built React website (frontend/dist)
                     ├─ /api/*            website API (anonymous, per-IP limits) incl. /api/market/*
                     ├─ /api/account/*    accounts: sessions, self-service keys, usage, watchlist, alerts (cookie)
                     ├─ /api/v1/*         developer API (X-API-Key + scopes, per-key minute limit + daily quota)
                     ├─ /v1/valuations    FixMyTech partner contract (X-API-Key, valuation:read)
                     ├─ /admin/api/*      operator API (admin-role key)
                     └─ /health /ready /docs /openapi.json
 FixMyTech / other servers ──HTTPS──▶ /v1/valuations or /api/v1/*
 Scheduler / operator ──CLI──▶ refresh-offers ──HTTPS──▶ Flipkart Affiliate API, Amazon Creators API
                                                  ▼
                       SQLite (dev) / PostgreSQL (deploy) via SQLAlchemy + Alembic
```

One valuation engine (`engine.py`) serves every channel; the frontend has no pricing logic. Provider calls never
happen inside a customer request: offers are fetched by `refresh-offers` (CLI/scheduler) or the operator's refresh
button, and requests read stored offers.

## Backend modules (`src/flipvalue/`)

| Module | Responsibility |
|---|---|
| `app.py` | App factory; middleware: request ids, body limits, channel auth (admin / partner / developer), per-key minute limits and daily quotas with headers, scope check on `/v1`, timeouts, security headers, request log, usage events |
| `routes/developer.py` | `/api/v1`: health, valuations (create/get, owner-only), market prices, price history, products, usage |
| `routes/account.py` | Sign-up/in/out, keys (create once-shown, list, revoke, usage), watchlist, alerts; CSRF header check |
| `routes/market.py` | Website price comparison, provider status, history (shared with `/api/v1`) |
| `routes/partner.py` | `POST /v1/valuations` (FixMyTech contract), idempotency |
| `routes/public.py` | Website: meta, catalogue, questionnaire valuations (+ value types), decision, saved, trends |
| `routes/admin.py` | Sources, jobs, rejects, CSV imports (observations and offers), aliases, metrics, audit, providers, offer refresh, data-quality report |
| `engine.py` | Comparable selection, statistics, quality, after-repair, evidence status, trends |
| `services.py` | Partner, website and v1 outputs; value types (buyback, refurbished retail, original retail), confidence |
| `marketplace/providers.py` | Provider protocol; Flipkart Affiliate, Amazon Creators, Cashify (manual-only) adapters; bounded retries |
| `marketplace/matching.py` | Product identity: exact / strong / variant / similar / unmatched with score and reasons |
| `marketplace/service.py` | Refresh (per-provider isolation, validation, dedup, matching), comparison, history, alerts, curated CSV, fixtures, data-quality report |
| `accounts.py` | scrypt passwords, session tokens |
| `security.py` | Key generation/verification (`KeyInfo`, scopes), DB-backed fixed-window limiter, IP fingerprints |
| `condition.py`, `decision.py`, `catalogue.py`, `ingestion/`, `db/`, `observability.py`, `cli.py` | As before: questionnaire → grade, repair-vs-sell arithmetic, catalogue, observation ingestion, persistence, logs, operator commands |

## Data model

Migration `0001`: catalogue (`device_models`, `model_aliases`, `model_variants`), `sources`, `ingestion_jobs`,
`rejected_records`, `observations`, `api_clients`, `idempotency_records`, `saved_valuations`, `rate_limit_counters`,
`request_log`, `audit_log`.

Migration `0002` (2026-10-25): `accounts`, `account_sessions`; `api_clients` + `account_id`, `scopes`,
`rate_limit_per_minute`, `daily_quota`, `last_used_at` (existing partner keys get all scopes); `api_usage_events`;
`api_valuations`; `marketplace_offers` (provenance, raw record, normalised fields, match category/score/reasons,
unique `dedup_key`, lookup index); `watchlist_items` (unique per account/model/storage/condition); `price_alerts`.
A test checks the migrations match the models.

## Frontend (`frontend/`)

React 18 + TypeScript + Vite, React Router, plain CSS tokens (light/dark), SVG charts, no UI kit.
Visual identity: warm paper background, ink text, terracotta accent, serif display headings, tabular figures.

| Route | Page |
|---|---|
| `/` | Landing |
| `/value` | 5-step valuation wizard → result with value types |
| `/prices` | Price comparison: sources and their status, new/refurbished/used/buyback tabs, filters, match details, alternatives, observed history |
| `/compare` | Repair-or-sell calculator |
| `/trends` | Monthly resale medians (genuine data only) |
| `/watchlist` | Sign-in, watched products with targets, alerts |
| `/developers` | Developer portal: sign-in, key creation (shown once), key list, usage, revoke, reference, examples, errors |
| `/saved`, `/v/:id` | Saved valuations and shareable/printable report |
| `/devices`, `/methodology`, `/data-sources`, `/privacy`, `/terms`, `/about`, `/api`, `/contact` | Information |
| `/admin` | Operator console incl. provider status, offer refresh, offer import and data-quality report |

## Key decisions

* **Single service, single origin:** no CORS by default; the browser never holds an API key.
* **Accounts are minimal and optional** (email + scrypt + server-side sessions); valuing a phone never needs one.
* **Keys are SHA-256 verifiers of 256-bit random secrets** (see API_SECURITY.md for why no slow hash).
* **Rate limits and quotas in the database:** shared across processes without Redis; fixed windows.
* **Offers are append-only retrievals**, which makes price history a query, not a separate fabricated series.
* **FixMyTech contract frozen:** `/v1/valuations` keeps its shape; richer data is a separate `/api/v1` endpoint.
