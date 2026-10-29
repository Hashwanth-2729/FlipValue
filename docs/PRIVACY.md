# Privacy and retention

Valuing a phone, comparing prices and saving a valuation need **no account** and collect no names, phone numbers,
IMEIs or serial numbers. Accounts exist only for the developer portal (API keys) and the watchlist; they hold an
email address and a password hash.

| Data | Where | Retention | Purpose |
|---|---|---|---|
| Valuation answers (model, storage, market, condition) | Not stored unless saved | — | Compute the valuation |
| Saved valuations (answers + result) | `saved_valuations` | 365 days (`purge`) or until deleted | Shareable link |
| Delete token | Saver's browser (`localStorage`); hash in DB | With the saved valuation | Authorise deletion |
| Account: email (lower-cased), scrypt password hash, creation time | `accounts` | Until the account is deleted by the operator (self-service deletion not implemented yet) | Sign-in |
| Sessions (SHA-256 of the token, expiry) | `account_sessions` | 14 days; expired rows purged | Stay signed in |
| API key metadata (name, prefix, scopes, limits, created/revoked/last-used times; SHA-256 verifier) | `api_clients` | Kept (audit) | Authentication |
| API usage events (key label, time, method, path, status, error code, latency — no IP, no body) | `api_usage_events` | 90 days | Usage statistics, quotas, abuse investigation |
| API valuations (request + result, owner) | `api_valuations` | 365 days | `GET /api/v1/valuations/{id}` |
| Watchlist items and price alerts | `watchlist_items`, `price_alerts` | Until removed by the user (cascade on account deletion) | Price alerts |
| Request log (time, channel, path, status, error code, latency) | `request_log` | 90 days | Metrics |
| Rate-limit counters (salted IP hash, email hash or key label) | `rate_limit_counters` | 48 hours (daily quota windows) | Abuse protection |
| Idempotency records (partner request hash + response) | `idempotency_records` | 24 hours | Safe retries |
| Audit log (account and operator actions) | `audit_log` | Kept | Accountability |
| Market observations and offers (prices, listing titles, seller names as published by marketplaces) | `observations`, `marketplace_offers` | Kept as price history unless a provider's terms require less | Valuations, comparison, history |

Run `python -m flipvalue purge` daily to enforce retention. Exported/shared valuation reports (saved links, print)
contain the phone details and results only — never account data, emails or keys.

The website loads no analytics or third-party scripts; listing links open the marketplace in a new tab with
`noopener noreferrer`. The partner API receives device data only. Not implemented yet: self-service account
deletion and data export (operator can delete an account row; keys, sessions and watchlist cascade).

The website's Privacy and Terms pages are drafts and have not had legal review.
