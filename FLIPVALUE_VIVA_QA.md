# FlipValue: technical Q&A for faculty questions

Study guide. Every number below comes from the project as it stands on 2026-10-29. Where something is a limitation, the answer says so: say it plainly in the viva, it is the strongest position.

**The 30-second pitch.** FlipValue tells a person what their used phone is worth, shows prices for the same phone across stores, and shows how its price has fallen since launch. It also exposes the same data to other apps through an API (FixMyTech, a phone-repair app, uses it). Live at https://flip-value.web.app.

---

## 1. The idea

**Q1. What problem does FlipValue solve?**
Someone with a used phone does not know what it is worth, or whether to repair it before selling. Price information is scattered over many shops and varies by storage size and condition. FlipValue gives one estimate with a range, shows prices store by store, and does the repair-or-sell arithmetic.

**Q2. Who uses it?**
Two kinds of user. (1) People using the website. (2) Other software, such as FixMyTech, through an API with a key.

**Q3. What are its main features?**
- *Value my phone*: a 5-step questionnaire gives a value and range for private sale, dealer buyback, refurbished retail and original retail (MRP).
- *Compare prices*: new, refurbished, used and buyback prices by store, with filters.
- *Trends*: a price graph from launch to today.
- *Repair or sell*: compares selling as-is, repairing then selling, repairing and keeping, and selling and replacing.
- *Watchlist*: alerts when a price falls to a target.
- *Developer API and portal*: keys, scopes, usage, limits.

**Q4. What makes it different from just searching Amazon?**
It compares the *same* model and storage only (a matching algorithm checks this), keeps different kinds of price apart (new, refurbished, used, buyback), always shows where a number came from, and says "no estimate" instead of guessing when it has no basis.

---

## 2. Architecture and technology

**Q5. What is the tech stack?**
- Backend: Python, FastAPI, Pydantic (validation), SQLAlchemy 2 (database access), Alembic (migrations), uvicorn (server), httpx (outgoing HTTP).
- Frontend: React 18, TypeScript, Vite, React Router, plain CSS, SVG charts.
- Database: SQLite for development, PostgreSQL 16 (Google Cloud SQL) in production.
- Hosting: Firebase Hosting (website) and Google Cloud Run (API), with Secret Manager, Cloud Build and Artifact Registry.
- Tests: pytest, Vitest, Playwright.

**Q6. Draw the architecture.**
```
Browser ──▶ Firebase Hosting (static React site, CDN)
                │  rewrites /api, /v1, /admin/api
                ▼
FixMyTech ──▶ Cloud Run: FastAPI service ──▶ Cloud SQL (PostgreSQL)
                │ secrets from Secret Manager
                └ one valuation engine used by every channel
```
The browser calls relative `/api/...` URLs; Firebase forwards them to Cloud Run. So the browser sees one origin and no CORS configuration is needed.

**Q7. Why FastAPI?**
It validates requests automatically from type hints (Pydantic), generates OpenAPI documentation, and is fast enough for this load. Request and response shapes are therefore declared once and checked on every call.

**Q8. Why SQLite in development but PostgreSQL in production?**
SQLite is zero-setup for development and tests. Cloud Run containers have temporary disks and many instances, so production needs one shared database; the app refuses to start in production with SQLite. PostgreSQL also gives exact rate limiting under concurrent requests.

**Q9. Why not Firestore or another NoSQL database?**
The data is relational (models, storage variants, sources, observations, offers) and queried with joins and aggregates. Firestore would have meant rewriting the data layer.

**Q10. Why Cloud Run rather than a virtual machine?**
It scales to zero when idle (no cost for compute), scales up with traffic, and we deploy a container image. Settings: 1 vCPU, 512 MiB, at most 3 instances, 40 concurrent requests per instance. A VM would cost money continuously and need patching.

**Q11. What is Alembic and why use it?**
It versions database schema changes as migration scripts (`0001_initial`, `0002_market_accounts_api`). The same scripts upgrade any database safely. A test checks that the migrations match the SQLAlchemy models.

**Q12. Why does the frontend contain no pricing logic?**
So there is one source of truth. Prices are computed only in `engine.py`; the website, the partner API and the developer API all use it. The website just displays what the server returns.

**Q13. What is the database structure?**
20 tables. Groups:
- *Catalogue*: `device_models`, `model_aliases` (names and OEM codes), `model_variants` (storage sizes).
- *Data*: `sources`, `ingestion_jobs`, `rejected_records`, `observations` (resale prices by grade), `marketplace_offers` (individual listings).
- *Users and keys*: `accounts`, `account_sessions`, `api_clients` (keys), `api_usage_events`, `api_valuations`.
- *Features*: `watchlist_items`, `price_alerts`, `saved_valuations`.
- *Operations*: `rate_limit_counters`, `idempotency_records`, `request_log`, `audit_log`.

**Q14. What is the difference between `observations` and `marketplace_offers`?**
Observations are resale prices by condition grade (completed sales, asking prices, dealer offers); they drive the private-sale and buyback estimates. Offers are individual store listings as retrieved (new, refurbished, used, buyback quotes), with URL and seller; they drive price comparison and price history. They measure different things and are never averaged together.

---

## 3. The valuation engine

**Q15. How is a value calculated?**
Method `comparables-v1`:
1. Select comparable observations: same model, same storage, same region, same condition grade, within the freshness window (180 days), not in the future.
2. Use one price basis only, in priority order: completed sales, then asking prices, then FlipValue modelled estimates (then synthetic data, development only).
3. Value = the **median**. Range = 10th to 90th percentile if there are 10 or more observations, otherwise lowest to highest.
4. Fewer than 3 observations means no estimate.

**Q16. Why the median and not the average?**
The median is not distorted by a few extreme prices (a mistaken listing, a luxury seller). The average would be.

**Q17. Why never mix price bases?**
A completed sale, an asking price and a trade-in offer are different quantities. Asking prices are usually higher than what phones sell for. Mixing them gives a number that means nothing. So each estimate uses exactly one basis and states it.

**Q18. What does "evidence-backed" mean?**
10 or more completed sales within the last 90 days. Anything less is "limited" (or "modelled" for our estimates). The label is shown on every result.

**Q19. Why 3 and 10 as thresholds?**
They are judgement calls, not derived values. Three is the smallest sample where a median means anything; ten is the smallest where percentiles are reasonable. They are named constants in the code (`MIN_OBSERVATIONS`, `DECILE_MIN`), so they are easy to change.

**Q20. Does the engine adjust for faults or age?**
No, on purpose. We have no evidence of how much a fault or a phone's age moves price, so adjusting would be inventing numbers. The result says so. Faults matter only through the grade (any functional fault means "faulty").

**Q21. How is the "after repair" value computed?**
By looking up the price for the grade the phone would have after the repair (a faulty phone repaired becomes "good": a repair restores function, not cosmetics). It does not include the repair cost. If there is no data for that grade, it says unavailable.

**Q22. What are the "value types"?**
- *Private sale*: what a person might get selling to another person.
- *Dealer buyback*: what a dealer pays; usually lower.
- *Refurbished retail*: what a refurbisher charges; not what you would receive.
- *Original retail (MRP)*: from retailer-supplied MRPs for that exact variant.
They are shown separately, with their own confidence.

**Q23. What is the confidence rating?**
`high` (evidence-backed), `medium` (10+ observations of another basis, or 3-9 completed sales), `low` (asking prices, thin data, or modelled estimates), `insufficient` (no estimate).

**Q24. How does the engine handle different storage sizes?**
Never pooled. A 128 GB and a 256 GB phone are separate. If a model has several variants and none is given, the engine refuses rather than guess.

**Q25. What is the `valuation_id`?**
A SHA-256 hash of the request, the method version and the IDs of the observations used. The same request on the same evidence gives the same ID, so results are reproducible and auditable.

---

## 4. Modelled estimates (the important one to understand)

**Q26. You said you don't have real sales data. Where do the numbers come from?**
Honest answer: there is no authorised source of completed sales for India, and the Flipkart and Amazon APIs need approvals we don't have yet. So every phone gets a **modelled estimate**, generated from a price-band file (`data/estimates/price_bands.csv`): the launch price and approximate current new, refurbished and used price ranges per model. The ranges combine figures supplied by the project owner with prices I checked by hand on public pages. Every estimate is labelled "Estimate" on the site and in the API; real data automatically takes priority when it exists.

**Q27. How does the model work exactly?**
From the used-price range [L, H]:
- excellent = H, good = (L+H)/2, fair = L, poor = 0.75 × L, faulty = 0.45 × L.
- Buyback = 70% of the private-sale price of the same grade.
- Larger storage: +8% per step for used/refurbished, +10% for new.
- Each month's estimate has three points (×0.94, ×1, ×1.06), so the range shown is ±6%. That range is a modelling margin, not a spread of real prices.

**Q28. How is the price-trend graph produced?**
For each month since the phone's release, the price falls exponentially from 80% of the launch price (a used phone in its first month) down to today's estimated price, with a small fading wobble so it doesn't look artificial. The graph shows the general depreciation shape, not true past prices, and it is a dashed line labelled "FlipValue estimate". Real observed prices, once collected, will appear as solid lines.

**Q29. Why exponential decay?**
Resale value of electronics typically drops fastest early and then flattens. An exponential curve captures this with only two inputs (start and end price). It is an assumption, stated openly, not a measurement.

**Q30. How are the store prices generated?**
For each store (Amazon, Flipkart, Croma, Reliance Digital, the brand's own store for new; Cashify, Amazon Renewed, Budli, Controlz for refurbished; OLX, Quikr, Facebook Marketplace for used; Cashify and Budli for buyback), a price is placed inside the model's range. The position is a hash of model, storage and store, so it is stable between page loads. They have no links, never expire, never trigger alerts and never appear in price history. The site labels them "Estimate, not a live listing".

**Q31. Isn't showing estimated store prices misleading?**
It would be if unlabelled. Each row carries an "Estimate" badge and "not a live listing" text, a line under the table explains it, and the API marks them (`source.estimated`). Real hand-checked prices appear alongside with links, so users can tell them apart.

**Q32. How do you know your estimates are reasonable?**
Partly by cross-checking: the owner-supplied ranges were compared with real prices I read from Cashify, Budli and Flipkart pages. Where they conflicted (for example used above refurbished, which makes no economic sense), I adjusted the range and recorded the change in the file. I have not measured accuracy against real sales; that needs real sales data.

---

## 5. Condition grading and repair-or-sell

**Q33. How does the questionnaire become a grade?**
`condition.py` applies fixed rules. If anything functional is wrong (won't power on, screen or touch fault, swollen or fast-draining battery, charging, cameras, audio, connectivity or buttons not working), the grade is **faulty**. Otherwise the grade is the worse of the screen and body conditions: excellent, good, fair or poor. The rules are definitional, not price adjustments.

**Q34. What if the user is unsure about something?**
The result lists "things that could change the grade" (for example, "cameras not tested; if they don't work, the phone would be graded faulty"). It never silently assumes.

**Q35. Is anything verified about the phone?**
No. All answers are customer-reported, and the result says a buyer will check. This is a stated limitation.

**Q36. How does the repair-or-sell calculator work?**
Plain arithmetic (`decision.py`):
- Sell as-is: net = as-is value − selling fees − fixed costs.
- Repair then sell: net = after-repair value − repair cost − fees − fixed costs.
- Advantage of repairing = net(repair then sell) − net(sell as-is).
- Also: repair and keep, and sell and buy a replacement.
No forecasting. It lists assumptions: no allowance for time, repair failure risk, or price changes.

**Q37. Why does it use `Decimal` and not `float`?**
Floats cannot represent decimal money exactly (0.1 + 0.2 ≠ 0.3). `Decimal` with explicit rounding (half-up, 2 places) keeps money arithmetic exact.

---

## 6. Marketplace data and matching

**Q38. How do you get real prices from Amazon and Flipkart?**
Properly, through their official partner APIs: Flipkart Affiliate API and Amazon's Creators API (it replaced PA-API 5, retired on 2026-04-30). Both adapters are written and tested against the documented response shapes, but no credentials exist yet because both need approved accounts. Until then, real prices were entered by hand from individual public pages, with the URL and date.

**Q39. Why didn't you just scrape?**
Amazon's and Flipkart's terms forbid automated extraction, Cashify's prohibit systematic retrieval, and scrapers break often and risk the site being blocked. The project's rule is no scraping and no bypassing access controls. I read individual pages by hand (13 first, then 25 more) and recorded each one as a source-attributed row.

**Q40. How does the system know two listings are the same phone?**
`matching.py` classifies each listing against the catalogue:
- *exact*: an OEM model code (like SM-G991B) is in the title and storage matches.
- *strong*: brand and model name appear as a whole phrase, with no variant word after it ("Pro", "FE", "Ultra", "Plus"…), and storage matches.
- *variant_unknown / variant_mismatch*: right model, storage missing or different.
- *similar*: same brand, different model (for example "Galaxy S21 FE" when you searched "Galaxy S21").
- *unmatched*: rejected.
Only exact and strong matches of the right storage enter price comparisons, history and alerts. Each decision keeps a score and reasons, shown in the UI.

**Q41. What is the problem with "Galaxy S21" matching "Galaxy S21 FE"?**
They are different phones with very different prices. The variant-word list stops "S21" matching when "FE" follows. Those listings appear separately as "Similar, but not the same phone".

**Q42. How do you handle duplicates?**
Each offer gets a hash of source, product ID (or URL, or title), condition, seller, price and retrieval date. The same price retrieved again on the same day is a duplicate and is dropped; a price change or a new day is a new row. That is what makes price history a simple query.

**Q43. What validation happens on incoming data?**
Title present; currency matches the region (INR for India); price greater than 0, at most 10,000,000 and 2 decimals; MRP not implausibly below the price; HTTPS URL; known condition, price type and seller type; must match a catalogue model. Rejected rows are kept with line and reason so nothing disappears silently.

**Q44. What is price freshness?**
An offer is "fresh" within 24 hours, "stale" up to 14 days, and older offers are kept for history but not shown as current.

**Q45. What happens if one provider fails?**
Providers are isolated: one failing never stops the others, and every failure is recorded as a failed ingestion job with its message. Calls use timeouts and bounded retries (with `Retry-After` respected, capped).

**Q46. Why are provider calls not made when a user opens a page?**
Latency, rate limits and terms. Offers are fetched by a scheduled `refresh-offers` command; user requests only read stored data. A minimum refresh interval per provider and product (default 60 minutes) is enforced.

---

## 7. API design and security

**Q47. What APIs does FlipValue expose?**
- `/api/*`: website, anonymous, rate-limited per IP.
- `/api/v1/*`: developer API, `X-API-Key` with scopes.
- `/v1/valuations`: the FixMyTech contract, frozen shape.
- `/admin/api/*`: operator, admin key.
- `/health`, `/ready`, `/docs`.

**Q48. How does FixMyTech integrate?**
Their server calls FlipValue with an API key in the `X-API-Key` header. They use valuations, price trends, store prices and the repair-or-sell comparison. The keyed `/api/v1/trends` and `/api/v1/decision` return exactly the same JSON as the public endpoints; a test enforces that, and I also checked it against production.

**Q49. How are API keys protected?**
A key is 256 random bits from the operating system's secure random generator. Only its SHA-256 hash is stored; the key is shown once on creation. A slow hash such as bcrypt is unnecessary because a 256-bit random key cannot be brute-forced, and an indexed lookup by hash keeps authentication fast. Keys can be revoked and the revocation applies to the next request (nothing is cached).

**Q50. What are scopes?**
Permissions on a key: `valuation:read`, `market_prices:read`, `price_history:read`. The server checks them on every request; a key without the right one gets 403 `insufficient_scope`. An invalid key gets 401.

**Q51. How is rate limiting done?**
Fixed one-minute windows counted in the database (table `rate_limit_counters`), so limits hold across several server instances without Redis. Keyed traffic is counted per key, not per IP (important because FixMyTech's calls all come from one server); website traffic is per IP plus a global cap. Responses carry `X-RateLimit-*` headers and 429 with `Retry-After`. Limitation: a burst up to 2× the limit is possible across a window boundary.

**Q52. How are user passwords stored?**
With scrypt (a memory-hard hash). Sessions are server-side tokens in an HttpOnly, SameSite cookie, and state-changing calls require a custom CSRF header.

**Q53. What other security measures exist?**
Request-size limits, request timeouts, security headers (Content-Security-Policy, HSTS, X-Frame-Options, nosniff), no stack traces in errors, structured logs without keys, bodies or IP addresses (IPs are only stored as salted hashes for rate limiting), secrets in Secret Manager not in code, an audit log for key actions, and refusal to start in production with mock data, SQLite, a missing salt or wildcard CORS.

**Q54. What is idempotency and where is it used?**
Repeating the same request gives the same result without creating duplicates. The partner valuation endpoint stores an idempotency record, so a retry after a network timeout is safe.

**Q55. How do you handle errors?**
Every error has the shape `{"error": {"code": ..., "message": ..., "request_id": ...}}`, with codes like `unsupported_model` (404), `unauthorized` (401), `insufficient_scope` (403), `validation_error` (422), `rate_limited` (429). "Not enough data" is deliberately not an error: it returns 200 with `available: false` and a human-readable reason, so callers can show it.

**Q56. What does the 404 vs `available: false` distinction give you?**
An unknown phone is a client mistake (404). A known phone with insufficient data is a valid answer ("no estimate yet"), so FixMyTech can display it instead of treating it as a failure.

**Q57. How are OEM model codes matched, for example `SM-G991B/DS`?**
Phones report codes, not marketing names, and often with suffixes (`/DS` for dual SIM). The catalogue stores codes as aliases; if an exact match fails, the code is retried without the `/…` suffix. This works in product search and in `/v1/valuations`.

---

## 8. Frontend

**Q58. Why React and TypeScript?**
React for component-based UI; TypeScript so the compiler catches wrong data shapes. The types in `types.ts` mirror the backend schemas.

**Q59. How is accessibility handled?**
Skip link, keyboard-operable controls, labelled form fields, charts with a "Show the data" table for screen readers, sufficient contrast with light and dark themes, and a mobile layout tested at 390 px with no horizontal scrolling.

**Q60. How are the charts drawn?**
Hand-written SVG components (no chart library), which keeps the bundle small (about 88 kB gzipped). Estimated series use a dashed line; real series are solid.

**Q61. How does the site stay honest about data?**
Labels everywhere: an "Estimate" badge on modelled values and store prices, a result notice, a site-wide banner, a "Mock data" label on test data, and an "Estimates" evidence level on the devices page.

---

## 9. Testing

**Q62. How is the software tested?**
Three layers:
- **pytest** (235 passed, 8 skipped): the engine's exact arithmetic, API contracts, security (scopes, limits, revocation), matching, ingestion, migrations, deployment safety rules, and the estimates.
- **Vitest** (29 passed): component tests for the wizard, results, comparison page, trends, developer portal.
- **Playwright** (9 passed): full browser journeys on desktop and mobile against the real backend.
Plus lint (ruff) and TypeScript type checking.

**Q63. Why are 8 tests skipped?**
They need a PostgreSQL server, which my development machine does not have. They were run earlier against PostgreSQL 16.2 locally, and production runs on PostgreSQL (Cloud SQL).

**Q64. Give an example of a test that protects honesty.**
Production tests assert that mock data is never used in production and that the smoke test fails if a server reports mock data. Another asserts that real observations always win over modelled estimates.

**Q65. What is a smoke test?**
A script (`scripts/smoke_test.py`) that checks the live deployment end to end: health, readiness, authentication, a valuation, error cases, and the website's rewrites. The full run, including the website checks, passed all 29 checks on the 2026-10-28 deployment. The API-only deployments on 2026-10-29 ran the API checks, which passed; the separate FixMyTech parity script then passed all 12 of its checks against production.

---

## 10. Deployment and operations

**Q66. How is it deployed?**
`scripts/deploy_update.ps1`: Cloud Build builds the Docker image; a Cloud Run job runs the database migrations and loads the catalogue and estimates; the API service is updated (zero downtime, same settings and secrets); the website is published to Firebase Hosting; the smoke test runs.

**Q67. How is the website published?**
Through the Firebase Hosting REST API with the Google Cloud login (`scripts/hosting_deploy.py`): create a version with the rewrites and headers from `firebase.json`, upload changed files by content hash, finalise, release.

**Q68. How are secrets managed?**
In Google Secret Manager (database URL, hash salt, partner keys, admin keys), injected as environment variables by Cloud Run. Nothing is committed to git.

**Q69. What does it cost?**
Cloud SQL (the smallest instance) is the main fixed cost, roughly US$8–12 per month; Cloud Run and Hosting stay in free allowances at low traffic. A budget alert is recommended.

**Q70. How do you roll back?**
API: route traffic to the previous Cloud Run revision. Website: Firebase "release history → rollback". Database migrations are forward-only; take a backup before risky ones.

**Q71. What bug did you hit during deployment, and what did it teach you?**
The upload filter `.gcloudignore` contained `FlipValue/`, meant for a notes folder. On Windows matching is case-insensitive, so it also excluded `src/flipvalue/`, the application code. The first image had no code and the setup job failed; production was never affected. Fix: anchor the pattern as `/FlipValue/`. Lesson: always check what is actually uploaded.

---

## 11. Limitations, honestly

**Q72. What are the limitations?**
- No real completed-sales data; headline values are modelled estimates (labelled).
- Only about 38 real, hand-checked prices; they expire from "current" after 14 days.
- Store prices are estimates, not live listings.
- Grade comes from customer answers, unverified.
- Faults and age are not priced.
- Catalogue facts (release dates, storage sizes, OEM codes) for 25 of the 31 phones were compiled from public knowledge, not verified model by model.
- No email verification, account deletion, or email alerts yet (alerts are in-app only).
- India only in practice; the US market is supported in code but has no data.

**Q73. What would you do next?**
Get approved for the Flipkart Affiliate and Amazon Creators APIs and schedule `refresh-offers`; find an authorised source of completed sales or a data agreement with refurbishers; replace modelled curves with observed history as it accumulates; verify the catalogue; add email verification and alert emails.

**Q74. How would you validate the accuracy of the estimates?**
Compare predictions against real completed sales: mean absolute percentage error per model and grade, tracked over time. That needs the real data above; I have not done it, and I would not claim accuracy numbers until I had.

**Q75. Is it ethical/legal to show estimated prices next to store names?**
Only if clearly labelled, which is why every such row says "Estimate" and "not a live listing", and the API flags it. Unlabelled, it would look like real Amazon or Flipkart listings, which would be misleading.

**Q76. What if a teacher says "so the numbers are fake?"**
"They are modelled, not fake: each comes from a stated formula using launch prices and real approximate market ranges, cross-checked against 38 real prices I collected. They are labelled as estimates everywhere, and real data replaces them automatically as it arrives. What I have not got is a measured accuracy figure."

---

## 12. Quick facts to memorise

| Item | Value |
|---|---|
| Live site | https://flip-value.web.app |
| API base | https://flipvalue-api-lhoxu5lfzq-el.a.run.app |
| Cloud project / region | `flip-value` / `asia-south1` (Mumbai) |
| Engine method | `comparables-v1` |
| Catalogue | 31 phone models (Apple, Samsung, Google, OnePlus, Nothing, Xiaomi, Motorola, Vivo) |
| Real hand-checked prices | 38 (2 new retail, 36 refurbished) |
| Estimates | 48,270 modelled observations, 909 estimated store prices |
| Database tables | 20 |
| Tests | pytest 235, Vitest 29, Playwright 9 |
| Thresholds | ≥3 observations for an estimate; ≥10 for percentile range; evidence-backed = ≥10 completed sales in 90 days |
| Grades | excellent, good, fair, poor, faulty |
| Match categories | exact, strong, variant_unknown, variant_mismatch, similar, unmatched |
| Rate limit (partner key) | 60 requests/minute per key, no daily cap |
| Key storage | SHA-256 hash of a 256-bit random key |
| Password hashing | scrypt |

Where to look in the code: `engine.py` (valuation), `estimates.py` (modelled data), `condition.py` (grading), `decision.py` (repair or sell), `marketplace/matching.py` (product identity), `security.py` (keys and limits), `app.py` (middleware), `routes/` (endpoints), `docs/` (methodology, architecture, security).
