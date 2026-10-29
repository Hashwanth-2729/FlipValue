"""Operator command line: python -m flipvalue <command>. Uses the same settings as the server."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import delete, select

from flipvalue.catalogue import load_catalogue
from flipvalue.config import ROOT, ConfigError, Settings
from flipvalue.context import build_providers, offer_policy
from flipvalue.db.models import (
    AccountSession,
    ApiClient,
    ApiUsageEvent,
    ApiValuation,
    AuditLog,
    DeviceModel,
    IdempotencyRecord,
    MarketplaceOffer,
    Observation,
    PriceAlert,
    RateLimitCounter,
    RequestLog,
    SavedValuation,
    Source,
    utcnow,
)
from flipvalue.db.session import make_engine, make_sessionmaker, transaction, upgrade
from flipvalue.estimates import load_estimates
from flipvalue.ingestion.adapters import CsvImportAdapter, SyntheticAdapter
from flipvalue.ingestion.runner import run_ingestion
from flipvalue.ingestion.sources import FIXTURE_OFFERS, SYNTHETIC_DEV, SourceSpec, register_source
from flipvalue.marketplace import service as market
from flipvalue.security import SCOPES, issue_key, revoke_key

CATALOGUE = ROOT / "data" / "catalogue" / "models.csv"
SYNTHETIC_SPEC = ROOT / "data" / "mock" / "synthetic_spec.csv"
FIXTURE_OFFERS_CSV = ROOT / "data" / "mock" / "fixture_offers.csv"

# Retention (docs/PRIVACY.md). Audit log, observations and offers (price history) are kept. Rate-limit counters
# include daily quota windows, so they are kept for two days.
RETENTION = {"idempotency_hours": 24, "rate_limit_hours": 48, "request_log_days": 90, "saved_days": 365,
             "usage_days": 90, "api_valuation_days": 365}


def _audit(session, action: str, detail: dict) -> None:
    session.add(AuditLog(actor="cli", action=action, detail=json.dumps(detail, default=str)))


def serve() -> int:
    """Production entry point: binds 0.0.0.0 on the port the platform supplies ($PORT, default 8080).

    Uvicorn's own access log is off (the app writes one structured line per request without IPs or query strings);
    its startup/error messages use the same JSON format.
    """
    import uvicorn

    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": "flipvalue.observability.JsonFormatter"}},
        "handlers": {"stdout": {"class": "logging.StreamHandler", "formatter": "json", "stream": "ext://sys.stdout"}},
        "loggers": {"uvicorn": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
                    "uvicorn.access": {"handlers": [], "level": "WARNING", "propagate": False}},
    }
    uvicorn.run("flipvalue.app:create_app", factory=True, host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "8080")), access_log=False, log_config=log_config,
                proxy_headers=False, timeout_keep_alive=5)
    return 0


def seed_mock(sessions, settings: Settings, reference: date, replace: bool) -> str:
    if settings.is_production:
        raise ConfigError("seed-mock is refused in production: synthetic data must never reach production.")
    with transaction(sessions) as session:
        register_source(session, SYNTHETIC_DEV)
        if replace:
            session.execute(delete(Observation).where(Observation.source_id == SYNTHETIC_DEV.id))
        job = run_ingestion(session, SYNTHETIC_DEV.id, SyntheticAdapter(SYNTHETIC_SPEC, reference), "cli:seed-mock",
                            production=False, today=reference)
        _audit(session, "ingestion.seed_mock", {"job": job.id, "accepted": job.accepted})
        fixtures = register_source(session, FIXTURE_OFFERS)
        if replace:
            session.execute(delete(PriceAlert).where(PriceAlert.offer_id.in_(
                select(MarketplaceOffer.id).where(MarketplaceOffer.source_id == fixtures.id))))
            session.execute(delete(MarketplaceOffer).where(MarketplaceOffer.source_id == fixtures.id))
        noon = datetime.combine(reference, time(12))
        offers = market.seed_fixture_offers(session, fixtures, FIXTURE_OFFERS_CSV.read_text(encoding="utf-8"), noon)
        return f"job {job.id}: {job.status}, {job.accepted} accepted, {job.duplicates} duplicates, " \
               f"{job.rejected} rejected; fixture offers job {offers.id}: {offers.accepted} stored, " \
               f"{offers.rejected} rejected as unrelated"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flipvalue")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    p = sub.add_parser("load-catalogue", help="load device models, aliases and storage variants")
    p.add_argument("path", nargs="?", type=Path, default=CATALOGUE)
    p = sub.add_parser("seed-mock", help="(development only) generate synthetic MOCK observations")
    p.add_argument("--replace", action="store_true", help="delete existing synthetic observations first")
    p.add_argument("--reference-date", type=date.fromisoformat, default=None)
    sub.add_parser("setup-dev", help="migrate + load catalogue + seed mock data")
    sub.add_parser("release", help="deploy step: migrate + load catalogue + load estimates (idempotent; run before "
                                   "shifting traffic)")
    sub.add_parser("load-estimates", help="replace FlipValue modelled estimates from data/estimates/price_bands.csv")
    p = sub.add_parser("register-source", help="register (or update) a market-data source")
    for name in ("id", "name", "source-type", "collection-method", "markets", "terms-note"):
        p.add_argument(f"--{name}", required=True)
    p.add_argument("--url")
    p.add_argument("--verified", action="store_true")
    p = sub.add_parser("import", help="import a CSV of observations for a registered source")
    p.add_argument("--source", required=True)
    p.add_argument("path", type=Path)
    keys = sub.add_parser("keys", help="manage API keys").add_subparsers(dest="action", required=True)
    p = keys.add_parser("create")
    p.add_argument("--name", required=True)
    p.add_argument("--role", choices=("partner", "admin"), required=True)
    p.add_argument("--scopes", default=",".join(SCOPES), help="partner keys: comma-separated scopes")
    p.add_argument("--rate-limit", type=int, help="requests per minute (default: server setting)")
    p.add_argument("--daily-quota", type=int, help="requests per UTC day (default: unlimited for operator keys)")
    p = sub.add_parser("refresh-offers", help="fetch current offers from configured marketplace providers")
    p.add_argument("--model", help="catalogue model id (default: every model)")
    p.add_argument("--storage", type=int, help="storage variant in GB (default: all)")
    p.add_argument("--region", default="IN")
    p = sub.add_parser("import-offers", help="import manually curated, source-attributed offers (CSV)")
    p.add_argument("--source", required=True)
    p.add_argument("--region", default="IN")
    p.add_argument("path", type=Path)
    sub.add_parser("providers", help="show marketplace provider status")
    keys.add_parser("list")
    p = keys.add_parser("revoke")
    p.add_argument("id", type=int)
    sub.add_parser("purge", help="delete data past its retention period")
    sub.add_parser("serve", help="run the web server on 0.0.0.0:$PORT (Cloud Run, containers)")
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    if args.command == "serve":
        return serve()
    sessions = make_sessionmaker(make_engine(settings.database_url, 1, 0))

    if args.command in ("migrate", "setup-dev", "release"):
        upgrade(settings.database_url)
        print("database migrated")
    if args.command in ("load-catalogue", "setup-dev", "release"):
        with transaction(sessions) as session:
            count = load_catalogue(session, getattr(args, "path", CATALOGUE))
            _audit(session, "catalogue.load", {"models": count})
        print(f"catalogue: {count} models loaded")
    if args.command in ("load-estimates", "release"):
        with transaction(sessions) as session:
            counts = load_estimates(session)
            _audit(session, "estimates.load", counts)
        print("estimates: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in counts.items()))
    if args.command in ("seed-mock", "setup-dev"):
        try:
            print(seed_mock(sessions, settings, getattr(args, "reference_date", None) or date.today(),
                            getattr(args, "replace", False) or args.command == "setup-dev"))
        except ConfigError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "register-source":
        spec = SourceSpec(id=args.id, name=args.name, source_type=args.source_type,
                          collection_method=args.collection_method, markets=args.markets,
                          terms_note=args.terms_note, verified=args.verified, url=args.url)
        if spec.is_mock:
            print("synthetic sources are created only by seed-mock", file=sys.stderr)
            return 2
        with transaction(sessions) as session:
            register_source(session, spec)
            _audit(session, "source.register", spec.__dict__)
        print(f"source {spec.id} registered")
    if args.command == "import":
        with transaction(sessions) as session:
            source = session.get(Source, args.source)
            if source is None or source.is_mock:
                print("unknown or synthetic source", file=sys.stderr)
                return 2
            job = run_ingestion(session, source.id, CsvImportAdapter.from_path(args.path), "cli:import",
                                production=settings.is_production)
            _audit(session, "ingestion.import", {"source": source.id, "job": job.id})
        print(f"job {job.id}: {job.status}, {job.accepted} accepted, {job.duplicates} duplicates, "
              f"{job.rejected} rejected{' - ' + job.message if job.message else ''}")
        return 0 if job.status == "succeeded" else 1
    if args.command == "keys":
        with transaction(sessions) as session:
            if args.action == "create":
                scopes = [s for s in args.scopes.split(",") if s] if args.role == "partner" else []
                try:
                    client, key = issue_key(session, args.name, args.role, scopes=scopes,
                                            rate_limit_per_minute=args.rate_limit, daily_quota=args.daily_quota)
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    return 2
                _audit(session, "key.create", {"id": client.id, "name": client.name, "role": client.role,
                                               "scopes": client.scopes})
                print(f"id {client.id} ({client.role}) {client.name}\n{key}\n"
                      "Shown once. Store it in the client's secret storage; it cannot be recovered.")
            elif args.action == "list":
                for c in session.scalars(select(ApiClient).order_by(ApiClient.id)):
                    state = f"revoked {c.revoked_at:%Y-%m-%d}" if c.revoked_at else "active"
                    owner = f"account {c.account_id}" if c.account_id else "operator"
                    print(f"{c.id}\t{c.role}\t{c.name}\t{c.key_prefix}...\t{state}\t{owner}\t{c.scopes or '-'}")
            elif args.action == "revoke":
                if not revoke_key(session, args.id):
                    print("no active key with that id", file=sys.stderr)
                    return 1
                _audit(session, "key.revoke", {"id": args.id})
                print(f"key {args.id} revoked")
    if args.command == "providers":
        with transaction(sessions) as session:
            for p in market.provider_status(session, build_providers(settings), offer_policy(settings)):
                print(f"{p['id']}\t{p['state']}\t{p['last_retrieved_at'] or '-'}\t{p['requirement'] or ''}")
    if args.command == "refresh-offers":
        providers = build_providers(settings)
        failed = False
        with transaction(sessions) as session:
            models = [session.get(DeviceModel, args.model)] if args.model else \
                list(session.scalars(select(DeviceModel).order_by(DeviceModel.id)))
            if not models or models[0] is None:
                print("unknown model", file=sys.stderr)
                return 2
            for model in models:
                for run in market.refresh(session, providers, model, args.storage, args.region, "cli:refresh-offers",
                                          offer_policy(settings)):
                    failed = failed or run.status == "failed"
                    print(f"{model.id}\t{run.source_id}\t{run.status}\taccepted {run.accepted} rejected "
                          f"{run.rejected} duplicates {run.duplicates}\t{run.message or ''}")
            _audit(session, "offers.refresh", {"models": [m.id for m in models]})
        return 1 if failed else 0
    if args.command == "import-offers":
        with transaction(sessions) as session:
            source = session.get(Source, args.source)
            if source is None or source.is_mock:
                print("unknown or mock source; register it first", file=sys.stderr)
                return 2
            job = market.import_offers_csv(session, source, args.path.read_text(encoding="utf-8-sig"), args.region,
                                           "cli:import-offers")
            _audit(session, "offers.import", {"source": source.id, "job": job.id})
        print(f"job {job.id}: {job.status}, {job.accepted} accepted, {job.duplicates} duplicates, "
              f"{job.rejected} rejected{' - ' + job.message if job.message else ''}")
        return 0 if job.status == "succeeded" else 1
    if args.command == "purge":
        now = utcnow()
        with transaction(sessions) as session:
            done = {
                "idempotency": session.execute(delete(IdempotencyRecord).where(
                    IdempotencyRecord.created_at < now - timedelta(hours=RETENTION["idempotency_hours"]))).rowcount,
                "rate_limit": session.execute(delete(RateLimitCounter).where(
                    RateLimitCounter.window_start < now.timestamp() - RETENTION["rate_limit_hours"] * 3600
                )).rowcount,
                "request_log": session.execute(delete(RequestLog).where(
                    RequestLog.at < now - timedelta(days=RETENTION["request_log_days"]))).rowcount,
                "saved_valuations": session.execute(delete(SavedValuation).where(
                    SavedValuation.created_at < now - timedelta(days=RETENTION["saved_days"]))).rowcount,
                "api_usage_events": session.execute(delete(ApiUsageEvent).where(
                    ApiUsageEvent.at < now - timedelta(days=RETENTION["usage_days"]))).rowcount,
                "api_valuations": session.execute(delete(ApiValuation).where(
                    ApiValuation.created_at < now - timedelta(days=RETENTION["api_valuation_days"]))).rowcount,
                "expired_sessions": session.execute(delete(AccountSession).where(
                    AccountSession.expires_at < now)).rowcount,
            }
            _audit(session, "purge", done)
        print(json.dumps(done))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
