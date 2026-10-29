# Limitations

1. **No real market data (blocking).** Every number in development is synthetic and labelled; production returns
   "no data" until an authorised source is imported (DATA_SOURCES.md).
2. **Faults, age and previous repairs do not adjust prices.** Disclosed on every result; needs fault-tagged
   observations to change.
3. **Small catalogue:** 6 hand-curated models; aliases are a starting set. Unknown OEM variants return 404 until an
   alias is added (admin API).
4. **Condition is self-reported.** The questionnaire maps answers to grades by definition; nothing verifies hardware.
5. **No accounts.** Saved valuations are links; the delete key lives in one browser. Losing browser data means the
   saved link can't be deleted (it expires after 365 days).
6. **Rate limiting** uses fixed one-minute windows in the database: bursts up to 2× at window edges; IP-based limits
   can be shared by users behind one NAT.
7. **Idempotency** keys are kept 24 hours.
8. **Not deployed.** Firebase Hosting + Cloud Run + Cloud SQL configuration is ready (DEPLOYMENT.md) and was
   rehearsed locally on PostgreSQL; the Docker image build, the cloud services and HTTPS are unverified; no URL.
   Cloud SQL is a fixed monthly cost.
9. **Trends** show nothing until three months of genuine data exist for a model/storage/market/grade.
10. **No automatic data-quality alerts** (stale sources, rejection spikes).
11. **Privacy and Terms pages are drafts** without legal review; no contact address configured.
12. **Accessibility** tested via keyboard and ARIA structure in automated tests, not with assistive technology users.

## Added 2026-10-25

* Marketplace comparison and history show only fixture offers until a provider is approved and configured; no
  live provider call has been made from this codebase.
* Product matching is rule-based on titles, codes and stated storage; it cannot verify colour, region variants or
  RAM equivalence, and every match carries its reasons for inspection.
* Refurbished-retail and MRP values reflect what retailers currently charge, not resale proceeds.
* Accounts have no email verification, password reset or self-service deletion; alerts are in-app only.
* Daily quotas and rate limits use fixed windows (bursts up to 2× across a boundary).
