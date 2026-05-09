"""Centralized config — single source of truth for env vars + hardcoded constants.

═════════════════════════════════════════════════════════════════════════
POLICY: NEW CODE MUST USE THIS MODULE

Any new module that needs an env var MUST add a field to Settings + the
matching `_required(...)` or `_optional(...)` call in get_settings(),
then access via `get_settings().my_field`. Do NOT reach for `os.getenv`
in business logic — every env var lives here.

EXISTING CODE migrates "as touched": when you edit a module that still
calls `os.getenv("FOO")` directly, swap it for `get_settings().foo` in
the same PR. Never open a file solely to migrate.

Modules already migrated: main.py, scheduler/helpers.py.
═════════════════════════════════════════════════════════════════════════

Two layers:

  1. Module-level constants (SCAN_HOURS, FALLBACK_EMAIL_RECIPIENTS, etc.) —
     hardcoded values that aren't env-derived. Changing the scan schedule
     or the admin email used to mean editing 2-3 different files. Now it's
     one line here.

  2. Settings dataclass + get_settings() — env-var-backed configuration.
     SUPABASE_URL and SUPABASE_KEY are required (everything that touches
     the DB imports the supabase client at module load and crashes hard
     without them). Everything else is optional — the underlying modules
     have their own code-level fallbacks (e.g., scan_korea_dart silently
     skips when DART_API_KEY is unset; freshness_tracker.notify_admin
     no-ops when TELEGRAM_ADMIN_CHANNEL_ID is unset).

Usage:
    from treasury_signals.config import get_settings, SCAN_HOURS

    settings = get_settings()
    if settings.dart_api_key:
        # Korea filing adapter is configured

    for hour in SCAN_HOURS:
        ...

Lazy init: importing this module DOES NOT trigger env var validation —
get_settings() does, on first call. Lets tests import config-aware code
without needing every prod env var present.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Tuple


class ConfigError(RuntimeError):
    """Raised when a required env var is missing or malformed at startup."""


# ════════════════════════════════════════════════════════════════════════
# HARDCODED CONSTANTS — change here, not in 5 different files
# ════════════════════════════════════════════════════════════════════════

# Scan schedule (UTC hours when the scan loop fires)
SCAN_HOURS: Tuple[int, ...] = (6, 12, 18)

# Email used by send_daily_email when subscribers table is empty
FALLBACK_EMAIL_RECIPIENTS: Tuple[str, ...] = (
    "contact@quantedgeriskadvisory.com",
)


# ════════════════════════════════════════════════════════════════════════
# ENV-VAR-BACKED SETTINGS
# ════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Settings:
    """Validated env-derived configuration. Built once via get_settings().

    Required: only SUPABASE_URL and SUPABASE_KEY — everything that touches
    the DB imports a supabase client at module load and would crash hard
    without them. Other vars are optional with code-level fallbacks.

    Add a new env var by adding a field here AND a corresponding line
    (`_required(...)` or `_optional(...)`) in get_settings(). Update the
    README env-vars table in the same change.
    """

    # ── Required ──
    supabase_url: str
    supabase_key: str

    # ── Optional (code-level fallbacks exist) ──
    twitter_api_key: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_paid_channel_id: Optional[str] = None
    telegram_free_channel_id: Optional[str] = None        # newer name
    telegram_channel_id: Optional[str] = None             # older alias used by some modules
    telegram_admin_channel_id: Optional[str] = None       # ops escalator channel
    telegram_error_alerts: Optional[str] = None
    resend_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    sentry_dsn: Optional[str] = None
    sentry_environment: str = "production"
    dart_api_key: Optional[str] = None                    # Korea filings
    edinet_api_key: Optional[str] = None                  # Japan filings
    coingecko_api_key: Optional[str] = None               # higher rate limit
    cryptoquant_api_key: Optional[str] = None             # exchange flow data
    database_url: Optional[str] = None                    # for migration_runner auto-mode
    dashboard_url: Optional[str] = None
    admin_email: str = "contact@quantedgeriskadvisory.com"
    email_from_address: str = "briefing@quantedgeriskadvisory.com"
    email_from_name: str = "Treasury Signal Intelligence"
    email_reply_to: Optional[str] = None
    log_dir: Optional[str] = None
    log_level_console: str = "INFO"
    log_level_file: str = "DEBUG"


def _required(key: str) -> str:
    v = (os.getenv(key) or "").strip()
    if not v:
        raise ConfigError(
            f"Required env var {key} is not set. See README env-vars table."
        )
    return v


def _optional(key: str, default: Optional[str] = None) -> Optional[str]:
    v = (os.getenv(key) or "").strip()
    return v if v else default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build the Settings singleton from current env vars.

    Cached after first call. Tests that need to override env vars should
    call get_settings.cache_clear() after modifying os.environ.
    """
    return Settings(
        # Required
        supabase_url=_required("SUPABASE_URL"),
        supabase_key=_required("SUPABASE_KEY"),
        # Optional
        twitter_api_key=_optional("TWITTER_API_KEY"),
        telegram_bot_token=_optional("TELEGRAM_BOT_TOKEN"),
        telegram_paid_channel_id=_optional("TELEGRAM_PAID_CHANNEL_ID"),
        telegram_free_channel_id=_optional("TELEGRAM_FREE_CHANNEL_ID"),
        telegram_channel_id=_optional("TELEGRAM_CHANNEL_ID"),
        telegram_admin_channel_id=_optional("TELEGRAM_ADMIN_CHANNEL_ID"),
        telegram_error_alerts=_optional("TELEGRAM_ERROR_ALERTS"),
        resend_api_key=_optional("RESEND_API_KEY"),
        anthropic_api_key=_optional("ANTHROPIC_API_KEY"),
        sentry_dsn=_optional("SENTRY_DSN"),
        sentry_environment=_optional("SENTRY_ENVIRONMENT", "production"),
        dart_api_key=_optional("DART_API_KEY"),
        edinet_api_key=_optional("EDINET_API_KEY"),
        coingecko_api_key=_optional("COINGECKO_API_KEY"),
        cryptoquant_api_key=_optional("CRYPTOQUANT_API_KEY"),
        database_url=_optional("DATABASE_URL"),
        dashboard_url=_optional("DASHBOARD_URL"),
        admin_email=_optional("ADMIN_EMAIL", "contact@quantedgeriskadvisory.com"),
        email_from_address=_optional("EMAIL_FROM_ADDRESS", "briefing@quantedgeriskadvisory.com"),
        email_from_name=_optional("EMAIL_FROM_NAME", "Treasury Signal Intelligence"),
        email_reply_to=_optional("EMAIL_REPLY_TO"),
        log_dir=_optional("LOG_DIR"),
        log_level_console=_optional("LOG_LEVEL_CONSOLE", "INFO"),
        log_level_file=_optional("LOG_LEVEL_FILE", "DEBUG"),
    )
