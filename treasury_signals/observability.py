"""
observability.py — Centralized error tracking + ops alerting.

Two responsibilities:
  1. init_sentry() — start the Sentry SDK once at process boot.
  2. capture_exception(exc, context=...) — drop-in replacement for the previous
     `logger.debug(f"...: {e}")` pattern that silently swallowed errors and let
     bugs (missing source column, wiped shares_outstanding) live for weeks.
  3. notify_admin(message) — escalate sustained operational issues to a
     Telegram admin channel separate from customer-facing paid/free channels.

Sentry SDK no-ops cleanly when SENTRY_DSN is unset, so the helpers are safe
to call from anywhere whether or not Sentry is configured.

Usage:
    from treasury_signals.observability import init_sentry, capture_exception, notify_admin

    # In main.py at startup:
    init_sentry()

    # Replace silent excepts:
    try:
        risky_thing()
    except Exception as e:
        logger.warning(f"risky_thing failed: {e}")
        capture_exception(e, context={"where": "risky_thing", "row_id": row_id})

    # Ops escalation (used by freshness_tracker on sustained failures):
    notify_admin("EDGAR adapter has been failing for 24h+")
"""

import os
import requests
from treasury_signals.logger import get_logger

logger = get_logger(__name__)

_SENTRY_INITIALIZED = False


def init_sentry():
    """
    Initialize Sentry SDK from SENTRY_DSN env var. Safe to call multiple times.
    Adds default tags so all events are filterable by environment + service.
    """
    global _SENTRY_INITIALIZED
    if _SENTRY_INITIALIZED:
        return

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        logger.info("Sentry: SENTRY_DSN not set — error tracking disabled")
        _SENTRY_INITIALIZED = True
        return

    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
            release=os.getenv("RENDER_GIT_COMMIT", "unknown")[:12],
            traces_sample_rate=0.0,  # error tracking only, no perf overhead
            send_default_pii=False,
            attach_stacktrace=True,
            max_breadcrumbs=50,
        )
        sentry_sdk.set_tag("service", "treasury-signals")
        logger.info(f"Sentry: initialized (env={os.getenv('SENTRY_ENVIRONMENT', 'production')})")
    except Exception as e:
        logger.warning(f"Sentry init failed (continuing without): {e}")
    finally:
        _SENTRY_INITIALIZED = True


def capture_exception(exc, context=None):
    """
    Send an exception to Sentry with optional context dict. No-ops if Sentry
    isn't initialized. The caller should still log the error locally — this
    is purely for the remote dashboard.

    Args:
        exc: the exception object (typically the `e` in `except Exception as e`)
        context: optional dict of extra fields (where, row_id, accession, etc.)
    """
    if not _SENTRY_INITIALIZED:
        return
    try:
        import sentry_sdk
        if context:
            with sentry_sdk.push_scope() as scope:
                for k, v in context.items():
                    scope.set_extra(k, v)
                sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.capture_exception(exc)
    except Exception as send_err:
        logger.debug(f"Sentry capture failed: {send_err}")


def capture_message(message, level="warning", context=None):
    """
    Send a non-exception message to Sentry (for important warnings that aren't
    raised exceptions, e.g., "all 17 adapters returned 0").
    """
    if not _SENTRY_INITIALIZED:
        return
    try:
        import sentry_sdk
        if context:
            with sentry_sdk.push_scope() as scope:
                for k, v in context.items():
                    scope.set_extra(k, v)
                sentry_sdk.capture_message(message, level=level)
        else:
            sentry_sdk.capture_message(message, level=level)
    except Exception as send_err:
        logger.debug(f"Sentry capture_message failed: {send_err}")


def notify_admin(message):
    """
    Send an ops-level alert to the Telegram admin channel.

    Reads TELEGRAM_ADMIN_CHANNEL_ID — separate from customer-facing
    TELEGRAM_PAID_CHANNEL_ID / TELEGRAM_FREE_CHANNEL_ID so ops noise doesn't
    leak to paying users. If unset, logs a warning and skips (no spam).

    Used by freshness_tracker for sustained source failures and any other
    "the system is unhealthy" condition.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    admin_chat_id = os.getenv("TELEGRAM_ADMIN_CHANNEL_ID", "").strip()

    if not bot_token or not admin_chat_id:
        logger.warning(f"notify_admin: TELEGRAM_ADMIN_CHANNEL_ID not set — would have sent: {message[:100]}")
        return False

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": admin_chat_id,
                "text": f"🚨 [TSI ADMIN] {message}",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return resp.ok
    except Exception as e:
        logger.warning(f"notify_admin: send failed ({e})")
        capture_exception(e, context={"where": "notify_admin", "msg_preview": message[:100]})
        return False
