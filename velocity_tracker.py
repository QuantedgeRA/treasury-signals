"""
velocity_tracker.py — Accumulation Velocity & New Entrant Detection
--------------------------------------------------------------------
Runs after treasury_sync + name fixers to:
  1. Record daily snapshot of each company's BTC holdings
  2. Detect new entrants (companies appearing for the first time)
  3. Calculate accumulation velocity (BTC added per month)
  4. Send alerts for new entrants via Telegram

New entrant detection uses COMPANY NAME (not ticker) to avoid false
positives when gov_entities/entity_name_fixer renames garbled entries.

Requires table: treasury_history (ticker, company, btc_holdings, snapshot_date)
Requires table: new_entrants (ticker, company, btc_holdings, first_seen, notified)
"""

import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "contact@quantedgeriskadvisory.com")
EMAIL_FROM = os.getenv("EMAIL_FROM_ADDRESS", "briefing@quantedgeriskadvisory.com")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Minimum BTC to count as a real new entrant (filters noise)
MIN_BTC_NEW_ENTRANT = 1


def _normalize_name(name):
    """Normalize company name for comparison. Strips emojis, punctuation, case."""
    if not name:
        return ""
    # Remove non-ASCII (flag emojis, garbled chars)
    clean = re.sub(r'[^\x20-\x7E]', '', name)
    # Lowercase, strip whitespace
    clean = clean.lower().strip()
    # Remove common suffixes that vary
    for suffix in [' inc', ' inc.', ' corp', ' corp.', ' ltd', ' ltd.', ' plc',
                   ' llc', ' ag', ' se', ' sa', ' gmbh', ' co.', ' co']:
        if clean.endswith(suffix):
            clean = clean[:-len(suffix)].strip()
    return clean


class VelocityTracker:

    def __init__(self):
        self._new_entrants = []

    def run(self):
        """Run velocity tracking after treasury sync."""
        logger.info("Velocity Tracker: starting...")

        today = datetime.now().strftime("%Y-%m-%d")

        # Step 1: Get current holdings
        try:
            result = supabase.table("treasury_companies").select(
                "id, ticker, company, btc_holdings"
            ).gt("btc_holdings", 0).execute()
            current = result.data if result.data else []
        except Exception as e:
            logger.warning(f"Velocity Tracker: failed to load current holdings: {e}")
            return

        if not current:
            return

        # Step 2: Get previous snapshot — load company names AND BTC amounts
        prev_names = set()
        prev_btc_amounts = set()

        try:
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            prev_result = supabase.table("treasury_history").select(
                "ticker, company, btc_holdings"
            ).eq("snapshot_date", yesterday).execute()

            if prev_result.data:
                for r in prev_result.data:
                    prev_names.add(_normalize_name(r.get("company", "")))
                    btc = r.get("btc_holdings", 0)
                    if btc and btc > 0:
                        prev_btc_amounts.add(btc)
        except Exception:
            pass

        # If no data from yesterday, try most recent date
        if not prev_names:
            try:
                any_prev = supabase.table("treasury_history").select(
                    "ticker, snapshot_date"
                ).order("snapshot_date", desc=True).limit(1).execute()
                if any_prev.data:
                    last_date = any_prev.data[0]["snapshot_date"]
                    prev_result = supabase.table("treasury_history").select(
                        "ticker, company, btc_holdings"
                    ).eq("snapshot_date", last_date).execute()
                    if prev_result.data:
                        for r in prev_result.data:
                            prev_names.add(_normalize_name(r.get("company", "")))
                            btc = r.get("btc_holdings", 0)
                            if btc and btc > 0:
                                prev_btc_amounts.add(btc)
            except Exception:
                pass

        # Step 3: Record today's snapshot
        recorded = 0
        errors = 0
        for c in current:
            try:
                supabase.table("treasury_history").upsert({
                    "ticker": c["ticker"],
                    "company": (c.get("company") or "")[:200],
                    "btc_holdings": c.get("btc_holdings", 0),
                    "snapshot_date": today,
                }, on_conflict="ticker,snapshot_date").execute()
                recorded += 1
            except Exception as e:
                errors += 1
                if errors <= 3:
                    logger.debug(f"History upsert error {c['ticker']}: {e}")

        logger.info(f"Velocity Tracker: {recorded} snapshots recorded for {today}")

        # Step 4: Detect REAL new entrants
        # Compare by COMPANY NAME (not ticker) to avoid false positives from renames.
        # Three layers of protection:
        #   1. Name match: if normalized name existed yesterday → not new
        #   2. BTC match: if exact BTC amount existed yesterday → likely rename
        #   3. Garbled filter: if name starts with non-ASCII → skip (will be fixed next scan)
        self._new_entrants = []

        if prev_names:
            for c in current:
                name = c.get("company", "")
                ticker = c.get("ticker", "")
                btc = c.get("btc_holdings", 0)
                norm_name = _normalize_name(name)

                # Layer 1: Name existed yesterday (even under different ticker)
                if norm_name in prev_names:
                    continue

                # Layer 2: Garbled name — will be fixed by name fixer, skip for now
                if name and not (name[0].isascii() and name[0].isalpha()):
                    continue

                # Layer 3: BTC amount exactly matches a previous entity → likely a rename
                if btc in prev_btc_amounts:
                    continue

                # Layer 4: Very small holdings (noise)
                if btc < MIN_BTC_NEW_ENTRANT:
                    continue

                # Layer 5: Empty/short name
                if not norm_name or len(norm_name) < 2:
                    continue

                self._new_entrants.append({
                    "ticker": ticker,
                    "company": name,
                    "btc_holdings": btc,
                })

            if self._new_entrants:
                logger.info(f"Velocity Tracker: {len(self._new_entrants)} NEW ENTRANTS detected!")
                for ne in self._new_entrants[:5]:
                    logger.info(f"  🆕 {ne['company']} ({ne['ticker']}): {ne['btc_holdings']:,} BTC")
                if len(self._new_entrants) > 5:
                    logger.info(f"  ... and {len(self._new_entrants) - 5} more")

                # Only send alerts if reasonable count (skip bulk loads)
                if len(self._new_entrants) <= 10:
                    self._send_new_entrant_alerts()
                else:
                    logger.info(f"Velocity Tracker: skipping alerts for {len(self._new_entrants)} entrants (bulk load)")
            else:
                logger.debug("Velocity Tracker: no new entrants detected")
        else:
            logger.info("Velocity Tracker: no previous data yet — new entrant detection starts tomorrow")

        if errors > 0:
            logger.warning(f"Velocity Tracker: {errors} snapshot errors")

        return {"recorded": recorded, "new_entrants": len(self._new_entrants)}

    def _send_new_entrant_alerts(self):
        """Send alerts for new entrants via Telegram and email."""
        if not self._new_entrants:
            return

        # Telegram
        try:
            from telegram_bot import send_to_paid, send_to_free
            for ne in self._new_entrants:
                msg = (
                    f"🆕 NEW BITCOIN TREASURY ENTRANT\n\n"
                    f"🏢 {ne['company']} ({ne['ticker']})\n"
                    f"₿ {ne['btc_holdings']:,} BTC\n"
                    f"📅 First detected: {datetime.now().strftime('%Y-%m-%d')}\n\n"
                    f"This company has been added to our tracking. "
                    f"Corporate Bitcoin adoption continues to grow.\n\n"
                    f"—\nTreasury Signal Intelligence"
                )
                try:
                    send_to_paid(msg)
                    send_to_free(msg)
                except Exception:
                    pass
        except ImportError:
            pass

        # Admin email summary
        if RESEND_API_KEY and len(self._new_entrants) > 0:
            try:
                body = "<h2>🆕 New Bitcoin Treasury Entrants</h2>"
                body += f"<p>{datetime.now().strftime('%Y-%m-%d %H:%M')}</p>"
                body += "<table border='1' cellpadding='6' style='border-collapse:collapse;'>"
                body += "<tr><th>Company</th><th>Ticker</th><th>BTC</th></tr>"
                for ne in self._new_entrants:
                    body += f"<tr><td>{ne['company']}</td><td>{ne['ticker']}</td><td>{ne['btc_holdings']:,}</td></tr>"
                body += "</table>"

                import requests
                requests.post("https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                    json={"from": f"TSI <{EMAIL_FROM}>", "to": [ADMIN_EMAIL],
                          "subject": f"🆕 {len(self._new_entrants)} new BTC treasury entrant(s)",
                          "html": body}, timeout=10)
            except Exception:
                pass

    def get_velocity(self, ticker, days=30):
        """Calculate accumulation velocity for a specific company."""
        try:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            result = supabase.table("treasury_history").select(
                "btc_holdings, snapshot_date"
            ).eq("ticker", ticker).gte("snapshot_date", cutoff).order(
                "snapshot_date", desc=False
            ).execute()

            data = result.data if result.data else []
            if len(data) < 2:
                return None

            first = data[0]
            last = data[-1]
            btc_start = first["btc_holdings"] or 0
            btc_end = last["btc_holdings"] or 0
            btc_added = btc_end - btc_start

            date_start = datetime.strptime(first["snapshot_date"], "%Y-%m-%d")
            date_end = datetime.strptime(last["snapshot_date"], "%Y-%m-%d")
            days_elapsed = (date_end - date_start).days

            if days_elapsed <= 0:
                return None

            btc_per_month = (btc_added / days_elapsed) * 30

            return {
                "btc_added": btc_added,
                "btc_per_month": round(btc_per_month),
                "days_tracked": days_elapsed,
                "data_points": len(data),
                "start_holdings": btc_start,
                "end_holdings": btc_end,
            }
        except Exception as e:
            logger.debug(f"Velocity calc error for {ticker}: {e}")
            return None

    def get_top_accumulators(self, days=30, limit=10):
        """Get the fastest accumulators over the last N days."""
        try:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            first_snaps = supabase.table("treasury_history").select(
                "ticker, btc_holdings, snapshot_date, company"
            ).gte("snapshot_date", cutoff).order("snapshot_date", desc=False).execute()

            last_snaps = supabase.table("treasury_history").select(
                "ticker, btc_holdings, snapshot_date"
            ).order("snapshot_date", desc=True).limit(500).execute()

            if not first_snaps.data or not last_snaps.data:
                return []

            first_map = {}
            for r in first_snaps.data:
                if r["ticker"] not in first_map:
                    first_map[r["ticker"]] = r

            last_map = {}
            for r in last_snaps.data:
                if r["ticker"] not in last_map:
                    last_map[r["ticker"]] = r

            velocities = []
            for ticker, first in first_map.items():
                last = last_map.get(ticker)
                if not last:
                    continue
                btc_start = first["btc_holdings"] or 0
                btc_end = last["btc_holdings"] or 0
                added = btc_end - btc_start

                if added <= 0:
                    continue

                d1 = datetime.strptime(first["snapshot_date"], "%Y-%m-%d")
                d2 = datetime.strptime(last["snapshot_date"], "%Y-%m-%d")
                elapsed = (d2 - d1).days
                if elapsed <= 0:
                    continue

                velocities.append({
                    "ticker": ticker,
                    "company": first.get("company", ticker),
                    "btc_added": added,
                    "btc_per_month": round((added / elapsed) * 30),
                    "days": elapsed,
                    "current": btc_end,
                })

            velocities.sort(key=lambda x: -x["btc_per_month"])
            return velocities[:limit]

        except Exception as e:
            logger.debug(f"Top accumulators error: {e}")
            return []


velocity = VelocityTracker()

if __name__ == "__main__":
    logger.info("Velocity Tracker — manual run...")
    result = velocity.run()
    print(f"\nRecorded: {result['recorded']}, New entrants: {result['new_entrants']}")

    print("\nTop accumulators (30d):")
    top = velocity.get_top_accumulators(days=30)
    for t in top:
        print(f"  {t['company']:30s} +{t['btc_added']:>8,} BTC ({t['btc_per_month']:>6,}/mo)")
