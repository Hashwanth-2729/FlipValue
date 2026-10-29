# Deployment

The deployment guide (Firebase Hosting + Cloud Run + Cloud SQL, costs, commands, rollback, checklist) is
[../DEPLOYMENT.md](../DEPLOYMENT.md). Environment variables: [ENVIRONMENT.md](ENVIRONMENT.md).

## Additions for marketplace data and the developer platform (2026-10-25)

Nothing here has been deployed. In addition to the steps in DEPLOYMENT.md:

1. **Migration 0002** runs with the usual release job (`python -m flipvalue release`). It alters `api_clients`
   (batch mode) and adds tables; existing partner keys keep working with all scopes. Tested on SQLite (fresh and an
   existing 0001 database); **not yet run on PostgreSQL**.
2. **Provider credentials** (when approved) go to Secret Manager and are mapped to the env variables in
   ENVIRONMENT.md. Without them the providers report "not configured" and nothing is fetched.
3. **Scheduled refresh:** create a Cloud Run Job from the same image with command
   `python -m flipvalue refresh-offers` and trigger it with Cloud Scheduler no more often than the providers allow
   (start with every 6 hours). The job exits 1 if any provider failed, so failures show in Cloud Run Job history.
4. **Daily purge:** schedule `python -m flipvalue purge` (usage events 90 days, API valuations 365 days, expired
   sessions, rate-limit counters 48 h).
5. **HTTPS only:** session cookies are `Secure` in production; partners must use the HTTPS URL.
6. Decide `FLIPVALUE_DEVELOPER_SIGNUP` (open vs closed) before launch; there is no email verification yet.
7. `httpx` is now a runtime dependency (`requirements.txt`) for outbound provider calls; the Cloud Run service
   account needs outbound internet access (default).

Backups: Cloud SQL automated backups + point-in-time recovery (DEPLOYMENT.md). The `marketplace_offers` table is the
only copy of observed price history — include it in any restore test.
