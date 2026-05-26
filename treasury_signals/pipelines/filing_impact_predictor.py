"""
filing_impact_predictor.py — historical-reaction context for new filings.

When edgar_realtime / filing_parser / global_filing_scanner detect a new
BTC treasury filing and pass it through the direction classifier, this
module looks up the historical equity reaction for that direction
class + ticker and returns a formatted context block.

The block embeds in Telegram + email + Slack alerts so customers see
the trade-thesis context alongside the raw event:

    SEC FILING DETECTED
    MSTR purchased 21,021 BTC
    Direction: pure_buy

    -> Historical reaction (179 pure_buy events):
       1-day:   +2.46% avg, 52% win rate
       5-day:   +4.11% avg
       30-day:  +12.7% avg

The /backtest page proved the direction classifier adds alpha (pure_buy
beats aggregate by ~1.1pp on 1-day mean). This module operationalizes
that finding — turns "another filing alert" into "another filing alert
WITH a historical baseline." Every existing alert becomes more actionable.

DATA SOURCE
===========
backtest_reactions table (migration 0019), populated by
scripts/backfill_backtest_reactions.py. Latest backfill at time of writing:
369 events with full reactions, 179 pure_buy / 67 unclear / 1 sale /
122 NULL.

LOOKUP STRATEGY
===============
1. Try per-ticker: "MSTR's last N pure_buy events" — most specific.
   Floor at MIN_PER_TICKER_SAMPLE=5 events; below that, fall through.
2. Aggregate fallback: "all pure_buy events across all entities."
   Floor at MIN_AGGREGATE_SAMPLE=20 events; below that, return None.

Returning None means we don't surface impact (rather than show a
misleadingly-small sample). The alert still fires; it just lacks the
context block.

CACHING
=======
In-process LRU-style cache, 10-minute TTL. The backtest table only
updates after daily backfills + occasional manual reruns, so 10min
freshness is generous. Cache eliminates ~99% of supabase round-trips
during alert-burst conditions (e.g. EDGAR FTS sweep finds 5 filings
at once).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client

from treasury_signals.logger import get_logger

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# Sample-size floors below which we don't surface a prediction —
# small samples are misleading.
MIN_PER_TICKER_SAMPLE = 5
MIN_AGGREGATE_SAMPLE = 20

# Cache TTL
CACHE_TTL_SECONDS = 600

# In-process cache: {cache_key: (timestamp, value)}
_cache: dict[str, tuple[float, "Optional[ReactionStats]"]] = {}


@dataclass
class ReactionStats:
    direction: str
    ticker: Optional[str]            # None when aggregate across all tickers
    n_events: int
    mean_1d_pct: Optional[float]
    mean_5d_pct: Optional[float]
    mean_30d_pct: Optional[float]
    win_rate_1d_pct: Optional[float]
    scope: str                       # 'per_ticker' or 'aggregate'


def _mean(arr: list) -> Optional[float]:
    valid = [float(x) for x in arr if x is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


def _win_rate(arr: list) -> Optional[float]:
    valid = [float(x) for x in arr if x is not None]
    if not valid:
        return None
    return (sum(1 for x in valid if x > 0) / len(valid)) * 100.0


def _fetch_stats(direction: str, ticker: Optional[str]) -> Optional[ReactionStats]:
    """Query backtest_reactions, compute stats. Returns None if sample too small."""
    if not supabase or not direction:
        return None
    try:
        q = (
            supabase.table("backtest_reactions")
            .select("reaction_1d_pct, reaction_5d_pct, reaction_30d_pct")
            .eq("direction", direction)
            .not_.is_("reaction_1d_pct", "null")
        )
        if ticker:
            q = q.eq("ticker", ticker)
        res = q.limit(2000).execute()
        rows = res.data or []
    except Exception as e:
        logger.debug(f"impact_predictor: fetch failed dir={direction} ticker={ticker}: {e}")
        return None

    min_sample = MIN_PER_TICKER_SAMPLE if ticker else MIN_AGGREGATE_SAMPLE
    if len(rows) < min_sample:
        return None

    m1 = _mean([r.get("reaction_1d_pct") for r in rows])
    m5 = _mean([r.get("reaction_5d_pct") for r in rows])
    m30 = _mean([r.get("reaction_30d_pct") for r in rows])
    wr = _win_rate([r.get("reaction_1d_pct") for r in rows])

    return ReactionStats(
        direction=direction,
        ticker=ticker,
        n_events=len(rows),
        mean_1d_pct=round(m1, 2) if m1 is not None else None,
        mean_5d_pct=round(m5, 2) if m5 is not None else None,
        mean_30d_pct=round(m30, 2) if m30 is not None else None,
        win_rate_1d_pct=round(wr, 1) if wr is not None else None,
        scope="per_ticker" if ticker else "aggregate",
    )


def get_historical_reactions(
    direction: Optional[str], ticker: Optional[str] = None
) -> Optional[ReactionStats]:
    """Look up reaction stats, trying per-ticker first then aggregate fallback.

    Cached for CACHE_TTL_SECONDS to absorb alert bursts.
    """
    if not direction:
        return None
    direction = str(direction).lower().strip()
    ticker_norm = (ticker or "").upper().strip() or None

    # Try per-ticker first
    if ticker_norm:
        key = f"{direction}::{ticker_norm}"
        cached = _cache.get(key)
        if cached and (time.time() - cached[0]) < CACHE_TTL_SECONDS:
            stats = cached[1]
        else:
            stats = _fetch_stats(direction, ticker_norm)
            _cache[key] = (time.time(), stats)
        if stats:
            return stats

    # Fall back to aggregate
    key = f"{direction}::*"
    cached = _cache.get(key)
    if cached and (time.time() - cached[0]) < CACHE_TTL_SECONDS:
        return cached[1]
    stats = _fetch_stats(direction, None)
    _cache[key] = (time.time(), stats)
    return stats


# ─── Formatters ──────────────────────────────────────────────────────


def _pretty_direction(direction: str) -> str:
    return {
        "pure_buy": "pure buy",
        "raise_then_buy": "raise-then-buy",
        "convertible": "convertible-funded buy",
        "sale": "sale",
        "unclear": "unclear direction",
    }.get(direction, direction.replace("_", " "))


def _sign(n) -> str:
    if n is None:
        return "n/a"
    return f"{'+' if n >= 0 else ''}{n:.1f}%"


def format_impact_context_telegram(stats: ReactionStats, ticker: str) -> str:
    """Markdown block for Telegram alerts.

    Designed to fit under the existing alert body without making the
    message overwhelming. ~5 lines.
    """
    scope_line = (
        f"based on {ticker}'s last {stats.n_events} {_pretty_direction(stats.direction)} events"
        if stats.scope == "per_ticker"
        else f"based on {stats.n_events} {_pretty_direction(stats.direction)} events across all tracked entities"
    )
    lines = [
        "",
        f"📊 **Historical reaction** ({scope_line}):",
        f"   1-day:  {_sign(stats.mean_1d_pct)}  ·  win rate {stats.win_rate_1d_pct:.0f}%" if stats.win_rate_1d_pct is not None else f"   1-day:  {_sign(stats.mean_1d_pct)}",
        f"   5-day:  {_sign(stats.mean_5d_pct)}",
        f"   30-day: {_sign(stats.mean_30d_pct)}",
    ]
    return "\n".join(lines)


def format_impact_context_html(stats: ReactionStats, ticker: str) -> str:
    """HTML snippet for email briefings.

    Uses the same dark-mode color palette as the dashboard so it
    visually matches.
    """
    scope_line = (
        f"based on {ticker}'s last {stats.n_events} {_pretty_direction(stats.direction)} events"
        if stats.scope == "per_ticker"
        else f"based on {stats.n_events} {_pretty_direction(stats.direction)} events across all tracked entities"
    )

    def _color(v):
        if v is None:
            return "#94a3b8"
        return "#22c55e" if v >= 0 else "#ef4444"

    return f"""<div style="margin-top:10px;padding:12px 14px;background:rgba(56,189,248,0.05);border:1px solid rgba(56,189,248,0.15);border-radius:10px;font-size:13px;color:#cdd6e1;">
  <div style="font-weight:600;color:#38bdf8;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;">Historical reaction</div>
  <div style="color:#94a3b8;font-size:11px;margin-bottom:8px;">{scope_line}</div>
  <table style="width:100%;font-family:monospace;font-size:12px;">
    <tr>
      <td style="color:#94a3b8;padding:2px 0;">1-day</td>
      <td style="text-align:right;color:{_color(stats.mean_1d_pct)};font-weight:600;">{_sign(stats.mean_1d_pct)}</td>
      <td style="text-align:right;color:#cdd6e1;padding-left:14px;">win rate {stats.win_rate_1d_pct:.0f}%</td>
    </tr>
    <tr>
      <td style="color:#94a3b8;padding:2px 0;">5-day</td>
      <td style="text-align:right;color:{_color(stats.mean_5d_pct)};font-weight:600;">{_sign(stats.mean_5d_pct)}</td>
      <td></td>
    </tr>
    <tr>
      <td style="color:#94a3b8;padding:2px 0;">30-day</td>
      <td style="text-align:right;color:{_color(stats.mean_30d_pct)};font-weight:600;">{_sign(stats.mean_30d_pct)}</td>
      <td></td>
    </tr>
  </table>
</div>"""


# ─── Manual smoke test ───────────────────────────────────────────────


if __name__ == "__main__":
    import sys
    direction = sys.argv[1] if len(sys.argv) > 1 else "pure_buy"
    ticker = sys.argv[2] if len(sys.argv) > 2 else None
    stats = get_historical_reactions(direction, ticker)
    if not stats:
        print(f"No stats for direction={direction} ticker={ticker} (sample too small)")
    else:
        print(f"Stats: {stats}")
        print()
        print("Telegram render:")
        print(format_impact_context_telegram(stats, ticker or "ANY"))
