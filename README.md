# FlipValue

Independent phone resale intelligence for India (INR) first, with the US as a second market. A consumer website
and a versioned API that answer: what is my phone worth as it is, what could I get from a dealer, what would it be
worth after a repair, what does the same phone cost new or refurbished across sources, and is repairing worth it.
One FastAPI service serves the website, the developer API (`/api/v1`), the FixMyTech partner API (`/v1`) and an
operator API, all on one valuation engine. FixMyTech is an optional client; FlipValue does not depend on it.

> **Data status: no real market data yet.** Marketplace adapters (Flipkart Affiliate API, Amazon Creators API) are
> built and tested against documented response shapes, but need approved accounts that do not exist yet. Development
> runs on synthetic observations and fixture offers, labelled "Mock"/"Fixture" everywhere (`mock: true` in the API)
> and excluded in production. See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Run locally

Requirements: Python 3.11+ (tested 3.15), Node 20+ (tested 24). PowerShell shown; bash is analogous.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:PYTHONPATH = "src"
.\.venv\Scripts\python -m flipvalue setup-dev          # migrate, catalogue, synthetic observations + fixture offers

npm --prefix frontend ci
npm --prefix frontend run build                         # served by the backend from frontend/dist

.\.venv\Scripts\python -m uvicorn flipvalue.app:create_app --factory --port 8091
```

| URL | What |
|---|---|
| http://127.0.0.1:8091/ | Website: value a phone, compare prices, repair or sell, trends, watchlist |
| http://127.0.0.1:8091/developers | Developer portal: account, API keys (shown once), usage, revoke, reference |
| http://127.0.0.1:8091/api/v1/… | Developer API (`X-API-Key` with scopes) — [docs/API_REFERENCE.md](docs/API_REFERENCE.md) |
| http://127.0.0.1:8091/v1/valuations | FixMyTech partner API — [INTEGRATION_CONTRACT.md](INTEGRATION_CONTRACT.md) |
| http://127.0.0.1:8091/admin | Operator console (admin key: `python -m flipvalue keys create --name me --role admin`) |
| /docs, /health, /ready | OpenAPI reference, liveness, readiness |

Frontend hot reload: run the backend, then `npm --prefix frontend run dev` (http://127.0.0.1:5173, proxies to 8091).

## Operator commands

`python -m flipvalue` + `migrate` · `release` · `load-catalogue` · `seed-mock` (dev only) · `register-source …` ·
`import --source ID file.csv` (resale observations) · `import-offers --source ID file.csv` (curated offers / buyback
quotes) · `providers` · `refresh-offers [--model ID --storage GB]` · `keys create|list|revoke` (`--scopes`,
`--rate-limit`, `--daily-quota`) · `purge` · `serve`. Configuration: [.env.example](.env.example),
[docs/ENVIRONMENT.md](docs/ENVIRONMENT.md).

## Tests

`python -m pytest` · `npm --prefix frontend test` · `cd frontend; npx playwright test` (Edge, real backend).
Latest results: [docs/TESTING.md](docs/TESTING.md).

## Deploying

Firebase Hosting + Cloud Run + Cloud SQL: [DEPLOYMENT.md](DEPLOYMENT.md) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
(scheduled offer refresh, purge). **Not deployed yet.** Not production-ready: no real data, migration 0002 untested
on PostgreSQL, no email verification for accounts.

## Documentation

| Document | Contents |
|---|---|
| [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) | What is tested, implemented, partial, missing or blocked |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Audits and plans |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, routes, data model |
| [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md), [docs/DATA_QUALITY.md](docs/DATA_QUALITY.md) | Providers, access requirements, validation, matching, data-quality report |
| [docs/VALUATION_METHODOLOGY.md](docs/VALUATION_METHODOLOGY.md) | `comparables-v1`, value types, confidence |
| [docs/API_REFERENCE.md](docs/API_REFERENCE.md), [docs/API_SECURITY.md](docs/API_SECURITY.md) | Developer API; keys, scopes, quotas, accounts |
| [docs/SECURITY.md](docs/SECURITY.md), [docs/PRIVACY.md](docs/PRIVACY.md) | Service controls; data and retention |
| [docs/TESTING.md](docs/TESTING.md), [docs/LIMITATIONS.md](docs/LIMITATIONS.md) | Tests and results; known limits |
| [INTEGRATION_CONTRACT.md](INTEGRATION_CONTRACT.md), [PARTNER_HANDOFF.md](PARTNER_HANDOFF.md), [PARTNER_HANDOFF_PROMPT.md](PARTNER_HANDOFF_PROMPT.md) | FixMyTech integration |
