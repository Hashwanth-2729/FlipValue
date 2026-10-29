# API security

Covers API keys, scopes, quotas, accounts and the developer portal. General service controls (headers, CSP, body
limits, timeouts, proxies, secrets in deployment) are in [SECURITY.md](SECURITY.md). "Tested" = covered by
`tests/test_developer_api.py`, `tests/test_partner_api.py` or `tests/test_marketplace.py`, all passing on 2026-10-25.

## Key lifecycle

| Step | Implementation | Tested |
|---|---|---|
| Generation | `secrets.token_urlsafe(32)` (OS CSPRNG, 256 bits), prefixed `fv_` | yes |
| One-time display | The raw key is in the create response only; list endpoints, the CLI listing, audit log and logs never contain it | yes |
| Storage | SHA-256 verifier (`api_clients.key_hash`, unique). With 256-bit random keys a fast hash cannot be brute-forced, and lookup stays an indexed equality query; a slow KDF would add latency without security benefit. Keys from the environment are hashed at startup and compared with `hmac.compare_digest` | yes |
| Identification | `key_prefix` = first 10 characters (`fv_` + 7), shown in the portal so owners recognise keys | yes |
| Verification | Every request on `/api/v1` (except health) and `/v1`: hash → lookup → role + revocation check, before the body is parsed | yes |
| Revocation | `revoked_at` set; nothing is cached, so the **next request** is refused (no propagation delay) | yes |
| Rotation | Create a new key, deploy it, revoke the old one; both work in between | yes (CLI + portal) |
| Ownership | Self-service keys belong to an account; another account's key id → 404 on revoke/usage | yes |
| Limit on keys | `FLIPVALUE_MAX_KEYS_PER_ACCOUNT` (default 5) active keys | yes |

## Authorisation

* **Roles:** `partner` keys (incl. all self-service keys) work on `/api/v1` and `/v1`; `admin` keys only on
  `/admin/api`. Admin keys cannot be created from the portal.
* **Scopes** (`valuation:read`, `market_prices:read`, `price_history:read`) are checked server-side per route,
  including on the FixMyTech partner endpoint; missing scope → 403 `insufficient_scope`.
* **Record isolation:** `/api/v1/valuations/{id}` ids are random (`val_` + 144 bits), and a valuation is returned only
  to its owning account (or, for operator keys, the same key). Other owners get the same 404 as unknown ids.
  `/api/v1/usage` only ever describes the calling key.

## Quotas and abuse protection

* Per-key fixed one-minute window and per-key UTC-day quota, counted in `rate_limit_counters` (shared by all
  instances). 429 with `Retry-After`, `X-RateLimit-*` and `X-Quota-*` headers. A burst of up to 2× is possible across
  a window boundary (fixed windows).
* Accounts: sign-in and sign-up are limited to 10 attempts/minute per (salted) IP and 5/minute per email; the
  general public limits apply on top. Unknown emails still run a scrypt verification so timing does not reveal
  which emails exist.
* `FLIPVALUE_DEVELOPER_SIGNUP=closed` disables self-service sign-up (e.g. invite-only launch).
* Not implemented: email verification (no mail delivery is configured), CAPTCHA, anomaly detection. With open
  sign-up, one person can create several accounts; the daily quota per key and the global public limit bound the
  cost. Decide on email verification before a public launch.

## Accounts and sessions

* Passwords: scrypt (n=2^14, r=8, p=1, 16-byte salt), 10–200 characters. Never logged.
* Sessions: 256-bit random token in an `HttpOnly`, `SameSite=Strict`, `Path=/api/account` cookie, `Secure` in
  production (or `FLIPVALUE_SECURE_COOKIES=true`). The database stores only its SHA-256; 14-day expiry; logout
  deletes it; expired sessions are purged.
* CSRF: state-changing account requests must send `X-FlipValue-Client: web`. Cross-site forms cannot set custom
  headers and CORS does not allow it, so forged requests fail even if a browser attached the cookie.

## Secret handling

* No raw key, password, session token or provider credential is written to logs, the request log, the usage log or
  the audit log. The usage log stores the key's non-secret label (`db-<id>-<name>`), path, status and latency.
* Marketplace credentials (`FLIPVALUE_FLIPKART_*`, `FLIPVALUE_AMAZON_*`) are server-side environment variables, sent
  only in request headers to the provider (never in URLs), and never returned by any endpoint — `/api/v1/health` and
  provider status report only *configured / not configured* (tested).
* Nothing secret is committed: `.env` is git-ignored; `.env.example` has empty values; tests generate random keys.

## Development vs production

| | development | production (`FLIPVALUE_ENV=production`) |
|---|---|---|
| Cookies | not `Secure` (http://127.0.0.1) | `Secure` |
| HSTS | off | on |
| Mock/fixture data | used and labelled | excluded from every response |
| Database | SQLite allowed | PostgreSQL required |
| Salt | random per process | `FLIPVALUE_HASH_SALT` required |

HTTPS is terminated by the platform (Cloud Run / Firebase Hosting); FlipValue itself does not serve TLS. Partners
must call the HTTPS URL only.

## Audit events

`audit_log` records: `account.register`, `key.create` (id, prefix, scopes), `key.revoke`, operator `source.register`,
`ingestion.import`, `offers.import`, `offers.refresh`, `catalogue.alias_add`, `purge`. View with
`GET /admin/api/audit`.

## Not verified

No penetration test, no dependency audit in this session, no load test of the database-backed limiter under heavy
traffic.
