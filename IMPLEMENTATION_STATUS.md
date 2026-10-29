# Implementation status

**As of 2026-10-25, FlipValue 0.2.0 (contract 1.2-implemented).** Only what was run is reported as tested. Not
production-ready: no real market data, not deployed, migration 0002 not run on PostgreSQL.

Legend: **tested** = implemented, automated tests pass · **verified live** = also exercised on a running local
server · **implemented** = works, no dedicated test · **partial** · **missing** · **blocked** (external dependency).

## Market data

| Feature | Status |
|---|---|
| Provider-independent adapter interface (search, normalise, timeouts, bounded retries, error classes, status) | tested |
| Flipkart Affiliate API adapter | tested against documented-shape fixtures; **blocked** live: needs approved affiliate id + token |
| Amazon.in Creators API adapter (PA-API 5 retired 2026-04-30) | tested against fixtures; **blocked** live: needs Associates approval + credentials; field names unverified against a live response |
| Cashify | **blocked**: terms prohibit systematic retrieval → manual quotes only (CSV import implemented, tested) |
| Manufacturer stores, refurbishers, OLX India | **missing** (not yet researched in depth) |
| Offer storage with provenance, raw record, normalised fields, retrieval time, match data | tested |
| Validation, de-duplication, rejects with reasons | tested |
| Per-provider isolation (one failing provider never blocks others) | tested |
| Minimum refresh interval per provider and product | tested |
| Scheduled refresh | implemented as CLI `refresh-offers`; schedule documented, **not configured** (no deployment) |
| Freshness (fresh/stale/expired) | tested |
| Product identity and matching (exact / strong / variant / similar / unmatched with reasons) | tested |
| Synthetic observations + fixture offers for development, excluded in production | tested |
| Real offers from manual price checks: 2026-10-27, 2 new retail (Flipkart) and 11 refurbished (Cashify, Budli, Easyphones) for the original 6 models; 2026-10-28, 25 refurbished (Cashify) for 25 new catalogue models, one each | imported into the local dev DB only; details and recording rules in docs/DATA_SOURCES.md |
| Catalogue expanded from 6 to 31 models (2026-10-28) | tested; facts for the 25 new models not verified page by page |
| FlipValue modelled estimates for all 31 models: valuation by grade, buyback, trends since release, estimated store prices (2026-10-28) | tested (pytest `test_estimates.py`, Vitest, e2e); loaded by `release`; labelled as estimates throughout |
| Real resale observations (completed sales) | **blocked** (no authorised source; eBay MI needs approval for US) |

## Valuation

| Feature | Status |
|---|---|
| `comparables-v1` engine (median, deciles/min–max, basis priority, no mixing, freshness) | tested (unchanged) |
| Value types: private sale, buyback (dealer → trade-in), refurbished retail, original retail (MRP), after repair | tested |
| Repair uplift from comparables, unavailable without post-repair evidence | tested |
| Confidence classes; assumptions, limitations, missing data, how to improve | tested |
| Fault/age adjustments | not implemented by design (no evidence); disclosed |
| Predictive model | not built: no labelled real data; documented |

## Developer platform (API keys)

| Feature | Status |
|---|---|
| Accounts (email + scrypt), sessions (HttpOnly/SameSite cookie), CSRF header, login rate limits | tested |
| Key creation (CSPRNG, shown once, SHA-256 verifier, prefix), list, revoke (next request), per-account limit | tested, verified live |
| Scopes enforced server-side on `/api/v1` and `/v1` | tested, verified live |
| Per-key minute limit + daily quota, `X-RateLimit-*`/`X-Quota-*` headers, 429 codes | tested, verified live |
| Usage events per key, last-used time, portal and `/api/v1/usage` statistics | tested, verified live |
| Audit events for account and key actions | tested (no raw key in audit) |
| `/api/v1` endpoints: health, valuations (POST/GET owner-only), market-prices, price-history, products, usage | tested, verified live |
| Developer portal UI (overview, auth, reference, examples, errors, keys, usage, revoke) | tested (Vitest + e2e) |
| Email verification, self-service account deletion | **missing** |

## Consumer product

| Feature | Status |
|---|---|
| Valuation wizard, results (now with "Other kinds of value"), saved links, print report | tested |
| Price comparison page (sources + status, tabs, filters, links, match details, alternatives, history) | tested (Vitest + e2e) |
| Observed price history with gaps; honest empty state | tested |
| Watchlist with target prices; alerts only from observed offers | tested |
| Alert delivery by email | **missing** (in-app only; no mail service configured) |
| Market insights (spread, MRP, history change) | partial: shown where data exists; depreciation curves not built |
| Repair-or-sell calculator, trends, devices, info pages | tested (unchanged) |
| Distinct visual identity (ledger palette, serif display, tabular numbers; light/dark) | implemented; 390 px tested |
| Operator console: providers, refresh, offer import, data-quality report | tested (API), implemented (UI) |

## Platform

| Feature | Status |
|---|---|
| Migration 0002 (accounts, scoped keys, usage, API valuations, offers, watchlist, alerts) | tested on SQLite (fresh + upgrade of an existing DB); **not run on PostgreSQL** |
| Retention purge extended (usage, API valuations, sessions; 48 h counters) | implemented |
| Deployment (Cloud Run, Cloud SQL, Firebase Hosting) | **blocked**: needs the owner's Google Cloud account |
| FixMyTech end-to-end | **blocked**: FixMyTech repository not available; handoff updated |

## Test results (2026-10-25)

pytest **222 passed**, 8 skipped (PostgreSQL) · ruff clean · tsc clean · Vitest **26 passed** · Playwright
**9 passed** · live HTTP lifecycle check passed. Details: docs/TESTING.md.

## Required credentials and external dependencies

1. Flipkart Affiliate Program approval → `FLIPVALUE_FLIPKART_AFFILIATE_ID`, `FLIPVALUE_FLIPKART_AFFILIATE_TOKEN`.
2. Amazon.in Associates + Creators API approval → `FLIPVALUE_AMAZON_CREDENTIAL_ID`, `_CREDENTIAL_SECRET`,
   `_PARTNER_TAG`, `_TOKEN_URL`.
3. A completed-sales source (eBay Marketplace Insights for US; none identified for India) or a data agreement
   (Cashify, refurbishers).
4. Google Cloud project with billing for deployment; a PostgreSQL instance to run migration 0002 and the PostgreSQL
   tests.
5. An email service if alert emails and account verification are wanted.

## Next priorities

1. Apply for Flipkart Affiliate and Amazon Creators API access; when approved, run `refresh-offers`, verify the field
   mapping against live responses, record each provider's terms in DATA_SOURCES.md.
2. Run migration 0002 and the test suite on PostgreSQL; deploy staging; schedule refresh and purge.
3. Email verification and account deletion before opening sign-up publicly.
4. Research manufacturer and refurbisher sources; expand the catalogue and OEM aliases.
