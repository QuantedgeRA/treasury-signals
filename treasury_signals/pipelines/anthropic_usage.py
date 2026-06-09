"""
anthropic_usage.py — Claude API spend monitoring
=================================================
Every Claude API response carries a `usage` block (input_tokens / output_tokens).
This module turns that into a durable per-day-per-model cost aggregate
(anthropic_usage_daily, migration 0029) and fires a one-shot admin alert when the
day's estimated spend crosses a soft cap. Before this, Anthropic spend had ZERO
visibility — the one external cost that scales with filing volume was unmonitored.

Design: best-effort + fail-open. record_usage() never raises and never blocks the
extraction caller; if the table/RPC is absent (pre-migration) it just logs. The
cost figure is an ESTIMATE from a published price table — close enough to catch a
runaway, not a billing-grade number.
"""
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

from treasury_signals.logger import get_logger
from treasury_signals.observability import notify_admin

logger = get_logger(__name__)
load_dotenv()

_SUPABASE_URL = os.getenv("SUPABASE_URL")
_SUPABASE_KEY = os.getenv("SUPABASE_KEY")
# Best-effort client; if creds are missing the tracker simply no-ops.
try:
    _supabase = create_client(_SUPABASE_URL, _SUPABASE_KEY) if _SUPABASE_URL and _SUPABASE_KEY else None
except Exception:
    _supabase = None

# USD per 1,000,000 tokens, (input, output). Keep roughly in sync with
# https://www.anthropic.com/pricing — order matters (longest/most-specific keys
# first so 'claude-3-5-haiku' doesn't match the generic 'claude' before 'haiku').
MODEL_PRICES = {
    "haiku": (0.80, 4.0),
    "opus": (15.0, 75.0),
    "sonnet": (3.0, 15.0),
}
DEFAULT_PRICE = (3.0, 15.0)  # assume Sonnet-class if the model string is unknown

# Soft daily cap. When the day's estimated spend crosses this, alert admin ONCE
# (per process per day). Override via env without a code change.
def _daily_cap() -> float:
    try:
        return float(os.getenv("ANTHROPIC_DAILY_COST_ALERT_USD", "25") or 25)
    except (TypeError, ValueError):
        return 25.0


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated USD cost of one call from the published per-MTok price table."""
    lowered = (model or "").lower()
    in_price, out_price = DEFAULT_PRICE
    for key, prices in MODEL_PRICES.items():
        if key in lowered:
            in_price, out_price = prices
            break
    return (input_tokens / 1_000_000.0) * in_price + (output_tokens / 1_000_000.0) * out_price


# Process-local guard so the cap alert fires at most once per day per process.
_alerted_dates: set[str] = set()


def usage_from_response(data: dict) -> tuple[int, int]:
    """Pull (input_tokens, output_tokens) from a raw Anthropic messages response."""
    usage = (data or {}).get("usage", {}) or {}
    try:
        return int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)
    except (TypeError, ValueError):
        return 0, 0


def record_usage(model: str, input_tokens: int, output_tokens: int, where: str = "") -> float:
    """Fold one Claude call into today's aggregate. Returns the call's est cost.

    Best-effort: logs always; persists + cap-checks when the DB is reachable.
    Never raises — extraction must not break because usage tracking hiccupped.
    """
    try:
        input_tokens = int(input_tokens or 0)
        output_tokens = int(output_tokens or 0)
    except (TypeError, ValueError):
        input_tokens, output_tokens = 0, 0

    cost = estimate_cost(model, input_tokens, output_tokens)
    logger.info(
        f"  Anthropic usage [{where or 'extraction'}]: {model} "
        f"in={input_tokens} out={output_tokens} ~${cost:.4f}"
    )

    if not _supabase:
        return cost

    today = datetime.now(timezone.utc).date().isoformat()
    try:
        res = _supabase.rpc("record_anthropic_usage", {
            "p_date": today,
            "p_model": model or "unknown",
            "p_input": input_tokens,
            "p_output": output_tokens,
            "p_cost": round(cost, 6),
        }).execute()
        day_total = float(res.data or 0)
    except Exception as e:
        # Pre-migration (table/RPC absent) or transient DB error → just log.
        logger.debug(f"  Anthropic usage persist failed [{where}]: {e}")
        return cost

    cap = _daily_cap()
    if day_total >= cap and today not in _alerted_dates:
        _alerted_dates.add(today)
        try:
            notify_admin(
                f"⚠️ Anthropic spend today is ~${day_total:.2f}, over the "
                f"${cap:.0f} soft cap. Check anthropic_usage_daily for the breakdown."
            )
        except Exception:
            pass
    return cost


def get_todays_spend() -> dict:
    """Return today's spend summary: {date, total_usd, by_model:[...]}. Best-effort."""
    if not _supabase:
        return {"date": None, "total_usd": 0.0, "by_model": []}
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        res = _supabase.table("anthropic_usage_daily").select("*").eq("usage_date", today).execute()
        rows = res.data or []
        return {
            "date": today,
            "total_usd": round(sum(float(r.get("est_cost_usd") or 0) for r in rows), 4),
            "by_model": rows,
        }
    except Exception as e:
        logger.debug(f"  Anthropic spend read failed: {e}")
        return {"date": today, "total_usd": 0.0, "by_model": []}
