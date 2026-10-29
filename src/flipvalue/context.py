"""Per-application objects shared by routes and middleware."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine as DbEngine
from sqlalchemy.orm import Session, sessionmaker

from flipvalue.config import Settings
from flipvalue.db.models import utcnow
from flipvalue.db.session import transaction
from flipvalue.engine import Engine
from flipvalue.marketplace.providers import AmazonCreators, CashifyManual, FlipkartAffiliate, Provider
from flipvalue.marketplace.service import OfferPolicy
from flipvalue.security import Authenticator, RateLimiter


@dataclass
class AppContext:
    settings: Settings
    db: DbEngine
    sessions: sessionmaker[Session]
    engine: Engine
    auth: Authenticator
    limiter: RateLimiter
    hash_salt: str
    providers: Sequence[Provider] = ()
    offer_policy: OfferPolicy = OfferPolicy()


def build_providers(settings: Settings) -> list[Provider]:
    """Every provider FlipValue knows; unconfigured ones report what they need instead of failing."""
    return [
        FlipkartAffiliate(settings.flipkart_affiliate_id, settings.flipkart_affiliate_token,
                          timeout_s=settings.provider_timeout_s),
        AmazonCreators(settings.amazon_credential_id, settings.amazon_credential_secret, settings.amazon_partner_tag,
                       settings.amazon_token_url, timeout_s=settings.provider_timeout_s),
        CashifyManual(),
    ]


def offer_policy(settings: Settings, clock: Callable[[], datetime] = utcnow) -> OfferPolicy:
    return OfferPolicy(fresh_hours=settings.offer_fresh_hours, max_age_days=settings.offer_max_age_days,
                       min_refresh_minutes=settings.provider_min_refresh_minutes,
                       include_mock=not settings.is_production, clock=clock)


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def get_session(request: Request) -> Iterator[Session]:
    with transaction(request.app.state.ctx.sessions) as session:
        yield session


# scope="function": commit before the response is sent, so a client never sees success for an uncommitted write
# and the middleware's own writes never wait on the route's lock.
DbSession = Annotated[Session, Depends(get_session, scope="function")]
