# Security

Verified by automated tests unless marked otherwise.

| Control | Implementation |
|---|---|
| Partner auth | `X-API-Key`; keys from env (bootstrap) or issued into the DB (`keys create`), stored only as SHA-256; env keys compared in constant time; revocation; ≥ 32-char keys; failure → 401 before the body is read |
| Roles | `partner` keys work only on `/v1`, `admin` keys only on `/admin/api`; a key cannot be both |
| Key rotation | Issue a new key, give it to the client, revoke the old one (`keys revoke <id>`); both work meanwhile |
| Public API | No key; per-IP (salted hash) fixed-window limits: writes `FLIPVALUE_PUBLIC_RATE_LIMIT_PER_MIN`, reads 4×; 429 + `Retry-After` |
| Partner/admin limits | Per key, 60/min and 120/min, shared across processes via the database |
| Request size | 16 KiB (2 MiB for admin CSV import) via `Content-Length`; chunked bodies without length → 411 |
| Timeouts | Per-request `FLIPVALUE_REQUEST_TIMEOUT_S` → 503 `service_timeout` (+ `Retry-After: 1`) |
| Validation | Strict Pydantic models, unknown fields rejected, enums, integer types, region/currency pairs |
| Errors | Uniform envelope with request id; no stack traces or secrets in responses or logs (log records only the exception type) |
| Headers | CSP (`default-src 'self'`, no inline scripts, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on APIs, HSTS in production |
| CORS | Off by default (Firebase Hosting rewrites keep one origin); only exact origins allowed, `*` and non-https production origins rejected at startup |
| Client IP behind proxies | `X-Forwarded-For` entry `FLIPVALUE_PROXY_HOPS` from the right (never the spoofable left-most); a global public limit bounds load even if IPs are spoofed; admin diagnostics endpoint to verify |
| Deployed secrets | Secret Manager → env vars on Cloud Run (DB URL with password, salt, partner and admin keys); dedicated service account with only `cloudsql.client` and per-secret `secretAccessor`; nothing secret in the image, `VITE_` variables or logs |
| Production guards | Startup fails on SQLite, missing salt, or wildcard CORS in production |
| Saved valuations | 128-bit random ids; delete requires a separate 192-bit token held by the saver's browser, stored hashed, compared in constant time; no personal data stored |
| Mock data | Excluded from valuations in production; synthetic ingestion refused in production |
| Admin actions | Audit log (actor, action, details) for source registration, imports, alias changes, key creation/revocation, purges |
| Logging | JSON logs and request log without keys, bodies or IPs; only a key fingerprint label |
| Database | Parameterised SQLAlchemy queries; transaction per request committed before the response |

## Not done / to verify before production

* HTTPS is provided by Firebase Hosting and Cloud Run once deployed; not tested here (no deployment).
* Dependency audit (`pip-audit`, `npm audit`) not run in this session.
* Admin console keeps the admin key in `sessionStorage`; an XSS would expose it. CSP mitigates; consider SSO for admins.
* Rate limits by IP can be evaded with many IPs; there is no CAPTCHA (deliberately — no fake friction).
* No penetration test.

API keys, scopes, quotas, accounts and sessions: see [API_SECURITY.md](API_SECURITY.md).

