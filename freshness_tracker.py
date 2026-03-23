"""
freshness_tracker.py — Data Freshness Tracking
------------------------------------------------
Tracks when each data source was last successfully fetched.
Every module calls `record_success()` or `record_failure()` after
each API call, and the dashboard/emails query `get_status()` to
show live/stale/fallback indicators.

Data Sources Tracked:
- twitter_api       (TwitterAPI.io tweet fetches)
- coingecko         (CoinGecko leaderboard)
- bitcointreasuries (BitcoinTreasuries.net scrape + sovereign API)
- sec_edgar         (SEC EDGAR 8-K filings)
- strc_yfinance     (STRC volume from Yahoo Finance)
- btc_yfinance      (BTC price from Yahoo Finance)
- mstr_yfinance     (MSTR price from Yahoo Finance)
- fear_greed        (Fear & Greed Index API)
- google_news_reg   (Google News RSS — regulatory)
- google_news_stmt  (Google News RSS — statements)
- google_news_purchases (Google News RSS — purchases)
- supabase          (Supabase database reads/writes)

Usage:
    from freshness_tracker import freshness
    
    # After a successful API call:
    freshness.record_success("coingecko", detail="148 companies fetched")
    
    # After a failed API call:
    freshness.record_failure("coingecko", error="HTTP 429 rate limited")
    
    # Check status for dashboard:
    status = freshness.get_status("coingecko")
    # → {"source": "coingecko", "status": "live", "last_success": "2026-03-22 14:30:01", 
    #    "age_minutes": 12, "detail": "148 companies fetched", "color": "green"}
    
    # Get all statuses for dashboard/email:
    all_statuses = freshness.get_all_statuses()
"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from logger import get_logger

logger = get_logger(__name__)
load_dotenv()

# ============================================
# STALENESS THRESHOLDS (minutes)
# ============================================
# Each source has a "fresh" window and a "stale" window.
# Beyond "stale" = considered unavailable.

THRESHOLDS = {
    "twitter_api":          {"fresh": 120, "stale": 360},     # Fresh < 2h, stale > 6h
    "coingecko":            {"fresh": 90,  "stale": 360},     # Fresh < 1.5h, stale > 6h
    "bitcointreasuries":    {"fresh": 90,  "stale": 360},
    "sec_edgar":            {"fresh": 120, "stale": 720},     # Fresh < 2h, stale > 12h
    "strc_yfinance":        {"fresh": 120, "stale": 360},
    "btc_yfinance":         {"fresh": 30,  "stale": 120},     # Price data: fresh < 30min
    "mstr_yfinance":        {"fresh": 30,  "stale": 120},
    "fear_greed":           {"fresh": 360, "stale": 1440},    # Updates daily, so 6h is fine
    "google_news_reg":      {"fresh": 120, "stale": 360},
    "google_news_stmt":     {"fresh": 120, "stale": 360},
    "google_news_purchases":{"fresh": 120, "stale": 360},
    "supabase":             {"fresh": 15,  "stale": 60},      # DB should always be reachable
}

# Human-readable names for display
SOURCE_LABELS = {
    "twitter_api":          "Twitter/X API",
    "coingecko":            "CoinGecko (Leaderboard)",
    "bitcointreasuries":    "BitcoinTreasuries.net",
    "sec_edgar":            "SEC EDGAR",
    "strc_yfinance":        "STRC Volume (Yahoo Finance)",
    "btc_yfinance":         "BTC Price (Yahoo Finance)",
    "mstr_yfinance":        "MSTR Price (Yahoo Finance)",
    "fear_greed":           "Fear & Greed Index",
    "google_news_reg":      "News Scanner (Regulatory)",
    "google_news_stmt":     "News Scanner (Statements)",
    "google_news_purchases":"News Scanner (Purchases)",
    "supabase":             "Supabase Database",
}


class FreshnessTracker:
    """
    In-memory tracker for data source freshness.
    Persists to Supabase periodically for dashboard access.
    """

    def __init__(self):
        self._sources = {}
        self._provenance = {}  # Tracks which source provided data for each category
        self._init_sources()

    def _init_sources(self):
        """Initialize all known sources with unknown status."""
        for source_id in THRESHOLDS:
            self._sources[source_id] = {
                "source": source_id,
                "label": SOURCE_LABELS.get(source_id, source_id),
                "last_success": None,
                "last_failure": None,
                "last_error": None,
                "detail": None,
                "consecutive_failures": 0,
            }

    def record_success(self, source_id, detail=""):
        """Record a successful data fetch for a source."""
        if source_id not in self._sources:
            self._sources[source_id] = {
                "source": source_id,
                "label": SOURCE_LABELS.get(source_id, source_id),
                "last_success": None, "last_failure": None,
                "last_error": None, "detail": None, "consecutive_failures": 0,
            }

        self._sources[source_id]["last_success"] = datetime.now()
        self._sources[source_id]["detail"] = detail[:200] if detail else None
        self._sources[source_id]["consecutive_failures"] = 0
        logger.debug(f"Freshness: {source_id} ✅ {detail[:80] if detail else 'OK'}")

    def record_failure(self, source_id, error=""):
        """Record a failed data fetch for a source."""
        if source_id not in self._sources:
            self._sources[source_id] = {
                "source": source_id,
                "label": SOURCE_LABELS.get(source_id, source_id),
                "last_success": None, "last_failure": None,
                "last_error": None, "detail": None, "consecutive_failures": 0,
            }

        self._sources[source_id]["last_failure"] = datetime.now()
        self._sources[source_id]["last_error"] = str(error)[:200] if error else None
        self._sources[source_id]["consecutive_failures"] += 1

        failures = self._sources[source_id]["consecutive_failures"]
        if failures >= 3:
            logger.warning(f"Freshness: {source_id} ❌ {failures} consecutive failures — {error[:80] if error else 'unknown'}")

    def set_provenance(self, category, source_name, source_type="live"):
        """
        Record which specific source provided data for a category.
        
        Args:
            category: Data category (e.g., "leaderboard_corporate", "leaderboard_sovereign",
                      "regulatory", "purchases", "btc_price", "strc_data")
            source_name: Human-readable source (e.g., "CoinGecko API", "Supabase snapshot",
                        "Hardcoded fallback")
            source_type: "live" | "cached" | "fallback"
        
        Example:
            freshness.set_provenance("leaderboard_corporate", "CoinGecko API", "live")
            freshness.set_provenance("leaderboard_sovereign", "Hardcoded fallback", "fallback")
        """
        self._provenance[category] = {
            "source_name": source_name,
            "source_type": source_type,  # live, cached, fallback
            "updated_at": datetime.now(),
        }
        logger.debug(f"Provenance: {category} → {source_name} ({source_type})")

    def get_provenance(self, category):
        """
        Get the current data provenance for a category.
        
        Returns dict with source_name, source_type, badge_html, badge_text.
        """
        if category not in self._provenance:
            return {
                "source_name": "Unknown",
                "source_type": "unknown",
                "badge_text": "⚪ UNKNOWN",
                "badge_color": "#6B7280",
                "badge_bg": "rgba(107, 114, 128, 0.1)",
            }

        prov = self._provenance[category]
        source_type = prov["source_type"]

        if source_type == "live":
            return {
                "source_name": prov["source_name"],
                "source_type": "live",
                "badge_text": "🟢 LIVE",
                "badge_color": "#10B981",
                "badge_bg": "rgba(16, 185, 129, 0.1)",
            }
        elif source_type == "cached":
            return {
                "source_name": prov["source_name"],
                "source_type": "cached",
                "badge_text": "🟡 CACHED",
                "badge_color": "#F59E0B",
                "badge_bg": "rgba(245, 158, 11, 0.1)",
            }
        else:  # fallback
            return {
                "source_name": prov["source_name"],
                "source_type": "fallback",
                "badge_text": "🔴 FALLBACK",
                "badge_color": "#EF4444",
                "badge_bg": "rgba(239, 68, 68, 0.1)",
            }

    def get_all_provenance(self):
        """Get provenance for all tracked categories."""
        return {cat: self.get_provenance(cat) for cat in self._provenance}

    def format_provenance_html(self, category):
        """
        Generate an inline HTML badge for a data section.
        Used in both dashboard and email.
        """
        prov = self.get_provenance(category)
        return (
            f'<span style="background: {prov["badge_bg"]}; color: {prov["badge_color"]}; '
            f'padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; '
            f'letter-spacing: 0.05em; margin-left: 8px; border: 1px solid {prov["badge_color"]}30;">'
            f'{prov["badge_text"]} — {prov["source_name"]}'
            f'</span>'
        )

    def get_status(self, source_id):
        """
        Get the current freshness status for a source.
        
        Returns dict with:
        - status: "live" | "stale" | "unavailable" | "unknown"
        - color: "green" | "yellow" | "red" | "gray"
        - age_minutes: how many minutes since last success
        - age_text: human-readable age ("12 min ago", "3 hours ago")
        """
        if source_id not in self._sources:
            return {
                "source": source_id,
                "label": SOURCE_LABELS.get(source_id, source_id),
                "status": "unknown", "color": "gray",
                "age_minutes": None, "age_text": "No data yet",
                "detail": None, "last_error": None,
                "emoji": "⚪",
            }

        source = self._sources[source_id]
        thresholds = THRESHOLDS.get(source_id, {"fresh": 120, "stale": 360})
        last_success = source["last_success"]

        if last_success is None:
            return {
                "source": source_id,
                "label": source["label"],
                "status": "unknown", "color": "gray",
                "age_minutes": None, "age_text": "No data yet",
                "detail": source["detail"], "last_error": source["last_error"],
                "emoji": "⚪",
            }

        age = datetime.now() - last_success
        age_minutes = age.total_seconds() / 60

        # Determine status
        if age_minutes <= thresholds["fresh"]:
            status = "live"
            color = "green"
            emoji = "🟢"
        elif age_minutes <= thresholds["stale"]:
            status = "stale"
            color = "yellow"
            emoji = "🟡"
        else:
            status = "unavailable"
            color = "red"
            emoji = "🔴"

        # Human-readable age
        if age_minutes < 1:
            age_text = "Just now"
        elif age_minutes < 60:
            age_text = f"{int(age_minutes)} min ago"
        elif age_minutes < 1440:
            hours = age_minutes / 60
            age_text = f"{hours:.1f} hours ago"
        else:
            days = age_minutes / 1440
            age_text = f"{days:.1f} days ago"

        return {
            "source": source_id,
            "label": source["label"],
            "status": status,
            "color": color,
            "emoji": emoji,
            "age_minutes": round(age_minutes, 1),
            "age_text": age_text,
            "detail": source["detail"],
            "last_error": source["last_error"],
            "consecutive_failures": source["consecutive_failures"],
        }

    def get_all_statuses(self):
        """Get freshness status for all tracked sources."""
        return [self.get_status(source_id) for source_id in THRESHOLDS]

    def get_overall_health(self):
        """
        Get an overall system health summary.
        Returns: "healthy", "degraded", or "critical"
        """
        statuses = self.get_all_statuses()
        live_count = sum(1 for s in statuses if s["status"] == "live")
        stale_count = sum(1 for s in statuses if s["status"] == "stale")
        unavailable_count = sum(1 for s in statuses if s["status"] == "unavailable")
        unknown_count = sum(1 for s in statuses if s["status"] == "unknown")
        total = len(statuses)

        # Critical sources that must be live
        critical_sources = ["supabase", "btc_yfinance"]
        critical_down = any(
            self.get_status(s)["status"] in ("unavailable", "unknown")
            for s in critical_sources
        )

        if critical_down or unavailable_count >= 3:
            health = "critical"
            color = "#EF4444"
            emoji = "🔴"
            message = f"{unavailable_count} source(s) unavailable — data quality degraded"
        elif stale_count >= 3 or unavailable_count >= 1:
            health = "degraded"
            color = "#F59E0B"
            emoji = "🟡"
            message = f"{live_count} live, {stale_count} stale, {unavailable_count} down"
        else:
            health = "healthy"
            color = "#10B981"
            emoji = "🟢"
            message = f"All {live_count} sources live"

        return {
            "health": health,
            "color": color,
            "emoji": emoji,
            "message": message,
            "live": live_count,
            "stale": stale_count,
            "unavailable": unavailable_count,
            "unknown": unknown_count,
            "total": total,
        }

    def format_status_text(self):
        """Format a text summary for logs or Telegram."""
        health = self.get_overall_health()
        lines = [f"{health['emoji']} System Health: {health['health'].upper()} — {health['message']}\n"]

        for status in self.get_all_statuses():
            lines.append(f"  {status['emoji']} {status['label']}: {status['age_text']}")
            if status["last_error"] and status["status"] != "live":
                lines.append(f"     ↳ Last error: {status['last_error'][:60]}")

        return "\n".join(lines)

    def format_for_email(self):
        """Format HTML snippet for the email briefing footer."""
        health = self.get_overall_health()
        statuses = self.get_all_statuses()

        rows_html = ""
        for s in statuses:
            if s["status"] == "unknown":
                continue
            dot_color = {"green": "#10B981", "yellow": "#F59E0B", "red": "#EF4444", "gray": "#6B7280"}[s["color"]]
            rows_html += f"""
            <tr>
                <td style="padding: 3px 8px; color: #9ca3af; font-size: 11px;">
                    <span style="color: {dot_color};">●</span> {s['label']}
                </td>
                <td style="padding: 3px 8px; color: #d1d5db; font-size: 11px; text-align: right;">
                    {s['age_text']}
                </td>
            </tr>"""

        health_color = health["color"]

        return f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 12px;">
            <tr><td style="padding: 12px 18px; border-top: 1px solid #1e2a3a;">
                <span style="color: {health_color}; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase;">
                    {health['emoji']} DATA SOURCES — {health['health'].upper()}
                </span>
                <span style="color: #4b5563; font-size: 10px; margin-left: 8px;">
                    {health['message']}
                </span>
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 8px;">
                    {rows_html}
                </table>
            </td></tr>
        </table>
        """

    def save_to_supabase(self, supabase_client):
        """
        Persist current freshness data to Supabase for the dashboard.
        Call this once per scan cycle.
        """
        try:
            now = datetime.now()
            statuses = self.get_all_statuses()
            health = self.get_overall_health()

            import json
            row = {
                "snapshot_time": now.isoformat(),
                "overall_health": health["health"],
                "live_count": health["live"],
                "stale_count": health["stale"],
                "unavailable_count": health["unavailable"],
                "sources_json": json.dumps(statuses, default=str),
                "provenance_json": json.dumps(self.get_all_provenance(), default=str),
            }

            supabase_client.table("data_freshness").upsert(
                row, on_conflict="snapshot_time"
            ).execute()
            logger.debug("Freshness snapshot saved to Supabase")
            return True
        except Exception as e:
            logger.error(f"Failed to save freshness to Supabase: {e}", exc_info=True)
            return False

    def load_from_supabase(self, supabase_client):
        """
        Load the most recent freshness snapshot from Supabase.
        Used by the dashboard (which runs in a separate process).
        """
        try:
            import json
            result = supabase_client.table("data_freshness").select("*").order(
                "snapshot_time", desc=True
            ).limit(1).execute()

            if result.data:
                snapshot = result.data[0]
                sources = json.loads(snapshot.get("sources_json", "[]"))
                provenance = json.loads(snapshot.get("provenance_json", "{}"))
                return {
                    "snapshot_time": snapshot["snapshot_time"],
                    "overall_health": snapshot.get("overall_health", "unknown"),
                    "live_count": snapshot.get("live_count", 0),
                    "stale_count": snapshot.get("stale_count", 0),
                    "unavailable_count": snapshot.get("unavailable_count", 0),
                    "sources": sources,
                    "provenance": provenance,
                }
            return None
        except Exception as e:
            logger.error(f"Failed to load freshness from Supabase: {e}", exc_info=True)
            return None


# ============================================
# GLOBAL INSTANCE
# ============================================
# All modules import this single instance
freshness = FreshnessTracker()


# ============================================
# SQL FOR SUPABASE TABLE
# ============================================
SETUP_SQL = """
-- Run this in your Supabase SQL Editor:

CREATE TABLE IF NOT EXISTS data_freshness (
    id BIGSERIAL PRIMARY KEY,
    snapshot_time TIMESTAMP WITH TIME ZONE UNIQUE NOT NULL,
    overall_health TEXT DEFAULT 'unknown',
    live_count INTEGER DEFAULT 0,
    stale_count INTEGER DEFAULT 0,
    unavailable_count INTEGER DEFAULT 0,
    sources_json JSONB DEFAULT '[]'::jsonb,
    provenance_json JSONB DEFAULT '{}'::jsonb
);

-- Optional: auto-cleanup old snapshots (keep last 7 days)
-- DELETE FROM data_freshness WHERE snapshot_time < NOW() - INTERVAL '7 days';
"""


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Freshness Tracker — testing...")

    # Simulate some activity
    freshness.record_success("coingecko", detail="148 companies fetched")
    freshness.record_success("btc_yfinance", detail="BTC $72,456")
    freshness.record_success("supabase", detail="DB read OK")
    freshness.record_failure("bitcointreasuries", error="DNS resolution failed")
    freshness.record_failure("bitcointreasuries", error="DNS resolution failed")
    freshness.record_failure("bitcointreasuries", error="DNS resolution failed")

    # Show all statuses
    print(freshness.format_status_text())

    # Show health
    health = freshness.get_overall_health()
    logger.info(f"Overall: {health['emoji']} {health['health']} — {health['message']}")

    # Show SQL
    print(f"\n{'='*60}")
    print("Run this SQL in Supabase to create the freshness table:")
    print(SETUP_SQL)

    logger.info("Freshness Tracker test complete")
