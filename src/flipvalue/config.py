"""Settings, read from environment variables. Secrets never have defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Each supported region is valued in exactly one currency; FlipValue never converts.
REGION_CURRENCY: dict[str, str] = {"IN": "INR", "US": "USD"}

ROOT = Path(__file__).resolve().parents[2]
MIN_KEY_LENGTH = 32
DEFAULT_DATABASE_URL = f"sqlite:///{(ROOT / 'var' / 'flipvalue.db').as_posix()}"


class ConfigError(RuntimeError):
    pass


def _keys(name: str) -> tuple[str, ...]:
    return tuple(k.strip() for k in os.environ.get(name, "").split(",") if k.strip())


def _str(name: str, default: str) -> str:
    # Secret Manager values often end with a newline; never let whitespace reach a URL or salt.
    return os.environ.get(name, default).strip()


def _bool(name: str) -> bool:
    return _str(name, "false").lower() == "true"


def _int(name: str, default: int) -> int:
    try:
        return int(_str(name, str(default)) or default)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc


@dataclass(frozen=True)
class Settings:
    # Partner (FixMyTech) and admin keys from the environment. More can be issued into the database with the CLI;
    # both work, so keys can be rotated without downtime.
    api_keys: tuple[str, ...] = ()
    admin_keys: tuple[str, ...] = ()
    database_url: str = DEFAULT_DATABASE_URL
    environment: str = "development"
    rate_limit_per_minute: int = 60          # partner, per key
    public_rate_limit_per_minute: int = 30   # website, per client IP, POST requests
    max_body_bytes: int = 16_384
    request_timeout_s: float = 5.0
    freshness_days: int = 180
    cors_origins: tuple[str, ...] = ()
    trust_proxy: bool = False
    # How many proxies append to X-Forwarded-For in front of the app; the client IP is the entry that many places
    # from the right. Verify after deploying with GET /admin/api/diagnostics/forwarding.
    proxy_hops: int = 1
    public_global_rate_limit_per_minute: int = 600  # all website clients together, POST requests
    hash_salt: str = ""
    frontend_dist: Path | None = ROOT / "frontend" / "dist"
    db_pool_size: int = 5
    db_max_overflow: int = 2
    # Production data must live in a managed database; SQLite is allowed only for local production-like tests.
    allow_sqlite_in_production: bool = False
    # Marketplace providers (docs/DATA_SOURCES.md). Empty = provider not configured; never sent to the browser.
    flipkart_affiliate_id: str = ""
    flipkart_affiliate_token: str = ""
    amazon_credential_id: str = ""
    amazon_credential_secret: str = ""
    amazon_partner_tag: str = ""
    amazon_token_url: str = ""
    provider_timeout_s: float = 8.0
    offer_fresh_hours: int = 24
    offer_max_age_days: int = 14
    provider_min_refresh_minutes: int = 60
    # Developer platform: self-service keys get these limits unless an operator sets others.
    developer_signup: bool = True
    developer_rate_limit_per_minute: int = 60
    developer_daily_quota: int = 1000
    max_keys_per_account: int = 5
    # Secure cookie flag: always in production; off locally so http://127.0.0.1 works.
    secure_cookies: bool = False

    def __post_init__(self) -> None:
        if any(len(key) < MIN_KEY_LENGTH for key in (*self.api_keys, *self.admin_keys)):
            raise ConfigError(f"Every API key must be at least {MIN_KEY_LENGTH} characters.")
        if set(self.api_keys) & set(self.admin_keys):
            raise ConfigError("A key cannot be both a partner key and an admin key.")
        if self.environment not in ("development", "production"):
            raise ConfigError("FLIPVALUE_ENV must be 'development' or 'production'.")
        if min(self.rate_limit_per_minute, self.public_rate_limit_per_minute,
               self.public_global_rate_limit_per_minute) < 1:
            raise ConfigError("Rate limits must be >= 1.")
        if self.freshness_days < 1:
            raise ConfigError("FLIPVALUE_FRESHNESS_DAYS must be >= 1.")
        if not 1 <= self.proxy_hops <= 5:
            raise ConfigError("FLIPVALUE_PROXY_HOPS must be 1-5.")
        if min(self.developer_rate_limit_per_minute, self.developer_daily_quota, self.max_keys_per_account,
               self.offer_fresh_hours, self.offer_max_age_days) < 1:
            raise ConfigError("Developer limits and offer freshness settings must be >= 1.")
        if self.provider_min_refresh_minutes < 15:
            raise ConfigError("FLIPVALUE_PROVIDER_MIN_REFRESH_MINUTES must be >= 15 (respect provider limits).")
        if self.amazon_token_url and not self.amazon_token_url.startswith("https://"):
            raise ConfigError("FLIPVALUE_AMAZON_TOKEN_URL must be an https:// URL.")
        if any(o == "*" or not o.startswith(("http://", "https://")) for o in self.cors_origins):
            raise ConfigError("FLIPVALUE_CORS_ORIGINS must list exact origins like https://example.web.app (no '*').")
        if self.environment == "production":
            if len(self.hash_salt) < MIN_KEY_LENGTH:
                raise ConfigError("FLIPVALUE_HASH_SALT (>= 32 characters) is required in production.")
            if self.database_url.startswith("sqlite") and not self.allow_sqlite_in_production:
                raise ConfigError("SQLite is not allowed in production (ephemeral, single-writer); use PostgreSQL.")
            if any(o.startswith("http://") for o in self.cors_origins):
                raise ConfigError("Production CORS origins must use https://.")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cookie_secure(self) -> bool:
        return self.is_production or self.secure_cookies

    @classmethod
    def from_env(cls) -> Settings:
        dist = _str("FLIPVALUE_FRONTEND_DIST", "")
        return cls(
            api_keys=_keys("FLIPVALUE_API_KEYS"),
            admin_keys=_keys("FLIPVALUE_ADMIN_KEYS"),
            database_url=_str("FLIPVALUE_DATABASE_URL", DEFAULT_DATABASE_URL),
            environment=_str("FLIPVALUE_ENV", "development"),
            rate_limit_per_minute=_int("FLIPVALUE_RATE_LIMIT_PER_MIN", 60),
            public_rate_limit_per_minute=_int("FLIPVALUE_PUBLIC_RATE_LIMIT_PER_MIN", 30),
            public_global_rate_limit_per_minute=_int("FLIPVALUE_PUBLIC_GLOBAL_RATE_LIMIT_PER_MIN", 600),
            max_body_bytes=_int("FLIPVALUE_MAX_BODY_BYTES", 16_384),
            request_timeout_s=float(_int("FLIPVALUE_REQUEST_TIMEOUT_S", 5)),
            freshness_days=_int("FLIPVALUE_FRESHNESS_DAYS", 180),
            cors_origins=_keys("FLIPVALUE_CORS_ORIGINS"),
            trust_proxy=_bool("FLIPVALUE_TRUST_PROXY"),
            proxy_hops=_int("FLIPVALUE_PROXY_HOPS", 1),
            hash_salt=_str("FLIPVALUE_HASH_SALT", ""),
            frontend_dist=Path(dist) if dist else ROOT / "frontend" / "dist",
            db_pool_size=_int("FLIPVALUE_DB_POOL_SIZE", 5),
            db_max_overflow=_int("FLIPVALUE_DB_MAX_OVERFLOW", 2),
            allow_sqlite_in_production=_bool("FLIPVALUE_ALLOW_SQLITE_IN_PRODUCTION"),
            flipkart_affiliate_id=_str("FLIPVALUE_FLIPKART_AFFILIATE_ID", ""),
            flipkart_affiliate_token=_str("FLIPVALUE_FLIPKART_AFFILIATE_TOKEN", ""),
            amazon_credential_id=_str("FLIPVALUE_AMAZON_CREDENTIAL_ID", ""),
            amazon_credential_secret=_str("FLIPVALUE_AMAZON_CREDENTIAL_SECRET", ""),
            amazon_partner_tag=_str("FLIPVALUE_AMAZON_PARTNER_TAG", ""),
            amazon_token_url=_str("FLIPVALUE_AMAZON_TOKEN_URL", ""),
            provider_timeout_s=float(_int("FLIPVALUE_PROVIDER_TIMEOUT_S", 8)),
            offer_fresh_hours=_int("FLIPVALUE_OFFER_FRESH_HOURS", 24),
            offer_max_age_days=_int("FLIPVALUE_OFFER_MAX_AGE_DAYS", 14),
            provider_min_refresh_minutes=_int("FLIPVALUE_PROVIDER_MIN_REFRESH_MINUTES", 60),
            developer_signup=_str("FLIPVALUE_DEVELOPER_SIGNUP", "open").lower() != "closed",
            developer_rate_limit_per_minute=_int("FLIPVALUE_DEVELOPER_RATE_LIMIT_PER_MIN", 60),
            developer_daily_quota=_int("FLIPVALUE_DEVELOPER_DAILY_QUOTA", 1000),
            max_keys_per_account=_int("FLIPVALUE_MAX_KEYS_PER_ACCOUNT", 5),
            secure_cookies=_bool("FLIPVALUE_SECURE_COOKIES"),
        )
