"""
subscriber_manager.py — Company Profiles & Subscriber System
--------------------------------------------------------------
Manages subscriber accounts and company profiles.
This is the foundation for all personalization features.

Each subscriber has:
- Personal info (name, email, plan)
- Company info (name, ticker, sector, country)
- BTC holdings (self-reported, for leaderboard positioning)
- Preferences (alert frequency, watchlist)

Usage:
    from subscriber_manager import subscribers

    # Get a subscriber by email
    profile = subscribers.get_by_email("ceo@company.com")

    # Get subscriber's leaderboard position
    position = subscribers.get_leaderboard_position("ceo@company.com", btc_price=72000)

    # Get all active subscribers for email briefings
    active = subscribers.get_active_subscribers()
"""

import os
import json
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================
# SQL — Run this in Supabase SQL Editor
# ============================================

SETUP_SQL = """
CREATE TABLE IF NOT EXISTS subscribers (
    id BIGSERIAL PRIMARY KEY,
    subscriber_id TEXT UNIQUE NOT NULL,
    
    -- Personal
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    role TEXT DEFAULT '',
    
    -- Company
    company_name TEXT NOT NULL,
    ticker TEXT DEFAULT '',
    sector TEXT DEFAULT '',
    country TEXT DEFAULT '',
    
    -- BTC Holdings (self-reported)
    btc_holdings DECIMAL DEFAULT 0,
    avg_purchase_price DECIMAL DEFAULT 0,
    total_invested_usd DECIMAL DEFAULT 0,
    
    -- Subscription
    plan TEXT DEFAULT 'pro',
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Preferences
    alert_frequency TEXT DEFAULT 'instant',
    email_briefing BOOLEAN DEFAULT TRUE,
    telegram_chat_id TEXT DEFAULT '',
    watchlist_json JSONB DEFAULT '[]'::jsonb,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_active TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for fast email lookups
CREATE INDEX IF NOT EXISTS idx_subscribers_email ON subscribers(email);
CREATE INDEX IF NOT EXISTS idx_subscribers_active ON subscribers(is_active);
"""


class SubscriberManager:
    """Manages subscriber profiles and company data."""

    def __init__(self):
        self._cache = {}  # email -> profile (in-memory cache)
        self._cache_time = None

    def create_subscriber(self, name, email, company_name, ticker="", sector="",
                          country="", role="", btc_holdings=0, avg_purchase_price=0,
                          total_invested_usd=0, plan="pro", telegram_chat_id="",
                          watchlist=None):
        """
        Create a new subscriber profile.
        Returns the subscriber dict or None on failure.
        """
        subscriber_id = f"sub_{email.split('@')[0]}_{datetime.now().strftime('%Y%m%d')}"

        try:
            # Check if email already exists
            existing = supabase.table("subscribers").select("email").eq("email", email).execute()
            if existing.data:
                logger.warning(f"Subscriber already exists: {email}")
                return self.get_by_email(email)

            row = {
                "subscriber_id": subscriber_id,
                "name": name,
                "email": email.lower().strip(),
                "role": role,
                "company_name": company_name,
                "ticker": ticker.upper().strip() if ticker else "",
                "sector": sector,
                "country": country,
                "btc_holdings": btc_holdings,
                "avg_purchase_price": avg_purchase_price,
                "total_invested_usd": total_invested_usd,
                "plan": plan,
                "telegram_chat_id": telegram_chat_id,
                "watchlist_json": json.dumps(watchlist or []),
            }

            supabase.table("subscribers").insert(row).execute()
            logger.info(f"Subscriber created: {name} ({company_name}) — {email}")
            self._invalidate_cache()
            return self.get_by_email(email)

        except Exception as e:
            logger.error(f"Failed to create subscriber {email}: {e}", exc_info=True)
            return None

    def get_by_email(self, email):
        """Get a subscriber profile by email address."""
        try:
            result = supabase.table("subscribers").select("*").eq("email", email.lower().strip()).limit(1).execute()
            if result.data:
                profile = result.data[0]
                profile["watchlist"] = json.loads(profile.get("watchlist_json", "[]")) if profile.get("watchlist_json") else []
                return profile
            return None
        except Exception as e:
            logger.error(f"Failed to fetch subscriber {email}: {e}", exc_info=True)
            return None

    def get_by_ticker(self, ticker):
        """Get subscriber(s) by company ticker."""
        try:
            result = supabase.table("subscribers").select("*").eq("ticker", ticker.upper().strip()).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Failed to fetch subscribers for {ticker}: {e}", exc_info=True)
            return []

    def get_active_subscribers(self, plan=None):
        """Get all active subscribers, optionally filtered by plan."""
        try:
            query = supabase.table("subscribers").select("*").eq("is_active", True)
            if plan:
                query = query.eq("plan", plan)
            result = query.order("created_at", desc=True).execute()
            subscribers_list = result.data if result.data else []
            for s in subscribers_list:
                s["watchlist"] = json.loads(s.get("watchlist_json", "[]")) if s.get("watchlist_json") else []
            return subscribers_list
        except Exception as e:
            logger.error(f"Failed to fetch active subscribers: {e}", exc_info=True)
            return []

    def get_email_recipients(self):
        """Get all subscribers who should receive email briefings."""
        try:
            result = (
                supabase.table("subscribers")
                .select("*")
                .eq("is_active", True)
                .eq("email_briefing", True)
                .execute()
            )
            subscribers_list = result.data if result.data else []
            for s in subscribers_list:
                s["watchlist"] = json.loads(s.get("watchlist_json", "[]")) if s.get("watchlist_json") else []
            return subscribers_list
        except Exception as e:
            logger.error(f"Failed to fetch email recipients: {e}", exc_info=True)
            return []

    def update_holdings(self, email, btc_holdings, avg_purchase_price=None, total_invested_usd=None):
        """Update a subscriber's BTC holdings."""
        try:
            update = {"btc_holdings": btc_holdings, "last_active": datetime.now().isoformat()}
            if avg_purchase_price is not None:
                update["avg_purchase_price"] = avg_purchase_price
            if total_invested_usd is not None:
                update["total_invested_usd"] = total_invested_usd

            supabase.table("subscribers").update(update).eq("email", email.lower().strip()).execute()
            logger.info(f"Holdings updated for {email}: {btc_holdings} BTC")
            self._invalidate_cache()
            return True
        except Exception as e:
            logger.error(f"Failed to update holdings for {email}: {e}", exc_info=True)
            return False

    def update_profile(self, email, **kwargs):
        """Update any subscriber profile fields."""
        try:
            allowed_fields = {
                "name", "role", "company_name", "ticker", "sector", "country",
                "plan", "alert_frequency", "email_briefing", "telegram_chat_id",
            }
            update = {k: v for k, v in kwargs.items() if k in allowed_fields}
            if not update:
                return False

            update["last_active"] = datetime.now().isoformat()
            supabase.table("subscribers").update(update).eq("email", email.lower().strip()).execute()
            logger.info(f"Profile updated for {email}: {list(update.keys())}")
            self._invalidate_cache()
            return True
        except Exception as e:
            logger.error(f"Failed to update profile for {email}: {e}", exc_info=True)
            return False

    def update_watchlist(self, email, watchlist):
        """Update a subscriber's watchlist (list of tickers to track)."""
        try:
            supabase.table("subscribers").update({
                "watchlist_json": json.dumps(watchlist),
                "last_active": datetime.now().isoformat(),
            }).eq("email", email.lower().strip()).execute()
            logger.info(f"Watchlist updated for {email}: {watchlist}")
            self._invalidate_cache()
            return True
        except Exception as e:
            logger.error(f"Failed to update watchlist for {email}: {e}", exc_info=True)
            return False

    def get_leaderboard_position(self, email, btc_price, leaderboard_companies=None):
        """
        Calculate where the subscriber's company ranks on the leaderboard.

        Returns dict with:
        - rank: their position (or None if not on leaderboard)
        - total_companies: total on leaderboard
        - btc_value_usd: current value of their holdings
        - unrealized_pnl: profit/loss if they have cost basis
        - companies_ahead: list of companies with more BTC
        - companies_behind: list of companies with less BTC
        - next_rank_gap: how many BTC needed to move up one rank
        """
        profile = self.get_by_email(email)
        if not profile:
            return None

        holdings = float(profile.get("btc_holdings", 0))
        avg_price = float(profile.get("avg_purchase_price", 0))
        total_cost = float(profile.get("total_invested_usd", 0))

        # Get leaderboard if not provided
        if not leaderboard_companies:
            try:
                from treasury_leaderboard import get_leaderboard_with_live_price
                leaderboard_companies, _ = get_leaderboard_with_live_price(btc_price)
            except Exception as e:
                logger.error(f"Could not load leaderboard for position calc: {e}")
                return None

        # Filter to corporate only (exclude governments for ranking)
        corporate = [c for c in leaderboard_companies if not c.get("is_government")]
        corporate.sort(key=lambda x: x.get("btc_holdings", 0), reverse=True)

        # Calculate position
        btc_value = holdings * btc_price
        unrealized_pnl = btc_value - total_cost if total_cost > 0 else 0
        unrealized_pnl_pct = (unrealized_pnl / total_cost * 100) if total_cost > 0 else 0

        # Find rank
        rank = None
        companies_ahead = []
        companies_behind = []
        next_rank_gap = 0

        for i, company in enumerate(corporate):
            company_btc = company.get("btc_holdings", 0)
            if holdings >= company_btc and rank is None:
                rank = i + 1
                if i > 0:
                    next_rank_gap = corporate[i - 1]["btc_holdings"] - holdings
            if rank is None:
                companies_ahead.append({
                    "company": company["company"],
                    "ticker": company.get("ticker", ""),
                    "btc_holdings": company_btc,
                })

        if rank is None:
            rank = len(corporate) + 1
            if corporate:
                next_rank_gap = corporate[-1]["btc_holdings"] - holdings

        # Companies just behind
        behind_start = rank  # 0-indexed would be rank-1, but we want the ones after
        companies_behind = [
            {"company": c["company"], "ticker": c.get("ticker", ""), "btc_holdings": c.get("btc_holdings", 0)}
            for c in corporate[behind_start:behind_start + 3]
        ]

        # Closest competitors (2 above, 2 below)
        above_start = max(0, rank - 3)
        closest = corporate[above_start:rank + 2] if rank <= len(corporate) else corporate[-5:]

        return {
            "rank": rank,
            "total_companies": len(corporate),
            "btc_holdings": holdings,
            "btc_value_usd": btc_value,
            "btc_value_b": round(btc_value / 1_000_000_000, 3),
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": round(unrealized_pnl_pct, 1),
            "total_cost": total_cost,
            "avg_price": avg_price,
            "next_rank_gap": next_rank_gap,
            "companies_ahead": companies_ahead[-3:],  # Top 3 ahead
            "companies_behind": companies_behind[:3],  # Top 3 behind
            "closest_competitors": closest,
            "company_name": profile["company_name"],
            "ticker": profile.get("ticker", ""),
        }

    def format_position_summary(self, position):
        """Format a human-readable position summary for email/Telegram."""
        if not position:
            return "Position data unavailable."

        lines = []
        rank = position["rank"]
        total = position["total_companies"]
        holdings = position["btc_holdings"]
        value_b = position["btc_value_b"]
        pnl_pct = position["unrealized_pnl_pct"]
        gap = position["next_rank_gap"]

        lines.append(f"📍 {position['company_name']} ranks #{rank} of {total} corporate BTC holders")
        lines.append(f"   Holdings: {holdings:,.0f} BTC (${value_b:.3f}B)")

        if position["total_cost"] > 0:
            pnl_emoji = "📈" if pnl_pct >= 0 else "📉"
            lines.append(f"   {pnl_emoji} Unrealized P&L: {pnl_pct:+.1f}%")

        if gap > 0:
            lines.append(f"   🎯 Need {gap:,.0f} more BTC to move up to #{rank - 1}")

        if position["companies_ahead"]:
            ahead = position["companies_ahead"][-1]
            lines.append(f"   ⬆️ Ahead of you: {ahead['company']} ({ahead['btc_holdings']:,} BTC)")

        if position["companies_behind"]:
            behind = position["companies_behind"][0]
            lines.append(f"   ⬇️ Behind you: {behind['company']} ({behind['btc_holdings']:,} BTC)")

        return "\n".join(lines)

    def _invalidate_cache(self):
        """Clear the in-memory cache."""
        self._cache = {}
        self._cache_time = None

    def get_sector_peers(self, email, leaderboard_companies=None):
        """
        Get companies in the same sector as the subscriber.
        Returns a list of companies with their holdings and recent activity.
        """
        profile = self.get_by_email(email)
        if not profile or not profile.get("sector"):
            return []

        subscriber_sector = profile["sector"].lower().strip()

        if not leaderboard_companies:
            try:
                from treasury_leaderboard import get_leaderboard_with_live_price
                leaderboard_companies, _ = get_leaderboard_with_live_price(72000)
            except Exception as e:
                logger.error(f"Could not load leaderboard for peer calc: {e}")
                return []

        # Map sectors to related keywords for fuzzy matching
        sector_keywords = {
            "software": ["software", "tech", "btc treasury"],
            "bitcoin mining": ["mining", "miner"],
            "fintech": ["fintech", "payments", "exchange"],
            "financial services": ["financial", "bank", "investment", "asset management"],
            "asset management": ["asset management", "investment", "etf"],
            "healthcare": ["healthcare", "medical", "scientific"],
            "energy": ["energy", "battery", "power"],
            "e-commerce": ["e-commerce", "retail", "gaming"],
            "automotive": ["automotive", "ev", "vehicle"],
        }

        # Find matching keywords for subscriber's sector
        match_keywords = []
        for key, keywords in sector_keywords.items():
            if key in subscriber_sector or subscriber_sector in key:
                match_keywords = keywords
                break
        if not match_keywords:
            match_keywords = [subscriber_sector]

        # Filter leaderboard to same sector
        peers = []
        for c in leaderboard_companies:
            if c.get("is_government"):
                continue
            company_sector = (c.get("sector", "") or "").lower()
            if any(kw in company_sector for kw in match_keywords):
                # Don't include the subscriber's own company
                if profile.get("ticker") and c.get("ticker") == profile["ticker"]:
                    continue
                peers.append({
                    "company": c["company"],
                    "ticker": c.get("ticker", ""),
                    "btc_holdings": c.get("btc_holdings", 0),
                    "btc_value_b": c.get("btc_value_b", 0),
                    "sector": c.get("sector", ""),
                    "rank": c.get("rank", 0),
                })

        peers.sort(key=lambda x: x["btc_holdings"], reverse=True)
        return peers[:10]

    def get_competitor_spotlight(self, email, btc_price, leaderboard_companies=None, purchases=None):
        """
        Get detailed intelligence on the 2-3 companies closest to the subscriber
        on the leaderboard, including any recent purchase activity.
        """
        position = self.get_leaderboard_position(email, btc_price, leaderboard_companies)
        if not position:
            return []

        closest = position.get("closest_competitors", [])
        if not closest:
            return []

        # Enrich with purchase data if available
        purchase_map = {}
        if purchases:
            for p in purchases:
                ticker = p.get("ticker", "")
                if ticker not in purchase_map:
                    purchase_map[ticker] = p

        spotlight = []
        subscriber_btc = position["btc_holdings"]

        for c in closest:
            c_btc = c.get("btc_holdings", 0)
            c_ticker = c.get("ticker", "")
            c_name = c.get("company", "")

            # Determine relationship
            diff = c_btc - subscriber_btc
            if abs(diff) < 1:
                relationship = "same"
                rel_text = "Same holdings as you"
            elif diff > 0:
                relationship = "ahead"
                rel_text = f"{diff:,.0f} BTC ahead of you"
            else:
                relationship = "behind"
                rel_text = f"{abs(diff):,.0f} BTC behind you"

            # Check for recent purchase
            recent_purchase = purchase_map.get(c_ticker)
            purchase_text = ""
            if recent_purchase:
                purchase_text = f"Bought {recent_purchase['btc_amount']:,} BTC on {recent_purchase['filing_date']}"

            spotlight.append({
                "company": c_name,
                "ticker": c_ticker,
                "btc_holdings": c_btc,
                "rank": c.get("rank", 0),
                "relationship": relationship,
                "rel_text": rel_text,
                "diff": diff,
                "recent_purchase": purchase_text,
            })

        return spotlight

    def get_personalized_context(self, email, btc_price, action_signal, leaderboard_companies=None):
        """
        Generate a personalized paragraph connecting the market conditions
        to the subscriber's specific position.
        """
        position = self.get_leaderboard_position(email, btc_price, leaderboard_companies)
        if not position:
            return ""

        rank = position["rank"]
        holdings = position["btc_holdings"]
        company = position["company_name"]
        gap = position["next_rank_gap"]
        action = action_signal.get("action", "")
        score = action_signal.get("score", 0)

        lines = []

        # Context based on action signal + position
        if "BUY" in action and gap > 0:
            gap_cost = gap * btc_price
            lines.append(
                f"With a BUY signal active, this could be an optimal time for {company} to accumulate. "
                f"A ${gap_cost/1_000_000:,.1f}M purchase ({gap:,.0f} BTC) would move you from #{rank} to #{rank-1} on the leaderboard."
            )
        elif "ACCUMULATE" in action:
            lines.append(
                f"Market conditions favor steady accumulation. At #{rank} with {holdings:,.0f} BTC, "
                f"{company} is well-positioned to strengthen its treasury through regular purchases."
            )
        elif "WAIT" in action or "HOLD" in action:
            lines.append(
                f"No urgency to deploy capital today. {company} holds #{rank} with {holdings:,.0f} BTC. "
                f"Use this quiet period to prepare for the next high-conviction opportunity."
            )
        elif "CAUTION" in action:
            lines.append(
                f"Risk indicators are elevated. {company}'s current position at #{rank} is stable — "
                f"consider pausing new purchases until conditions improve."
            )

        # Add peer context
        if position.get("companies_ahead"):
            ahead = position["companies_ahead"][-1]
            lines.append(
                f"The company directly ahead of you, {ahead['company']}, holds {ahead['btc_holdings']:,} BTC."
            )

        return " ".join(lines)

    def track_holdings_change(self, email):
        """
        Check if the subscriber's holdings changed since the last snapshot.
        Returns a dict with change details or None if no change.
        """
        profile = self.get_by_email(email)
        if not profile:
            return None

        current_btc = float(profile.get("btc_holdings", 0))

        # Check for previous snapshot in leaderboard_snapshots
        try:
            import json
            yesterday = (datetime.now() - __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")
            result = supabase.table("leaderboard_snapshots").select("companies_json").eq("snapshot_date", yesterday).limit(1).execute()

            if not result.data:
                return None

            prev_holdings = json.loads(result.data[0].get("companies_json", "{}"))
            ticker = profile.get("ticker", "")

            if ticker and ticker in prev_holdings:
                prev_data = prev_holdings[ticker]
                prev_btc = prev_data.get("btc", 0) if isinstance(prev_data, dict) else prev_data
                change = current_btc - prev_btc

                if abs(change) > 0.5:  # Meaningful change
                    return {
                        "previous_btc": prev_btc,
                        "current_btc": current_btc,
                        "change_btc": change,
                        "direction": "increased" if change > 0 else "decreased",
                    }

            return None
        except Exception as e:
            logger.debug(f"Holdings change check failed for {email}: {e}")
            return None


# ============================================
# GLOBAL INSTANCE
# ============================================
subscribers = SubscriberManager()


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Subscriber Manager — testing...")

    print(f"\n{'='*60}")
    print("  SUBSCRIBER SYSTEM")
    print(f"{'='*60}\n")

    # Show setup SQL
    print("Run this SQL in Supabase to create the subscribers table:")
    print(SETUP_SQL)

    # Test: list active subscribers
    active = subscribers.get_active_subscribers()
    logger.info(f"Active subscribers: {len(active)}")

    for s in active:
        logger.info(f"  {s['name']} ({s['company_name']}) — {s['email']} — Plan: {s['plan']}")

    # Test: email recipients
    recipients = subscribers.get_email_recipients()
    logger.info(f"Email recipients: {len(recipients)}")

    logger.info("Subscriber Manager test complete")
