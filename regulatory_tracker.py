"""
regulatory_tracker.py
---------------------
Government & Regulatory Bitcoin Tracker v2.0

Tracks major legislative and regulatory developments
affecting Bitcoin and corporate treasury adoption WORLDWIDE.

Note: REGULATORY_ITEMS and NOTABLE_STATEMENTS below are used
ONLY for initial seeding into Supabase. Once seeded, the database
is the single source of truth. These lists are a last-resort fallback.
"""

from datetime import datetime
from logger import get_logger

logger = get_logger(__name__)


# ============================================
# REGULATORY DATABASE v2.0 — WORLDWIDE
# Used for initial seeding only. DB is source of truth.
# ============================================

REGULATORY_ITEMS = [
    {"id": "genius-act", "title": "GENIUS Act (Guiding and Establishing National Innovation for US Stablecoins)", "category": "US Federal", "type": "Legislation", "status": "Passed Senate", "status_color": "green", "date_introduced": "2025-02-04", "date_updated": "2025-05-20", "sponsors": "Sen. Bill Hagerty (R-TN), Sen. Kirsten Gillibrand (D-NY)", "summary": "Establishes a regulatory framework for stablecoins in the US. Requires issuers to maintain 1:1 reserves.", "impact": "HIGH — Legitimizes crypto infrastructure.", "btc_impact": "BULLISH"},
    {"id": "clarity-act", "title": "CLARITY Act", "category": "US Federal", "type": "Legislation", "status": "In Committee", "status_color": "yellow", "date_introduced": "2025-03-01", "date_updated": "2025-03-15", "sponsors": "Rep. French Hill (R-AR), Rep. Maxine Waters (D-CA)", "summary": "Defines which digital assets are securities vs. commodities.", "impact": "VERY HIGH — Would definitively classify Bitcoin as a commodity.", "btc_impact": "VERY BULLISH"},
    {"id": "bitcoin-act-2025", "title": "BITCOIN Act (Strategic Reserve Acquisition)", "category": "US Federal", "type": "Legislation", "status": "Introduced", "status_color": "yellow", "date_introduced": "2025-03-11", "date_updated": "2025-03-11", "sponsors": "Sen. Cynthia Lummis (R-WY)", "summary": "Proposes the US government acquire up to 1 million BTC over 5 years.", "impact": "EXTREME — Largest single Bitcoin purchase in history if passed.", "btc_impact": "EXTREMELY BULLISH"},
    {"id": "us-strategic-btc-reserve", "title": "US Strategic Bitcoin Reserve (Executive Order)", "category": "US Federal", "type": "Executive Order", "status": "Active", "status_color": "green", "date_introduced": "2025-03-06", "date_updated": "2025-03-06", "sponsors": "President Trump", "summary": "Establishes a Strategic Bitcoin Reserve using BTC seized in criminal/civil forfeiture.", "impact": "HIGH — US government officially treats Bitcoin as a strategic reserve asset.", "btc_impact": "BULLISH"},
    {"id": "us-digital-asset-stockpile", "title": "US Digital Asset Stockpile (Executive Order)", "category": "US Federal", "type": "Executive Order", "status": "Active", "status_color": "green", "date_introduced": "2025-03-06", "date_updated": "2025-03-06", "sponsors": "President Trump", "summary": "Creates a separate stockpile for non-Bitcoin digital assets seized by the government.", "impact": "MEDIUM — Signals broad government engagement with digital assets.", "btc_impact": "NEUTRAL"},
    {"id": "new-hampshire-btc", "title": "New Hampshire Bitcoin Reserve (HB 302)", "category": "US State", "type": "Legislation", "status": "Signed into Law", "status_color": "green", "date_introduced": "2025-01-08", "date_updated": "2025-05-06", "sponsors": "State Legislature", "summary": "First US state to sign a BTC reserve bill into law. Up to 5% of state funds.", "impact": "HIGH — Historic precedent.", "btc_impact": "BULLISH"},
    {"id": "texas-btc-reserve", "title": "Texas Strategic Bitcoin Reserve (SB 778)", "category": "US State", "type": "Legislation", "status": "Passed Senate", "status_color": "green", "date_introduced": "2025-01-15", "date_updated": "2025-03-12", "sponsors": "Sen. Charles Schwertner (R)", "summary": "Allows Texas Comptroller to invest state funds in Bitcoin.", "impact": "HIGH — Texas leads, other states follow.", "btc_impact": "BULLISH"},
    {"id": "arizona-btc-reserve", "title": "Arizona Bitcoin Reserve Act (SB 1025)", "category": "US State", "type": "Legislation", "status": "Passed Legislature", "status_color": "green", "date_introduced": "2025-01-01", "date_updated": "2025-03-10", "sponsors": "Sen. Wendy Rogers (R)", "summary": "Allows Arizona to allocate up to 10% of state treasury and pension funds to Bitcoin.", "impact": "MEDIUM", "btc_impact": "BULLISH"},
    {"id": "utah-blockchain-act", "title": "Utah Blockchain and Digital Innovation Act", "category": "US State", "type": "Legislation", "status": "Signed into Law", "status_color": "green", "date_introduced": "2025-01-15", "date_updated": "2025-03-07", "sponsors": "State Legislature", "summary": "Protects rights to self-custody of digital assets, mine Bitcoin, and run blockchain nodes.", "impact": "MEDIUM", "btc_impact": "BULLISH"},
    {"id": "eu-mica", "title": "EU MiCA Regulation (Markets in Crypto-Assets)", "category": "Europe", "type": "Regulation", "status": "Active", "status_color": "green", "date_introduced": "2023-06-09", "date_updated": "2025-01-01", "sponsors": "European Commission", "summary": "Comprehensive EU-wide regulatory framework for crypto-assets.", "impact": "HIGH — Provides regulatory clarity across 27 EU member states.", "btc_impact": "BULLISH"},
    {"id": "czech-btc-reserve", "title": "Czech National Bank Bitcoin Reserve Proposal", "category": "Europe", "type": "Proposal", "status": "Under Consideration", "status_color": "yellow", "date_introduced": "2025-01-22", "date_updated": "2025-02-15", "sponsors": "Ales Michl, CNB Governor", "summary": "Governor proposed allocating up to 5% of reserves to Bitcoin.", "impact": "HIGH — First major European central bank to seriously consider BTC.", "btc_impact": "VERY BULLISH"},
    {"id": "japan-stablecoin", "title": "Japan Stablecoin Regulation", "category": "Asia-Pacific", "type": "Regulation", "status": "Active", "status_color": "green", "date_introduced": "2023-06-01", "date_updated": "2025-01-01", "sponsors": "Financial Services Agency (FSA)", "summary": "Allows licensed banks and trust companies to issue stablecoins.", "impact": "MEDIUM — Opens institutional on-ramps in world's third largest economy.", "btc_impact": "BULLISH"},
    {"id": "el-salvador-btc-bonds", "title": "El Salvador Bitcoin Bonds (Volcano Bonds)", "category": "Latin America", "type": "Financial Instrument", "status": "Issued", "status_color": "green", "date_introduced": "2024-11-01", "date_updated": "2025-02-01", "sponsors": "Government of El Salvador", "summary": "World's first sovereign Bitcoin-backed bonds.", "impact": "MEDIUM — Template for other nations.", "btc_impact": "BULLISH"},
]

NOTABLE_STATEMENTS = [
    {"person": "Donald Trump", "title": "President of the United States", "date": "2025-03-06", "statement": "Signed executive orders establishing the US Strategic Bitcoin Reserve and Digital Asset Stockpile.", "impact": "EXTREMELY BULLISH", "category": "Government"},
    {"person": "Michael Saylor", "title": "Executive Chairman, Strategy", "date": "2025-03-15", "statement": "Stretch the Orange Dots. (Known purchase hint pattern)", "impact": "VERY BULLISH", "category": "CEO"},
    {"person": "Larry Fink", "title": "CEO, BlackRock", "date": "2025-01-20", "statement": "Bitcoin could reach $700,000 if sovereign wealth funds allocate even 2-5% to it.", "impact": "VERY BULLISH", "category": "CEO"},
    {"person": "Ales Michl", "title": "Governor, Czech National Bank", "date": "2025-01-22", "statement": "We should consider allocating part of our reserves to Bitcoin as a diversification strategy.", "impact": "VERY BULLISH", "category": "Government"},
    {"person": "Paul Atkins", "title": "SEC Chair", "date": "2025-02-01", "statement": "The SEC will work to provide clear, innovation-friendly rules for digital assets.", "impact": "BULLISH", "category": "Government"},
    {"person": "Cathie Wood", "title": "CEO, ARK Invest", "date": "2025-01-15", "statement": "Bitcoin will reach $1.5 million by 2030 in our bull case. Institutional adoption is accelerating.", "impact": "VERY BULLISH", "category": "CEO"},
    {"person": "Jamie Dimon", "title": "CEO, JPMorgan Chase", "date": "2025-01-10", "statement": "I'm still not a fan of Bitcoin, but our clients want exposure and we'll provide it.", "impact": "NEUTRAL", "category": "CEO"},
    {"person": "Nayib Bukele", "title": "President of El Salvador", "date": "2025-02-15", "statement": "El Salvador's Bitcoin strategy has generated over $300M in unrealized profits.", "impact": "BULLISH", "category": "Government"},
    {"person": "Javier Milei", "title": "President of Argentina", "date": "2025-01-15", "statement": "Central banking is a scam. Bitcoin represents monetary freedom.", "impact": "BULLISH", "category": "Government"},
]


def get_all_regulatory_items():
    return REGULATORY_ITEMS


def get_all_statements():
    return sorted(NOTABLE_STATEMENTS, key=lambda x: x["date"], reverse=True)


def get_by_category(category):
    return [r for r in REGULATORY_ITEMS if r["category"] == category]


def get_by_status(status_color):
    return [r for r in REGULATORY_ITEMS if r["status_color"] == status_color]


def get_statements_by_category(category):
    return sorted([s for s in NOTABLE_STATEMENTS if s["category"] == category], key=lambda x: x["date"], reverse=True)


def get_bullish_items():
    return [r for r in REGULATORY_ITEMS if "BULLISH" in r.get("btc_impact", "")]


def get_summary_stats():
    """Get summary statistics from database."""
    all_items = get_all_items_combined()
    all_statements = get_all_statements_combined()

    categories = list(set(r.get("category", "Global") for r in all_items))

    bullish_statements = len([s for s in all_statements if "BULLISH" in s.get("impact", "")])
    bearish_statements = len([s for s in all_statements if "BEARISH" in s.get("impact", "")])
    auto_reg = len([r for r in all_items if r.get("auto_detected")])
    auto_stmt = len([s for s in all_statements if s.get("auto_detected")])

    return {
        "total_items": len(all_items),
        "us_federal": len([r for r in all_items if r.get("category") == "US Federal"]),
        "us_state": len([r for r in all_items if r.get("category") == "US State"]),
        "europe": len([r for r in all_items if r.get("category") == "Europe"]),
        "asia_pacific": len([r for r in all_items if r.get("category") == "Asia-Pacific"]),
        "latin_america": len([r for r in all_items if r.get("category") == "Latin America"]),
        "middle_east_africa": len([r for r in all_items if r.get("category") == "Middle East & Africa"]),
        "global": len([r for r in all_items if r.get("category") == "Global"]),
        "regions_tracked": len(categories),
        "active_passed": len([r for r in all_items if r.get("status_color") == "green"]),
        "pending": len([r for r in all_items if r.get("status_color") == "yellow"]),
        "failed": len([r for r in all_items if r.get("status_color") == "red"]),
        "bullish": len([r for r in all_items if "BULLISH" in r.get("btc_impact", "")]),
        "total_statements": len(all_statements),
        "bullish_statements": bullish_statements,
        "bearish_statements": bearish_statements,
        "auto_detected_reg": auto_reg,
        "auto_detected_stmt": auto_stmt,
    }


def format_regulatory_briefing():
    """Format a regulatory summary for email/Telegram."""
    stats = get_summary_stats()
    lines = [
        "🏛️ GLOBAL REGULATORY TRACKER\n",
        f"Tracking {stats['total_items']} regulatory items across {stats['regions_tracked']} regions",
        f"  US Federal: {stats['us_federal']} | US State: {stats['us_state']}",
        f"  Europe: {stats['europe']} | Asia-Pacific: {stats['asia_pacific']}",
        f"  Latin America: {stats['latin_america']} | Middle East & Africa: {stats['middle_east_africa']}",
        f"  ✅ Active/Passed: {stats['active_passed']}",
        f"  🟡 Pending: {stats['pending']}",
        f"  📈 Bullish for BTC: {stats['bullish']}",
        f"\n📣 Notable Statements: {stats['total_statements']}",
        f"  📈 Bullish: {stats['bullish_statements']} | 📉 Bearish: {stats['bearish_statements']}",
        "\n---", "Treasury Signal Intelligence", "Global Regulatory Tracker™",
    ]
    return "\n".join(lines)


def get_all_items_combined():
    """
    Get all regulatory items from database.
    Database is the single source of truth.
    Hardcoded data is ONLY used if DB is completely empty (first run before seeding).
    """
    try:
        from regulatory_scanner import get_all_regulatory_from_db
        db_items = get_all_regulatory_from_db()

        if not db_items:
            logger.warning("Regulatory DB is empty — run 'python seed_database.py' to populate. Using hardcoded fallback.")
            return REGULATORY_ITEMS

        all_items = []
        for item in db_items:
            all_items.append({
                "id": item.get("item_id", ""), "title": item.get("title", ""),
                "category": item.get("category", "Global"), "type": item.get("type", "News"),
                "status": item.get("status", "Reported"), "status_color": item.get("status_color", "yellow"),
                "date_introduced": item.get("date_updated", ""), "date_updated": item.get("date_updated", ""),
                "sponsors": "", "summary": item.get("summary", ""),
                "impact": item.get("impact", ""), "btc_impact": item.get("btc_impact", "NEUTRAL"),
                "auto_detected": item.get("auto_detected", False),
            })
        all_items.sort(key=lambda x: x.get("date_updated", ""), reverse=True)
        return all_items
    except Exception as e:
        logger.warning(f"DB regulatory fetch failed — run 'python seed_database.py'. Fallback: {e}")
        return REGULATORY_ITEMS


def get_all_statements_combined():
    """
    Get all statements from database.
    Database is the single source of truth.
    Hardcoded data is ONLY used if DB is completely empty (first run before seeding).
    """
    try:
        from regulatory_scanner import get_all_statements_from_db
        db_statements = get_all_statements_from_db()

        if not db_statements:
            logger.warning("Statements DB is empty — run 'python seed_database.py' to populate. Using hardcoded fallback.")
            return NOTABLE_STATEMENTS

        all_statements = []
        for s in db_statements:
            all_statements.append({
                "person": s.get("person", ""), "title": s.get("title", ""),
                "date": s.get("date", ""), "statement": s.get("statement", ""),
                "impact": s.get("impact", "NEUTRAL"), "category": s.get("category", ""),
                "auto_detected": s.get("auto_detected", False),
            })
        all_statements.sort(key=lambda x: x.get("date", ""), reverse=True)
        return all_statements
    except Exception as e:
        logger.warning(f"DB statements fetch failed — run 'python seed_database.py'. Fallback: {e}")
        return NOTABLE_STATEMENTS


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Global Regulatory Tracker v2.0 — testing...")
    stats = get_summary_stats()
    logger.info(f"Total items: {stats['total_items']} | Regions: {stats['regions_tracked']} | Statements: {stats['total_statements']}")
    print(format_regulatory_briefing())
    logger.info("Regulatory Tracker test complete")
