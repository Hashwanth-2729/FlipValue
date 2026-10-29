"""Accounts for the developer portal and watchlists: scrypt password hashes and server-side sessions.

A session token lives only in an HttpOnly cookie; the database holds its SHA-256. Valuing a phone never needs an
account.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from flipvalue.db.models import Account, AccountSession, utcnow
from flipvalue.security import hash_key

# Firebase Hosting forwards only a cookie named __session to Cloud Run (it strips all others), so the website, which
# is served through Hosting, can sign in only if the session cookie has exactly this name.
SESSION_COOKIE = "__session"
SESSION_DAYS = 14
MIN_PASSWORD = 10
MAX_PASSWORD = 200
# scrypt cost: n=2^14, r=8, p=1 uses 16 MiB and ~50 ms; well above OWASP's minimum.
_N, _R, _P = 2**14, 8, 1
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,63}$")


class AccountError(ValueError):
    pass


def normalise_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise AccountError("Enter a valid email address.")
    return email


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    encoded = (base64.b64encode(salt).decode(), base64.b64encode(digest).decode())
    return f"scrypt${_N}${_R}${_P}${encoded[0]}${encoded[1]}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                                dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, base64.b64decode(digest))


# Verifying against this when the email is unknown keeps response times alike for known and unknown emails.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def check_password_rules(password: str) -> None:
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise AccountError(f"Use a password of {MIN_PASSWORD} to {MAX_PASSWORD} characters.")


def register(session: Session, email: str, password: str) -> Account:
    email = normalise_email(email)
    check_password_rules(password)
    if session.scalar(select(Account.id).where(Account.email == email)) is not None:
        raise AccountError("An account with this email already exists. Sign in instead.")
    account = Account(email=email, password_hash=hash_password(password))
    session.add(account)
    session.flush()
    return account


def authenticate(session: Session, email: str, password: str) -> Account | None:
    try:
        email = normalise_email(email)
    except AccountError:
        return None
    account = session.scalar(select(Account).where(Account.email == email))
    if account is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, account.password_hash) or account.disabled_at is not None:
        return None
    return account


def start_session(session: Session, account: Account, now: datetime | None = None) -> str:
    now = now or utcnow()
    token = secrets.token_urlsafe(32)
    session.execute(delete(AccountSession).where(AccountSession.expires_at < now))
    session.add(AccountSession(account_id=account.id, token_hash=hash_key(token), created_at=now,
                               expires_at=now + timedelta(days=SESSION_DAYS)))
    return token


def account_for(session: Session, token: str | None, now: datetime | None = None) -> Account | None:
    if not token or len(token) > 100:
        return None
    row = session.scalar(select(AccountSession).where(AccountSession.token_hash == hash_key(token)))
    if row is None or row.expires_at < (now or utcnow()):
        return None
    account = session.get(Account, row.account_id)
    return account if account and account.disabled_at is None else None


def end_session(session: Session, token: str | None) -> None:
    if token:
        session.execute(delete(AccountSession).where(AccountSession.token_hash == hash_key(token)))
