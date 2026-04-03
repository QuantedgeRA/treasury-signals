"""
correlation_engine_v2.py — Market-Wide Multi-Signal Correlation Engine
-----------------------------------------------------------------------
Replaces the original Strategy-centric correlation engine with a
market-wide system that tracks every company individually and detects
institutional wave patterns.

6 Input Streams:
  1. Tweet signals (100+ accounts, mapped to companies)
  2. STRC volume spikes (Strategy-specific capital raise indicator)
  3. EDGAR realtime 8-K filings (US public companies)
  4. Global filing scanner (international regulatory filings)
  5. Whale on-chain detection (large BTC movements)
  6. News scanner (purchase headlines worldwide)

Output:
  - Per-company correlation score (0-100)
  - Market-wide score (0-100) — "institutional wave" detection
  - Ranked company signals with reasons
  - Historical pattern matching
"""

from datetime import datetime, timedelta
from collections import defaultdict
from logger import get_logger

logger = get_logger(__name__)

# ============================================
# CONFIGURATION
# ============================================

# Time window for correlating events (hours)
CORRELATION_WINDOW_HOURS = 48

# Per-company scoring weights
SCORE_WEIGHTS = {
    "tweet_purchase_keywords": 25,     # CEO tweet with purchase-related words
    "tweet_cryptic_signal": 15,        # CEO cryptic/coded tweet (pattern match)
    "tweet_general": 10,               # CEO tweet mentioning BTC (no purchase signal)
    "strc_spike": 20,                  # STRC volume spike (Strategy only)
    "edgar_8k_btc": 30,               # 8-K filing mentioning bitcoin (US)
    "edgar_8k_general": 15,           # 8-K filing, not clearly BTC-related
    "global_filing": 25,              # International regulatory filing
    "whale_identified": 20,           # Whale movement linked to known company
    "whale_unidentified": 10,         # Large whale movement, unknown source
    "news_purchase_confirmed": 20,    # News confirming a purchase
    "news_purchase_rumor": 10,        # News suggesting possible purchase
}

# Multi-stream multipliers (when multiple streams fire for same company)
MULTI_STREAM_MULTIPLIERS = {
    2: 1.5,   # 2 streams → 1.5x
    3: 2.0,   # 3 streams → 2.0x
    4: 2.5,   # 4+ streams → 2.5x
    5: 3.0,
    6: 3.5,
}

# Market-wide scoring thresholds
MARKET_THRESHOLDS = {
    "companies_signaling_2": 20,     # 2 companies with score > 40
    "companies_signaling_3": 40,     # 3+ companies
    "companies_signaling_5": 60,     # 5+ companies (institutional wave)
    "whale_plus_company": 15,        # Whale activity + company signals
    "extreme_fear_accumulation": 10, # Fear & Greed < 20 + company signals
    "dip_buying": 10,                # BTC down 10%+ + company signals
}


# ============================================
# EVENT TRACKING
# ============================================

class CompanySignal:
    """A single signal event for a company."""
    def __init__(self, company, ticker, stream, score, detail, timestamp=None):
        self.company = company
        self.ticker = ticker
        self.stream = stream          # "tweet", "strc", "edgar", "global_filing", "whale", "news"
        self.score = score
        self.detail = detail
        self.timestamp = timestamp or datetime.now()

    def is_within_window(self, hours=CORRELATION_WINDOW_HOURS):
        age = (datetime.now() - self.timestamp).total_seconds() / 3600
        return age <= hours

    def __repr__(self):
        return f"Signal({self.ticker}: {self.stream} +{self.score} — {self.detail[:50]})"


class CorrelationEngineV2:
    """
    Market-wide correlation engine.
    
    Tracks signals per-company and calculates both individual
    company scores and a market-wide "institutional wave" score.
    """

    def __init__(self):
        # All active signals within the correlation window
        self.signals = []

        # Market context
        self.fear_greed_value = 50
        self.btc_weekly_change = 0.0
        self.btc_price = 0

        # Cache for computed scores
        self._last_computed = None
        self._last_result = None

    # ============================================
    # STREAM 1: TWEET SIGNALS
    # ============================================
    def add_tweet_signal(self, author_username, company, ticker, signal_score, tweet_text):
        """
        Add a tweet-based signal. Called by process_and_alert() in main.py.
        
        Args:
            author_username: Twitter handle
            company: Company name
            ticker: Stock ticker
            signal_score: Classification score (0-100)
            tweet_text: The tweet content
        """
        if signal_score >= 60:
            score = SCORE_WEIGHTS["tweet_purchase_keywords"]
            detail = f"HIGH signal from @{author_username}: {tweet_text[:100]}"
        elif signal_score >= 40:
            score = SCORE_WEIGHTS["tweet_cryptic_signal"]
            detail = f"MEDIUM signal from @{author_username}: {tweet_text[:100]}"
        else:
            score = SCORE_WEIGHTS["tweet_general"]
            detail = f"LOW signal from @{author_username}: {tweet_text[:100]}"

        signal = CompanySignal(company, ticker, "tweet", score, detail)
        self.signals.append(signal)
        self._cleanup_old_signals()
        logger.debug(f"Correlation: +tweet for {ticker} ({score}pts) — @{author_username}")

    # ============================================
    # STREAM 2: STRC VOLUME
    # ============================================
    def add_strc_spike(self, volume_ratio, dollar_volume_m):
        """
        Add STRC volume spike signal. Strategy-specific.
        
        Args:
            volume_ratio: Today's volume / 20-day average
            dollar_volume_m: Dollar volume in millions
        """
        if volume_ratio < 1.5:
            return  # Not significant enough

        score = SCORE_WEIGHTS["strc_spike"]
        # Scale score by intensity
        if volume_ratio >= 3.0:
            score = int(score * 1.5)  # 30 pts for extreme spike
        elif volume_ratio >= 2.0:
            score = int(score * 1.25)  # 25 pts for high spike

        detail = f"STRC volume {volume_ratio:.1f}x average (${dollar_volume_m:.0f}M)"
        signal = CompanySignal("Strategy", "MSTR", "strc", score, detail)
        self.signals.append(signal)
        self._cleanup_old_signals()
        logger.debug(f"Correlation: +strc for MSTR ({score}pts) — {volume_ratio:.1f}x")

    # ============================================
    # STREAM 3: EDGAR REALTIME
    # ============================================
    def add_edgar_filing(self, company, ticker, is_btc_related, filing_date, btc_amount=0):
        """
        Add an EDGAR 8-K filing signal.
        
        Args:
            company: Company name from filing
            ticker: Ticker/CIK
            is_btc_related: Whether filing mentions bitcoin
            filing_date: Date of filing
            btc_amount: BTC amount extracted (0 if not a purchase)
        """
        if is_btc_related:
            score = SCORE_WEIGHTS["edgar_8k_btc"]
            detail = f"8-K filing (BTC-related) on {filing_date}"
            if btc_amount > 0:
                score += 10  # Bonus for confirmed purchase amount
                detail += f" — {btc_amount:,.0f} BTC"
        else:
            score = SCORE_WEIGHTS["edgar_8k_general"]
            detail = f"8-K filing on {filing_date}"

        # Normalize ticker
        clean_ticker = ticker.upper().replace(".US", "").strip()

        signal = CompanySignal(company, clean_ticker, "edgar", score, detail)
        self.signals.append(signal)
        self._cleanup_old_signals()
        logger.debug(f"Correlation: +edgar for {clean_ticker} ({score}pts)")

    # ============================================
    # STREAM 4: GLOBAL FILING SCANNER
    # ============================================
    def add_global_filing(self, company, ticker, country, filing_type, detail_text):
        """
        Add an international regulatory filing signal.
        
        Args:
            company: Company name
            ticker: Ticker
            country: Country code
            filing_type: e.g., "TDnet", "SEDAR", "DART", "RNS"
            detail_text: Description
        """
        score = SCORE_WEIGHTS["global_filing"]
        detail = f"{filing_type} ({country}): {detail_text[:100]}"

        clean_ticker = ticker.upper().replace(".US", "").strip() if ticker else company[:10].upper()

        signal = CompanySignal(company, clean_ticker, "global_filing", score, detail)
        self.signals.append(signal)
        self._cleanup_old_signals()
        logger.debug(f"Correlation: +global_filing for {clean_ticker} ({score}pts)")

    # ============================================
    # STREAM 5: WHALE ON-CHAIN DETECTION
    # ============================================
    def add_whale_movement(self, btc_amount, from_entity=None, to_entity=None, from_ticker=None, to_ticker=None):
        """
        Add a whale on-chain movement signal.
        
        Args:
            btc_amount: Amount of BTC moved
            from_entity: Source entity name (None if unknown)
            to_entity: Destination entity name (None if unknown)
            from_ticker: Source ticker
            to_ticker: Destination ticker
        """
        if btc_amount < 500:
            return  # Too small to matter

        # If we can identify the entity, it's a stronger signal
        if to_entity and to_ticker:
            score = SCORE_WEIGHTS["whale_identified"]
            detail = f"Whale: {btc_amount:,.0f} BTC → {to_entity}"
            signal = CompanySignal(to_entity, to_ticker, "whale", score, detail)
            self.signals.append(signal)
            logger.debug(f"Correlation: +whale (identified) for {to_ticker} ({score}pts)")
        elif from_entity and from_ticker:
            score = SCORE_WEIGHTS["whale_identified"]
            detail = f"Whale: {btc_amount:,.0f} BTC from {from_entity}"
            signal = CompanySignal(from_entity, from_ticker, "whale", score, detail)
            self.signals.append(signal)
            logger.debug(f"Correlation: +whale (identified) for {from_ticker} ({score}pts)")
        else:
            # Unknown whale — contributes to market-wide score only
            score = SCORE_WEIGHTS["whale_unidentified"]
            detail = f"Whale: {btc_amount:,.0f} BTC (Unknown → Unknown)"
            signal = CompanySignal("Unknown Whale", "WHALE", "whale", score, detail)
            self.signals.append(signal)
            logger.debug(f"Correlation: +whale (unidentified) ({score}pts) — {btc_amount:,.0f} BTC")

        self._cleanup_old_signals()

    # ============================================
    # STREAM 6: NEWS SCANNER
    # ============================================
    def add_news_signal(self, company, ticker, is_confirmed_purchase, headline):
        """
        Add a news-based purchase signal.
        
        Args:
            company: Company name
            ticker: Ticker
            is_confirmed_purchase: True if headline confirms a purchase
            headline: News headline
        """
        if is_confirmed_purchase:
            score = SCORE_WEIGHTS["news_purchase_confirmed"]
            detail = f"News (confirmed): {headline[:100]}"
        else:
            score = SCORE_WEIGHTS["news_purchase_rumor"]
            detail = f"News (possible): {headline[:100]}"

        clean_ticker = ticker.upper().replace(".US", "").strip() if ticker else company[:10].upper()

        signal = CompanySignal(company, clean_ticker, "news", score, detail)
        self.signals.append(signal)
        self._cleanup_old_signals()
        logger.debug(f"Correlation: +news for {clean_ticker} ({score}pts)")

    # ============================================
    # MARKET CONTEXT
    # ============================================
    def update_market_context(self, fear_greed=None, btc_weekly_change=None, btc_price=None):
        """Update market context for pattern matching."""
        if fear_greed is not None:
            self.fear_greed_value = fear_greed
        if btc_weekly_change is not None:
            self.btc_weekly_change = btc_weekly_change
        if btc_price is not None:
            self.btc_price = btc_price

    # ============================================
    # SCORE CALCULATION
    # ============================================
    def _cleanup_old_signals(self):
        """Remove signals older than the correlation window."""
        cutoff = datetime.now() - timedelta(hours=CORRELATION_WINDOW_HOURS)
        self.signals = [s for s in self.signals if s.timestamp >= cutoff]

    def _get_active_signals(self):
        """Get all signals within the correlation window."""
        self._cleanup_old_signals()
        return self.signals

    def _calculate_company_scores(self):
        """
        Calculate per-company correlation scores.
        Returns dict: {ticker: {company, ticker, score, streams, signals, reasons}}
        """
        active = self._get_active_signals()
        companies = defaultdict(lambda: {
            "company": "",
            "ticker": "",
            "raw_score": 0,
            "streams": set(),
            "signals": [],
            "reasons": [],
        })

        for signal in active:
            ticker = signal.ticker
            if ticker == "WHALE":
                continue  # Unidentified whales don't contribute to company scores

            companies[ticker]["company"] = signal.company
            companies[ticker]["ticker"] = ticker
            companies[ticker]["raw_score"] += signal.score
            companies[ticker]["streams"].add(signal.stream)
            companies[ticker]["signals"].append(signal)
            companies[ticker]["reasons"].append(f"{signal.stream}: {signal.detail[:80]}")

        # Apply multi-stream multipliers
        result = {}
        for ticker, data in companies.items():
            num_streams = len(data["streams"])
            multiplier = 1.0
            for threshold, mult in sorted(MULTI_STREAM_MULTIPLIERS.items()):
                if num_streams >= threshold:
                    multiplier = mult

            final_score = min(100, int(data["raw_score"] * multiplier))

            result[ticker] = {
                "company": data["company"],
                "ticker": ticker,
                "score": final_score,
                "raw_score": data["raw_score"],
                "num_streams": num_streams,
                "streams": list(data["streams"]),
                "multiplier": multiplier,
                "signals": data["signals"],
                "reasons": data["reasons"],
            }

        return result

    def _calculate_market_wide_score(self, company_scores):
        """
        Calculate the market-wide "institutional wave" score.
        High when multiple companies are signaling simultaneously.
        """
        score = 0
        reasons = []

        # Count companies with meaningful signals
        signaling = {t: d for t, d in company_scores.items() if d["score"] >= 40}
        num_signaling = len(signaling)

        if num_signaling >= 5:
            score += MARKET_THRESHOLDS["companies_signaling_5"]
            reasons.append(f"🔴 INSTITUTIONAL WAVE: {num_signaling} companies signaling simultaneously")
        elif num_signaling >= 3:
            score += MARKET_THRESHOLDS["companies_signaling_3"]
            reasons.append(f"🟠 Multiple signals: {num_signaling} companies active")
        elif num_signaling >= 2:
            score += MARKET_THRESHOLDS["companies_signaling_2"]
            reasons.append(f"🟡 Dual signals: {num_signaling} companies active")

        # Whale activity amplifier
        whale_signals = [s for s in self._get_active_signals() if s.stream == "whale"]
        total_whale_btc = sum(
            int(s.detail.split("BTC")[0].split()[-1].replace(",", ""))
            for s in whale_signals
            if "BTC" in s.detail
        ) if whale_signals else 0

        if whale_signals and num_signaling >= 1:
            score += MARKET_THRESHOLDS["whale_plus_company"]
            reasons.append(f"🐋 Whale activity ({len(whale_signals)} movements, ~{total_whale_btc:,} BTC) + company signals")

        # Fear & Greed amplifier (accumulation zone)
        if self.fear_greed_value < 20 and num_signaling >= 1:
            score += MARKET_THRESHOLDS["extreme_fear_accumulation"]
            reasons.append(f"😱 Extreme fear (F&G: {self.fear_greed_value}) — accumulation zone active")

        # Dip buying amplifier
        if self.btc_weekly_change < -10 and num_signaling >= 1:
            score += MARKET_THRESHOLDS["dip_buying"]
            reasons.append(f"📉 BTC down {self.btc_weekly_change:.1f}% this week — dip buying likely")

        return min(100, score), reasons

    def calculate_correlation(self):
        """
        Main calculation method. Returns complete correlation analysis.
        
        Returns dict with:
            - company_scores: per-company breakdown
            - market_score: market-wide institutional wave score
            - top_companies: ranked list of companies by score
            - total_signals: number of active signals
            - total_streams: number of unique streams active
            - alert_level: "NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"
            - narrative: human-readable summary
            - reasons: list of market-wide reasons
        """
        company_scores = self._calculate_company_scores()
        market_score, market_reasons = self._calculate_market_wide_score(company_scores)

        # Rank companies by score
        top_companies = sorted(
            company_scores.values(),
            key=lambda x: x["score"],
            reverse=True
        )

        # Count unique active streams across all companies
        all_streams = set()
        for data in company_scores.values():
            all_streams.update(data["streams"])

        # Include whale as a stream if present
        whale_signals = [s for s in self._get_active_signals() if s.stream == "whale"]
        if whale_signals:
            all_streams.add("whale")

        # Determine alert level
        if market_score >= 70 or any(c["score"] >= 80 for c in top_companies):
            alert_level = "CRITICAL"
        elif market_score >= 50 or any(c["score"] >= 60 for c in top_companies):
            alert_level = "HIGH"
        elif market_score >= 30 or any(c["score"] >= 40 for c in top_companies):
            alert_level = "MEDIUM"
        elif market_score >= 10 or any(c["score"] >= 20 for c in top_companies):
            alert_level = "LOW"
        else:
            alert_level = "NONE"

        # Build narrative
        narrative = self._build_narrative(top_companies, market_score, market_reasons, whale_signals)

        result = {
            "company_scores": company_scores,
            "market_score": market_score,
            "top_companies": top_companies[:10],  # Top 10
            "total_signals": len(self._get_active_signals()),
            "total_streams": len(all_streams),
            "active_streams": list(all_streams),
            "alert_level": alert_level,
            "narrative": narrative,
            "reasons": market_reasons,
            "fear_greed": self.fear_greed_value,
            "btc_weekly_change": self.btc_weekly_change,
            # Backward compatibility fields
            "correlated_score": market_score,
            "active_streams_count": len(all_streams),
            "multiplier": max((c.get("multiplier", 1) for c in top_companies), default=1),
        }

        self._last_computed = datetime.now()
        self._last_result = result

        return result

    def _build_narrative(self, top_companies, market_score, market_reasons, whale_signals):
        """Build a human-readable narrative of the current state."""
        parts = []

        signaling = [c for c in top_companies if c["score"] >= 40]

        if not signaling and not whale_signals:
            return "No significant correlation signals detected. Market is quiet."

        if market_score >= 70:
            parts.append(f"⚠️ INSTITUTIONAL WAVE DETECTED — Market-wide score: {market_score}/100.")
        elif market_score >= 40:
            parts.append(f"🟠 Elevated market activity — Market-wide score: {market_score}/100.")

        if signaling:
            company_list = ", ".join(f"{c['company']} ({c['score']}/100)" for c in signaling[:5])
            parts.append(f"Active companies: {company_list}.")

        for c in signaling[:3]:
            streams_str = " + ".join(c["streams"])
            parts.append(f"{c['company']}: {streams_str} → {c['score']}/100 ({c['multiplier']}x multiplier).")

        if whale_signals:
            parts.append(f"On-chain: {len(whale_signals)} whale movement(s) detected in last {CORRELATION_WINDOW_HOURS}h.")

        if self.fear_greed_value < 25:
            parts.append(f"Market sentiment: Extreme Fear ({self.fear_greed_value}) — historically an accumulation zone.")

        return " ".join(parts)

    # ============================================
    # TELEGRAM FORMATTING
    # ============================================
    def format_correlation_alert(self, result=None):
        """Format a Telegram alert for the correlation state."""
        if result is None:
            result = self.calculate_correlation()

        market_score = result["market_score"]
        top = result["top_companies"]
        signaling = [c for c in top if c["score"] >= 30]

        lines = []
        lines.append(f"🔗 MARKET CORRELATION ENGINE v2\n")
        lines.append(f"Market-Wide Score: {market_score}/100")
        lines.append(f"Active Streams: {result['total_streams']}/6")
        lines.append(f"Total Signals: {result['total_signals']} (last {CORRELATION_WINDOW_HOURS}h)")
        lines.append("")

        if signaling:
            lines.append("📊 Company Signals:")
            for c in signaling[:8]:
                bar_filled = int(c["score"] / 10)
                bar_empty = 10 - bar_filled
                bar = "█" * bar_filled + "░" * bar_empty
                streams_str = " + ".join(c["streams"])
                lines.append(f"  {c['company'][:20]}: {c['score']}/100 {bar}")
                lines.append(f"    → {streams_str} ({c['multiplier']}x)")
            lines.append("")

        if result["reasons"]:
            lines.append("🔍 Market Patterns:")
            for reason in result["reasons"]:
                lines.append(f"  {reason}")
            lines.append("")

        if result.get("narrative"):
            lines.append(f"📝 {result['narrative'][:300]}")

        lines.append("\n---")
        lines.append("Treasury Signal Intelligence")
        lines.append("Multi-Signal Correlation Engine™ v2")

        return "\n".join(lines)

    def format_company_alert(self, ticker):
        """Format a Telegram alert for a specific company's signals."""
        result = self.calculate_correlation()
        company_data = result["company_scores"].get(ticker)

        if not company_data or company_data["score"] < 30:
            return None

        lines = []
        lines.append(f"🔗 COMPANY SIGNAL ALERT\n")
        lines.append(f"📊 {company_data['company']} ({ticker})")
        lines.append(f"Score: {company_data['score']}/100")
        lines.append(f"Streams: {' + '.join(company_data['streams'])} ({company_data['multiplier']}x)")
        lines.append("")

        lines.append("📋 Signal Details:")
        for reason in company_data["reasons"][:5]:
            lines.append(f"  • {reason}")

        lines.append("\n---")
        lines.append("Treasury Signal Intelligence")

        return "\n".join(lines)

    # ============================================
    # STATUS / DEBUG
    # ============================================
    def get_status(self):
        """Get current engine status for logging."""
        active = self._get_active_signals()
        companies = set(s.ticker for s in active if s.ticker != "WHALE")
        streams = set(s.stream for s in active)

        return {
            "total_signals": len(active),
            "unique_companies": len(companies),
            "active_streams": list(streams),
            "num_streams": len(streams),
            "fear_greed": self.fear_greed_value,
        }

    def get_summary_line(self):
        """One-line summary for log output."""
        status = self.get_status()
        if self._last_result:
            ms = self._last_result["market_score"]
            level = self._last_result["alert_level"]
            return f"Market: {ms}/100 | {status['num_streams']}/6 streams | {status['unique_companies']} companies | {level}"
        return f"Signals: {status['total_signals']} | {status['num_streams']}/6 streams | {status['unique_companies']} companies"


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Correlation Engine v2 — self-test")
    logger.info("=" * 60)

    engine = CorrelationEngineV2()

    # Simulate signals
    engine.add_tweet_signal("saylor", "Strategy", "MSTR", 85, "Stretch the Orange Dots")
    engine.add_strc_spike(2.5, 450)
    engine.add_edgar_filing("Strategy", "MSTR", True, "2026-04-02", btc_amount=1031)
    engine.add_tweet_signal("gerovich", "Metaplanet", "3350.T", 65, "Bitcoin is the future of Japan")
    engine.add_whale_movement(5000, to_entity=None, to_ticker=None)
    engine.add_news_signal("GameStop", "GME", True, "GameStop buys 500 BTC for treasury reserve")
    engine.update_market_context(fear_greed=18, btc_weekly_change=-8.5, btc_price=66000)

    result = engine.calculate_correlation()

    logger.info(f"\nMarket-Wide Score: {result['market_score']}/100")
    logger.info(f"Alert Level: {result['alert_level']}")
    logger.info(f"Active Streams: {result['active_streams']}")
    logger.info(f"Total Signals: {result['total_signals']}")

    logger.info(f"\nTop Companies:")
    for c in result['top_companies'][:5]:
        logger.info(f"  {c['company']}: {c['score']}/100 ({' + '.join(c['streams'])})")

    logger.info(f"\nMarket Reasons:")
    for r in result['reasons']:
        logger.info(f"  {r}")

    logger.info(f"\nNarrative: {result['narrative']}")
    logger.info(f"\nTelegram Alert:\n{engine.format_correlation_alert(result)}")

    logger.info("\nCorrelation Engine v2 self-test complete")

# Backward compatibility — other files still import the old name
CorrelationEngine = CorrelationEngineV2
