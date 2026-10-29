# Data quality

## Import format (manual CSV and adapter rows)

```
manufacturer,model,storage_gb,region,currency,grade,price,observed_at,external_ref
samsung,SM-G991B,128,IN,INR,good,21000,2026-09-01,listing-12345
```

* `model` may be an OEM code or a catalogued name; `grade` must already be one of the five FlipValue grades (map
  the source's own condition labels before import and document the mapping in the source's `terms_note`/docs).
* `storage_gb` may be blank only for single-variant models.
* `external_ref` is the source's own id (strongly recommended: it makes de-duplication exact).

## Validation (rows failing any rule are rejected, kept with line and reason)

| Rule | Reason text |
|---|---|
| Model in catalogue (exact alias) | `model not in catalogue` |
| Supported region/currency pair; source registered for that market | `not a supported pair` / `not registered for market` |
| Valid grade | `grade must be one of …` |
| Storage catalogued for the model; required for multi-variant models | `storage_gb must be one of …` / `storage_gb is required` |
| Price > 0, ≤ 10,000,000, ≤ 2 decimals | `price must be > 0 and plausible` / `more than 2 decimal places` |
| Date ISO, not in the future, ≤ 5 years old | `observed_at …` |
| `external_ref` ≤ 200 characters | |

A malformed header fails the whole job (`status: failed`, message recorded).

## De-duplication

`dedup_key` = SHA-256 of `source|external_ref`, or of `source|model|storage|region|grade|price|date` when there is
no reference. Duplicates within a file or against the database are counted, not stored.

## Marketplace offers

Provider offers and curated CSV offers go through the same pipeline (`marketplace/service.py`):

| Rule | Reject reason |
|---|---|
| Title present; currency is the region's (INR for IN) | `title is empty` / `currency X is not INR for IN` |
| Price > 0, ≤ 10,000,000, ≤ 2 decimals; MRP not below half the price | `price must be > 0 and plausible` / `MRP is implausibly below the price` |
| Listing URL https | `listing URL must be https` |
| Known condition, price type, seller type | `unknown condition or price type` / `seller_type must be one of …` |
| Matches a catalogue model (matching.py) | `unrelated product: <reasons>` |
| Provider record parseable | `malformed product/item: <detail>` (provider adapters) |

**Matching** (`marketplace/matching.py`): `exact` (OEM code in title + storage), `strong` (brand + model name as a whole
phrase with no variant word such as Pro/FE/Ultra/Plus/a after it + storage, or a single-variant model),
`variant_unknown`, `variant_mismatch`, `similar` (same brand, different model — kept only as an alternative for the
model searched), `unmatched` (rejected). Score and reasons are stored per offer and shown in the UI and API.
Only `exact`/`strong` offers of the requested storage enter price comparisons, refurbished-retail/MRP values,
history and alerts.

**De-duplication:** SHA-256 of `source | product id (or URL, or title) | condition | seller | price | retrieval date`.
The same price retrieved again on the same day is a duplicate; a price change, or a new day, is a new row — that is
the price history.

**Freshness:** `fresh` ≤ `FLIPVALUE_OFFER_FRESH_HOURS` (24); `stale` up to `FLIPVALUE_OFFER_MAX_AGE_DAYS` (14); older
offers are kept for history but never shown as current.

**Curated offer CSV** (`import-offers` / `POST /admin/api/offer-imports`):

```
title,brand,storage_gb,condition,price_type,price,mrp,currency,url,seller,seller_type,availability,retrieved_at,external_ref
Samsung Galaxy S21 128 GB,Samsung,128,used,buyback_quote,15000,,INR,https://www.cashify.in/…,Cashify,dealer,,2026-09-30,q1
```

`condition`: new | refurbished | used. `retrieved_at`: when the person saw the price (ISO date/datetime, not in the
future). Leave unknown fields empty — never guess.

## Monitoring

* Each run is an `ingestion_jobs` row: accepted, rejected, duplicates, status, message, who triggered it. Provider
  failures (timeout, rate limit, unauthorized, malformed, HTTP error) are recorded as failed jobs.
* `/admin` and `GET /admin/api/sources` show per-source observation counts, newest observation and its age, and the
  last job status. `GET /admin/api/jobs/{id}/rejected` lists rejected rows.
* **Data-quality report** `GET /admin/api/data-quality?days=30` (also in `/admin`): provider states, successful and
  failed retrievals per source with recent failure messages, current listings fresh vs stale, rows older than the
  maximum age, rejects grouped by reason, duplicates skipped, offers per match category (matching uncertainty),
  offers missing URL/seller/availability/MRP/storage, sources missing a URL or not verified.
* Not implemented: automatic notifications on stale sources or rejection spikes, statistical outlier detection
  beyond the plausibility bounds. Median statistics limit the influence of single outliers.

## Retention

Observations and offers are kept (they are the price history); nothing is deleted indiscriminately. If a provider's
terms restrict retention, add a purge rule for that source before connecting it.
