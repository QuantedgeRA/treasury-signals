"""
pre_announcement_persister.py — persist CorrelationEngineV2 state to DB.

Two responsibilities:
  feed_filing_excerpts_to_engine()
      Pulls the last 48h of filing_excerpts (from the Week 2-3 build),
      filters by impact >= 50, calls engine.add_filing_excerpt() for
      each. Runs once per scheduler tick BEFORE phase_5_correlation, so
      the engine has the latest filing-excerpt context when it scores.

  persist_correlation_snapshot(result)
      Takes engine.calculate_correlation() output and writes per-company
      rows into pre_announcement_signals. Inherits threshold_at from
      prior rows so we can measure lead time once a confirmed purchase
      lands.

Both functions no-op gracefully when their DB tables don't exist
(migration 0011 / 0012 not yet applied), logging a warning so operators
notice.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from dotenv import load_dotenv
from supabase import create_client

from treasury_signals.logger import get_logger
from treasury_signals.observability import capture_exception

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Hard caps to keep one tick's DB chatter bounded.
MAX_EXCERPTS_TO_FEED = 100
MAX_SNAPSHOT_ROWS = 50
EXCERPT_LOOKBACK_HOURS = 48
SNAPSHOT_THRESHOLD_SCORE = 30  # only persist rows with at least this score


# ────────────────────────── STREAM 7 FEEDER ──────────────────────────────


def feed_filing_excerpts_to_engine(engine) -> int:
    """Pull recent filing_excerpts and pour them into the correlation engine.

    Returns count of excerpts successfully fed. Called once per scheduler
    tick BEFORE the regular signal-collection phases so filing-excerpt
    signals coexist with tweets / 8-Ks / whale / etc.

    Engine state is in-memory and accumulates across ticks. Within the
    48h window, the same excerpt would get re-added each tick — fine
    because CompanySignal.timestamp gets refreshed, so the signal
    stays "live". A future optimization could track fed excerpt ids
    in process memory, but the DB read is cheap and the duplicate
    insertion is idempotent in scoring (the dedup happens implicitly
    when the engine cleans up old signals).
    """
    cutoff = (datetime.utcnow() - timedelta(hours=EXCERPT_LOOKBACK_HOURS)).isoformat()

    try:
        res = (
            supabase.table("filing_excerpts")
            .select(
                "id, accession_number, company_name, ticker, filing_date, "
                "filing_url, form_type, excerpt_text, claude_summary, "
                "impact_score, category, btc_amount, usd_amount, created_at"
            )
            .gte("created_at", cutoff)
            .gte("impact_score", 50)
            .order("impact_score", desc=True)
            .limit(MAX_EXCERPTS_TO_FEED)
            .execute()
        )
        excerpts = res.data or []
    except Exception as e:
        # filing_excerpts table may not exist if migration 0011 hasn't
        # been applied yet. Loud warning, not a crash.
        logger.warning(f"  Pre-announce feeder: filing_excerpts read error (run migration 0011?): {e}")
        return 0

    if not excerpts:
        logger.debug("  Pre-announce feeder: no recent excerpts to feed")
        return 0

    fed = 0
    for excerpt in excerpts:
        try:
            engine.add_filing_excerpt(excerpt)
            fed += 1
        except Exception as e:
            logger.debug(f"  Pre-announce feeder: engine.add_filing_excerpt failed for ticker={excerpt.get('ticker')}: {e}")

    logger.info(f"Pre-announce feeder: fed {fed} filing excerpts into correlation engine")
    return fed


# ────────────────────────── SNAPSHOT PERSISTER ───────────────────────────


def _existing_threshold_at_for_ticker(ticker: str) -> str | None:
    """Look up the most recent row's threshold_at for this ticker, if any.
    Used to preserve 'first time this company crossed 60' across snapshots."""
    if not ticker:
        return None
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    try:
        res = (
            supabase.table("pre_announcement_signals")
            .select("threshold_at")
            .eq("ticker", ticker)
            .gte("snapshot_at", cutoff)
            .not_.is_("threshold_at", "null")
            .order("snapshot_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0]["threshold_at"] if rows else None
    except Exception as e:
        logger.debug(f"  Pre-announce persister: threshold_at lookup error for {ticker}: {e}")
        return None


def _build_components_blob(company_data: dict, engine_result: dict) -> dict:
    """Build the JSONB `components` payload for a snapshot row.

    Mirrors the engine output shape but trimmed to what the dashboard
    needs. Includes the source filing_excerpt id if a filing_excerpt
    signal was the highest-scoring contribution — gives the frontend
    a deep link target.
    """
    reasons = company_data.get("reasons", [])[:8]
    streams = list(company_data.get("streams", []))

    # Find the highest-scoring filing_excerpt signal for this company, if any
    top_excerpt_id = None
    top_filing_url = None
    for signal in company_data.get("signals", []):
        if getattr(signal, "stream", "") == "filing_excerpt" and getattr(signal, "excerpt_id", None):
            top_excerpt_id = signal.excerpt_id
            break

    return {
        "streams": streams,
        "reasons": reasons,
        "top_excerpt_id": top_excerpt_id,
        "top_filing_url": top_filing_url,
        "fear_greed": engine_result.get("fear_greed"),
        "btc_weekly_change": engine_result.get("btc_weekly_change"),
    }


def persist_correlation_snapshot(engine_result: dict) -> int:
    """Write the engine's per-company correlation snapshot to DB.

    Args:
        engine_result: dict from engine.calculate_correlation()

    Returns:
        Count of rows inserted.

    Skips companies with score < SNAPSHOT_THRESHOLD_SCORE (30). Inserts
    one row per ticker per call — the table is intentionally
    history-friendly so the dashboard can show "X has been signaling
    since Tuesday".
    """
    top_companies = engine_result.get("top_companies", []) or []
    if not top_companies:
        logger.debug("  Pre-announce persister: no companies above threshold")
        return 0

    market_score = engine_result.get("market_score") or engine_result.get("correlated_score") or 0
    alert_level = engine_result.get("alert_level") or "NONE"
    now_iso = datetime.utcnow().isoformat()

    rows = []
    for company_data in top_companies[:MAX_SNAPSHOT_ROWS]:
        score = int(company_data.get("score") or 0)
        if score < SNAPSHOT_THRESHOLD_SCORE:
            continue

        ticker = (company_data.get("ticker") or "").upper()
        if not ticker:
            continue

        # threshold_at: inherit from prior row if present, else stamp now if score >= 60
        prior_threshold = _existing_threshold_at_for_ticker(ticker)
        threshold_at = prior_threshold or (now_iso if score >= 60 else None)

        rows.append({
            "ticker": ticker,
            "company": (company_data.get("company") or "")[:200],
            "score": min(100, max(0, score)),
            "raw_score": int(company_data.get("raw_score") or 0),
            "num_streams": int(company_data.get("num_streams") or 0),
            "multiplier": float(company_data.get("multiplier") or 1.0),
            "components": _build_components_blob(company_data, engine_result),
            "market_score": min(100, max(0, int(market_score))),
            "alert_level": alert_level,
            "threshold_at": threshold_at,
        })

    if not rows:
        logger.debug("  Pre-announce persister: no rows met threshold for persistence")
        return 0

    try:
        supabase.table("pre_announcement_signals").insert(rows).execute()
    except Exception as e:
        # Table may not exist yet — migration 0012 gate
        logger.warning(f"  Pre-announce persister: insert failed (run migration 0012?): {e}")
        capture_exception(e, context={
            "where": "pre_announcement_persister.persist_correlation_snapshot",
            "row_count": len(rows),
        })
        return 0

    logger.info(f"Pre-announce persister: snapshot stored — {len(rows)} companies (market score {market_score}, level {alert_level})")
    return len(rows)


# ────────────────────────── RETENTION CLEANUP ────────────────────────────


def cleanup_old_snapshots(retention_days: int = 7) -> int:
    """Delete snapshots older than `retention_days`. Optional housekeeping.

    Not wired into the scheduler by default — the partial index keeps
    queries fast even with millions of rows. Run manually or via a
    weekly cron if you want to bound the table size.
    """
    cutoff = (datetime.utcnow() - timedelta(days=retention_days)).isoformat()
    try:
        res = (
            supabase.table("pre_announcement_signals")
            .delete()
            .lt("snapshot_at", cutoff)
            .execute()
        )
        deleted = len(res.data or [])
        logger.info(f"Pre-announce cleanup: removed {deleted} snapshots older than {retention_days}d")
        return deleted
    except Exception as e:
        logger.warning(f"  Pre-announce cleanup error: {e}")
        return 0


if __name__ == "__main__":
    # Manual run for diagnostics — does NOT touch the live engine.
    # Useful for verifying the DB plumbing without waiting for a scheduler tick.
    from treasury_signals.scheduler import engine as live_engine

    logger.info("Pre-announce persister — manual diagnostic run...")
    fed = feed_filing_excerpts_to_engine(live_engine)
    result = live_engine.calculate_correlation()
    snapshots = persist_correlation_snapshot(result)
    print(f"Fed excerpts: {fed}, Snapshot rows: {snapshots}")
