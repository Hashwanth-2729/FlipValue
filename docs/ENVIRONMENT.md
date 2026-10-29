# Environment variables

Read once at startup by `Settings.from_env()` (`src/flipvalue/config.py`). Values are trimmed, so a trailing newline
from Secret Manager is harmless. Invalid combinations stop the server at startup with a clear message.

## Backend (Cloud Run service and migration job)

| Variable | Production value | Set via | Default | Notes |
|---|---|---|---|---|
| `FLIPVALUE_ENV` | `production` | image (`Dockerfile`) | `development` | Production refuses mock data and SQLite, needs the salt |
| `FLIPVALUE_DATABASE_URL` | `postgresql+psycopg://flipvalue:<pw>@/flipvalue?host=/cloudsql/<project>:<region>:<instance>` | **Secret Manager** `flipvalue-database-url` | local SQLite | Contains the DB password |
| `FLIPVALUE_HASH_SALT` | 43-char random | **Secret Manager** `flipvalue-hash-salt` | — | Required in production; same for all instances |
| `FLIPVALUE_API_KEYS` | partner key(s), comma-separated | **Secret Manager** `flipvalue-partner-keys` | empty | ≥ 32 chars each; two during rotation |
| `FLIPVALUE_ADMIN_KEYS` | admin key(s) | **Secret Manager** `flipvalue-admin-keys` | empty | Never the same as a partner key |
| `FLIPVALUE_TRUST_PROXY` | `true` | image | `false` | Cloud Run always sits behind Google's front end |
| `FLIPVALUE_PROXY_HOPS` | `1` until verified | `--set-env-vars` | `1` | Verify with `GET /admin/api/diagnostics/forwarding` through Firebase Hosting |
| `FLIPVALUE_DB_POOL_SIZE` / `FLIPVALUE_DB_MAX_OVERFLOW` | `3` / `2` | `--set-env-vars` | `5` / `2` | (pool + overflow) × max instances < DB connection limit |
| `FLIPVALUE_RATE_LIMIT_PER_MIN` | `60` | `--set-env-vars` | `60` | Per partner key |
| `FLIPVALUE_PUBLIC_RATE_LIMIT_PER_MIN` | `30` | `--set-env-vars` | `30` | Website writes per client IP (reads 4×) |
| `FLIPVALUE_PUBLIC_GLOBAL_RATE_LIMIT_PER_MIN` | `600` | `--set-env-vars` | `600` | All website writes together (reads 4×) |
| `FLIPVALUE_MAX_BODY_BYTES` | `16384` | default | `16384` | Admin CSV import allows 2 MiB |
| `FLIPVALUE_REQUEST_TIMEOUT_S` | `5` | default | `5` | Below Firebase Hosting's 60 s and FixMyTech's 8 s |
| `FLIPVALUE_FRESHNESS_DAYS` | `180` | default | `180` | Comparable window |
| `FLIPVALUE_CORS_ORIGINS` | empty | `--set-env-vars` if needed | empty | Only if the website calls the API cross-origin; exact https origins |
| `FLIPVALUE_FRONTEND_DIST` | unset | — | `frontend/dist` | Not in the API image; the website is on Firebase Hosting |
| `FLIPVALUE_ALLOW_SQLITE_IN_PRODUCTION` | **never set** | — | `false` | Local rehearsals only |
| `PORT` | set by Cloud Run | platform | `8080` | `python -m flipvalue serve` binds `0.0.0.0:$PORT` |

## Website build (Firebase Hosting)

| Variable | Value | Notes |
|---|---|---|
| `VITE_API_BASE_URL` | empty | Same origin via Hosting rewrites. If set (https only), it is added to the page's CSP `connect-src` and the API must list the website in `FLIPVALUE_CORS_ORIGINS`. Public: never put secrets in `VITE_` variables |

## Smoke test

| Variable | Notes |
|---|---|
| `FLIPVALUE_SMOKE_API_KEY` | Partner key used by `scripts/smoke_test.py`; read from the environment so it is not in shell history |

## Added 2026-10-25: marketplace providers and developer platform

| Variable | Default | Production | Purpose |
|---|---|---|---|
| `FLIPVALUE_FLIPKART_AFFILIATE_ID`, `FLIPVALUE_FLIPKART_AFFILIATE_TOKEN` | empty | Secret Manager | Flipkart Affiliate API credentials |
| `FLIPVALUE_AMAZON_CREDENTIAL_ID`, `_CREDENTIAL_SECRET`, `_PARTNER_TAG`, `_TOKEN_URL` | empty | Secret Manager (ID/secret), env (tag, URL) | Amazon Creators API |
| `FLIPVALUE_PROVIDER_TIMEOUT_S` | 8 | env | Per provider HTTP call; up to 2 retries |
| `FLIPVALUE_PROVIDER_MIN_REFRESH_MINUTES` | 60 (min 15) | env | Minimum interval per provider and product |
| `FLIPVALUE_OFFER_FRESH_HOURS` / `FLIPVALUE_OFFER_MAX_AGE_DAYS` | 24 / 14 | env | Freshness labels; current-offer window |
| `FLIPVALUE_DEVELOPER_SIGNUP` | open | env | `closed` disables self-service accounts |
| `FLIPVALUE_DEVELOPER_RATE_LIMIT_PER_MIN` / `FLIPVALUE_DEVELOPER_DAILY_QUOTA` | 60 / 1000 | env | Defaults for self-service keys |
| `FLIPVALUE_MAX_KEYS_PER_ACCOUNT` | 5 | env | Active keys per account |
| `FLIPVALUE_SECURE_COOKIES` | false | not needed (forced on in production) | Secure session cookie outside production |
