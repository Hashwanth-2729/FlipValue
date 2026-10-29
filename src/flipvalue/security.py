"""API keys (partner/admin roles, scopes, per-key limits), database-backed rate limiting and client fingerprints."""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from flipvalue.db.models import ApiClient, RateLimitCounter, utcnow
from flipvalue.db.session import transaction

ROLES = ("partner", "admin")
KEY_PREFIX = "fv_"
# What a partner key may read. Usage of the calling key itself needs no scope.
SCOPES = ("valuation:read", "market_prices:read", "price_history:read")
MAX_KEY_LENGTH = 200


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def new_key() -> str:
    """256 random bits from the OS CSPRNG. A SHA-256 verifier of a key this random cannot be brute-forced, so no
    slow hash (or pepper) is needed, and lookup by the verifier stays an indexed equality query."""
    return KEY_PREFIX + secrets.token_urlsafe(32)


def parse_scopes(text: str) -> tuple[str, ...]:
    return tuple(s for s in text.split(",") if s in SCOPES)


@dataclass(frozen=True)
class KeyInfo:
    """The authenticated caller. `label` is non-secret and safe to log."""

    label: str
    role: str
    scopes: tuple[str, ...]
    client_id: int | None = None          # None for environment keys
    account_id: int | None = None
    rate_limit_per_minute: int | None = None
    daily_quota: int | None = None

    def owner(self) -> str:
        """Who owns records this key creates: the account when there is one, so sibling keys share them."""
        return f"acct-{self.account_id}" if self.account_id else self.label


class Authenticator:
    """Keys from the environment (bootstrap) plus keys issued into the database (rotatable, revocable).

    Only SHA-256 hashes are held. Environment keys are compared in constant time against every candidate;
    database keys are found by an indexed lookup of the hash, which reveals nothing usable about a key.
    """

    def __init__(self, sessions: sessionmaker[Session], env_keys: dict[str, Iterable[str]]) -> None:
        self._sessions = sessions
        self._env = [(role, hash_key(k)) for role, keys in env_keys.items() for k in keys]

    def lookup(self, presented: str | None, role: str) -> KeyInfo | None:
        """The caller for a valid, unrevoked key with this role, else None. Revocation applies to the next request:
        nothing is cached."""
        if not presented or len(presented) > MAX_KEY_LENGTH:
            return None
        candidate = hash_key(presented)
        matched = None
        for key_role, digest in self._env:
            if hmac.compare_digest(candidate, digest) and key_role == role:
                matched = KeyInfo(label=f"env-{role}-{digest[:8]}", role=role,
                                  scopes=SCOPES if role == "partner" else ())
        if matched:
            return matched
        with transaction(self._sessions) as session:
            client = session.scalar(select(ApiClient).where(ApiClient.key_hash == candidate))
            if client and client.role == role and client.revoked_at is None:
                return KeyInfo(label=f"db-{client.id}-{client.name}"[:64], role=role,
                               scopes=parse_scopes(client.scopes), client_id=client.id,
                               account_id=client.account_id, rate_limit_per_minute=client.rate_limit_per_minute,
                               daily_quota=client.daily_quota)
        return None

    def identify(self, presented: str | None, role: str) -> str | None:
        """Return a non-secret client label for a valid, unrevoked key with this role, else None."""
        info = self.lookup(presented, role)
        return info.label if info else None


def issue_key(session: Session, name: str, role: str, *, scopes: Iterable[str] | None = None,
              account_id: int | None = None, rate_limit_per_minute: int | None = None,
              daily_quota: int | None = None) -> tuple[ApiClient, str]:
    """Create a key. The raw key is returned once and never stored."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    chosen = tuple(SCOPES if scopes is None and role == "partner" else (scopes or ()))
    if any(s not in SCOPES for s in chosen):
        raise ValueError(f"scopes must be among {', '.join(SCOPES)}")
    key = new_key()
    client = ApiClient(name=name[:80], role=role, key_prefix=key[:10], key_hash=hash_key(key),
                       scopes=",".join(s for s in SCOPES if s in chosen), account_id=account_id,
                       rate_limit_per_minute=rate_limit_per_minute, daily_quota=daily_quota)
    session.add(client)
    session.flush()
    return client, key


def revoke_key(session: Session, client_id: int) -> bool:
    client = session.get(ApiClient, client_id)
    if client is None or client.revoked_at is not None:
        return False
    client.revoked_at = utcnow()
    return True


@dataclass(frozen=True)
class Usage:
    limit: int
    count: int
    reset_s: int

    @property
    def allowed(self) -> bool:
        return self.count <= self.limit

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.count)


class RateLimiter:
    """Fixed one-minute windows counted in the database, so limits hold across server processes.

    A burst of up to 2x the limit is possible across a window boundary.
    """

    WINDOW_S = 60

    def __init__(self, sessions: sessionmaker[Session], clock: Callable[[], float] = time.time) -> None:
        self._sessions = sessions
        self._clock = clock

    def hit(self, bucket: str, limit: int) -> int | None:
        """Count one request. Return None if allowed, else whole seconds until the window resets."""
        usage = self.consume(bucket, limit)
        return None if usage.allowed else usage.reset_s

    def consume(self, bucket: str, limit: int, window_s: int | None = None) -> Usage:
        """Count one request in a fixed window of `window_s` seconds (default one minute)."""
        window_s = window_s or self.WINDOW_S
        now = self._clock()
        window = int(now // window_s) * window_s
        with transaction(self._sessions) as session:
            count = self._increment(session, bucket, window)
        return Usage(limit=limit, count=count, reset_s=max(1, math.ceil(window + window_s - now)))

    def peek(self, bucket: str, window_s: int | None = None) -> int:
        """Requests counted so far in the current window, without counting one."""
        window_s = window_s or self.WINDOW_S
        window = int(self._clock() // window_s) * window_s
        with transaction(self._sessions) as session:
            return session.scalar(select(RateLimitCounter.count).where(
                RateLimitCounter.bucket == bucket, RateLimitCounter.window_start == window)) or 0

    @staticmethod
    def _increment(session: Session, bucket: str, window: int) -> int:
        stmt = (update(RateLimitCounter)
                .where(RateLimitCounter.bucket == bucket, RateLimitCounter.window_start == window)
                .values(count=RateLimitCounter.count + 1))
        if session.execute(stmt).rowcount == 0:
            try:
                with session.begin_nested():
                    session.add(RateLimitCounter(bucket=bucket, window_start=window, count=1))
                return 1
            except IntegrityError:  # another process created the row first
                session.execute(stmt)
        return session.scalar(select(RateLimitCounter.count).where(
            RateLimitCounter.bucket == bucket, RateLimitCounter.window_start == window)) or 1


def client_fingerprint(ip: str, salt: str) -> str:
    """Salted hash of the client IP: enough to rate-limit, not stored anywhere else."""
    return hashlib.sha256(f"{salt}|{ip}".encode()).hexdigest()[:24]
