"""
narrative_engine.py — LLM-Powered Intelligence Narratives
-----------------------------------------------------------
Uses Claude API to generate analyst-quality prose from raw signal data.

Generates three types of narratives:
1. Daily Intelligence Summary — replaces templated action signal text
2. Pattern Explanation — explains why patterns match in plain English
3. Purchase Analysis — contextualizes detected purchases

Narratives are stored in Supabase for display in emails and dashboard.

Usage:
    from narrative_engine import narrator

    # Generate daily intelligence narrative
    narrative = narrator.generate_daily_narrative(
        action_signal=action,
        pattern_match=pattern_match,
        market_data=market,
        risk_data=risk,
        signals=signals,
        purchases=purchases,
        subscriber=subscriber,
    )

    # Generate purchase analysis
    analysis = narrator.analyze_purchase(purchase_data, market_context)
"""

import os
import json
from datetime import datetime
from dotenv import load_dotenv
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Lazy import to avoid crash if anthropic not installed
_client = None

def _get_client():
    global _client
    if _client is None:
        try:
            import anthropic
            _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        except ImportError:
            logger.warning("anthropic package not installed — LLM narratives disabled")
            _client = False
        except Exception as e:
            logger.warning(f"Anthropic client init failed: {e}")
            _client = False
    return _client if _client else None


def _call_claude(system_prompt, user_prompt, max_tokens=500):
    """Call Claude API with error handling."""
    client = _get_client()
    if not client:
        return None

    if not ANTHROPIC_API_KEY:
        logger.debug("No ANTHROPIC_API_KEY set — skipping LLM narrative")
        return None

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text.strip()
        logger.debug(f"Claude response: {len(text)} chars")
        return text
    except Exception as e:
        logger.warning(f"Claude API call failed: {e}")
        return None


# ============================================
# SYSTEM PROMPTS
# ============================================

DAILY_SYSTEM = """You are the chief intelligence analyst at Treasury Signal Intelligence, a Bitcoin corporate treasury monitoring platform. You write daily intelligence briefings for CEOs considering or managing Bitcoin treasury positions.

Your tone is: authoritative, concise, data-driven, actionable. Like a Goldman Sachs morning briefing crossed with a Bloomberg terminal alert.

Rules:
- Write in 2-3 short paragraphs, max 150 words total
- Lead with the most important insight
- Reference specific numbers and data points provided
- Connect current conditions to historical patterns when relevant
- End with a clear, actionable takeaway for the subscriber
- Never use disclaimers, caveats, or "not financial advice" — that's handled elsewhere
- Never use bullet points — write in flowing prose
- Use present tense and active voice"""

PATTERN_SYSTEM = """You are a pattern recognition analyst specializing in Bitcoin corporate treasury purchases. You explain why historical purchase patterns match current conditions in plain English.

Rules:
- Write 1-2 paragraphs, max 100 words
- Explain which patterns are firing and why they matter
- Reference historical success rates
- Be specific about what would need to change for confidence to increase or decrease
- Never use bullet points"""

PURCHASE_SYSTEM = """You are a financial analyst covering Bitcoin corporate treasury purchases. You write brief, insightful analyses of confirmed BTC acquisitions.

Rules:
- Write 1-2 paragraphs, max 120 words
- Contextualize the purchase (size relative to company's history, market conditions)
- Note if the system predicted it in advance
- Connect to broader treasury adoption trends
- Never use bullet points"""


# ============================================
# NARRATIVE GENERATORS
# ============================================

class NarrativeEngine:
    """Generates LLM-powered intelligence narratives."""

    def __init__(self):
        self._cache = {}

    def generate_daily_narrative(self, action_signal=None, pattern_match=None,
                                  market_data=None, risk_data=None, signals=None,
                                  purchases=None, subscriber=None):
        """Generate the daily intelligence narrative."""
        action = action_signal or {}
        pattern = pattern_match or {}
        market = market_data or {}
        risk = risk_data or {}
        signals = signals or []
        purchases = purchases or []

        # Build context for Claude
        btc_price = market.get("btc_price", 0)
        btc_change = market.get("btc_change", 0)
        strc_ratio = market.get("strc_ratio", 0)
        fg_value = risk.get("fear_greed_value", 50)
        fg_label = risk.get("fear_greed_label", "Neutral")
        risk_level = risk.get("risk_level", "MODERATE")
        action_text = action.get("action", "HOLD")
        action_score = action.get("score", 0)
        pattern_score = pattern.get("score", 0)
        matched_patterns = pattern.get("matching_patterns", [])
        pattern_names = [p["name"] for p in matched_patterns]
        high_signals = len([s for s in signals if s.get("confidence_score", 0) >= 60])
        recent_purchases_text = ""
        if purchases:
            p = purchases[0]
            recent_purchases_text = f"Most recent purchase: {p.get('company', '')} bought {p.get('btc_amount', 0):,} BTC on {p.get('filing_date', '')}."

        # Subscriber context
        sub_context = ""
        if subscriber:
            holdings = float(subscriber.get("btc_holdings", 0))
            company = subscriber.get("company_name", "")
            if holdings > 0:
                sub_context = f"The subscriber is {company} with {holdings:,.0f} BTC. Tailor the closing sentence to their position."
            elif company:
                sub_context = f"The subscriber is {company} with no BTC yet. They are evaluating a treasury strategy."

        prompt = f"""Today's data for the daily intelligence briefing:

Bitcoin: ${btc_price:,.0f} ({btc_change:+.1f}% 24h)
Fear & Greed: {fg_value} ({fg_label})
Risk Level: {risk_level}
STRC Volume Ratio: {strc_ratio:.1f}x average
Action Signal: {action_text} (score: {action_score}/100)
High-confidence tweet signals (24h): {high_signals}
Pattern Match: {pattern_score}/100 — {len(matched_patterns)} patterns active: {', '.join(pattern_names) if pattern_names else 'none'}
{recent_purchases_text}
{sub_context}

Write today's intelligence narrative."""

        narrative = _call_claude(DAILY_SYSTEM, prompt, max_tokens=400)

        if narrative:
            logger.info(f"Daily narrative generated: {len(narrative)} chars")
            self._save_narrative("daily", narrative)
        else:
            narrative = action.get("summary", "No strong signals detected.")
            logger.debug("Using fallback summary (LLM unavailable)")

        return narrative

    def explain_pattern_match(self, pattern_match):
        """Generate plain-English explanation of pattern match."""
        if not pattern_match or pattern_match.get("score", 0) == 0:
            return ""

        matched = pattern_match.get("matching_patterns", [])
        if not matched:
            return ""

        patterns_text = ""
        for p in matched:
            patterns_text += f"- {p['name']}: {p['match_detail']} ({p['historical_frequency']})\n"

        prompt = f"""Current pattern match score: {pattern_match['score']}/100
Matched patterns ({len(matched)}/{pattern_match.get('total_patterns', 8)}):
{patterns_text}

Explain what this pattern alignment means and what to watch for next."""

        explanation = _call_claude(PATTERN_SYSTEM, prompt, max_tokens=250)

        if explanation:
            logger.info(f"Pattern explanation generated: {len(explanation)} chars")
        return explanation or pattern_match.get("narrative", "")

    def analyze_purchase(self, purchase, market_context=None, was_predicted=False, lead_time_hours=None):
        """Generate contextual analysis of a detected purchase."""
        market = market_context or {}

        company = purchase.get("company", "Unknown")
        btc_amount = purchase.get("btc_amount", 0)
        usd_amount = purchase.get("usd_amount", 0)
        price = purchase.get("price_per_btc", 0)
        date = purchase.get("filing_date", "")

        prediction_text = ""
        if was_predicted and lead_time_hours:
            prediction_text = f"Our system predicted this purchase {lead_time_hours:.0f} hours in advance."
        elif was_predicted:
            prediction_text = "Our system predicted this purchase in advance."

        prompt = f"""Confirmed Bitcoin purchase:
Company: {company}
Amount: {btc_amount:,} BTC
Cost: ${usd_amount/1_000_000:,.0f}M at ${price:,.0f}/BTC
Date: {date}
BTC Price: ${market.get('btc_price', 0):,.0f}
Fear & Greed: {market.get('fear_greed', 50)}
{prediction_text}

Write a brief analysis of this purchase."""

        analysis = _call_claude(PURCHASE_SYSTEM, prompt, max_tokens=300)

        if analysis:
            logger.info(f"Purchase analysis generated for {company}: {len(analysis)} chars")
        return analysis or f"{company} acquired {btc_amount:,} BTC for ${usd_amount/1_000_000:,.0f}M."

    def _save_narrative(self, narrative_type, text):
        """Save narrative to Supabase for dashboard display."""
        try:
            from database import supabase
            supabase.table("narratives").upsert({
                "narrative_type": narrative_type,
                "narrative_date": datetime.now().strftime("%Y-%m-%d"),
                "content": text[:2000],
                "generated_at": datetime.now().isoformat(),
            }, on_conflict="narrative_type,narrative_date").execute()
        except Exception as e:
            logger.debug(f"Could not save narrative: {e}")

    def get_latest_narrative(self, narrative_type="daily"):
        """Get the most recent narrative from Supabase."""
        try:
            from database import supabase
            result = supabase.table("narratives").select("*").eq("narrative_type", narrative_type).order("generated_at", desc=True).limit(1).execute()
            if result.data:
                return result.data[0].get("content", "")
        except Exception as e:
            logger.debug(f"Could not load narrative: {e}")
        return ""


# ============================================
# GLOBAL INSTANCE
# ============================================
narrator = NarrativeEngine()


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Narrative Engine — testing...")

    test_narrative = narrator.generate_daily_narrative(
        action_signal={"action": "🟡 WAIT", "score": 15, "summary": "Markets quiet."},
        pattern_match={"score": 13, "matching_patterns": [{"name": "Fear-Based Accumulation", "match_detail": "F&G at 8", "historical_frequency": "45% of purchases"}]},
        market_data={"btc_price": 70853, "btc_change": -2.1, "strc_ratio": 0.79},
        risk_data={"fear_greed_value": 8, "fear_greed_label": "Extreme Fear", "risk_level": "HIGH"},
    )

    print(f"\n{'='*60}")
    print("  DAILY INTELLIGENCE NARRATIVE")
    print(f"{'='*60}\n")
    print(test_narrative)

    logger.info("Narrative Engine test complete")
