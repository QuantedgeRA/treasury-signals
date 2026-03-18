"""
regulatory_tracker.py
---------------------
Government & Regulatory Bitcoin Tracker

Tracks major legislative and regulatory developments
affecting Bitcoin and corporate treasury adoption worldwide.

Categories:
- US Federal legislation (GENIUS Act, CLARITY Act, etc.)
- US State-level Bitcoin reserve bills
- Global government Bitcoin adoption
- Regulatory actions (SEC, CFTC, etc.)

This is a unique differentiator — no competitor tracks
regulatory moves alongside treasury purchase signals.
"""

from datetime import datetime


# ============================================
# REGULATORY DATABASE
# Updated as of March 2026
# ============================================

REGULATORY_ITEMS = [
    # US FEDERAL LEGISLATION
    {
        "id": "genius-act",
        "title": "GENIUS Act (Guiding and Establishing National Innovation for US Stablecoins)",
        "category": "US Federal",
        "type": "Legislation",
        "status": "Passed Senate",
        "status_color": "green",
        "date_introduced": "2025-02-04",
        "date_updated": "2025-05-20",
        "sponsors": "Sen. Bill Hagerty (R-TN), Sen. Kirsten Gillibrand (D-NY)",
        "summary": "Establishes a regulatory framework for stablecoins in the US. Requires issuers to maintain 1:1 reserves in cash, T-bills, or insured deposits. Passed Senate with bipartisan support.",
        "impact": "HIGH — Legitimizes crypto infrastructure. Stablecoin clarity benefits Bitcoin on/off ramps and corporate treasury management.",
        "btc_impact": "BULLISH",
        "url": "",
    },
    {
        "id": "clarity-act",
        "title": "CLARITY Act (Crypto Legal Architecture for Regulatory Innovation and Transparency)",
        "category": "US Federal",
        "type": "Legislation",
        "status": "In Committee",
        "status_color": "yellow",
        "date_introduced": "2025-03-01",
        "date_updated": "2025-03-15",
        "sponsors": "Rep. French Hill (R-AR), Rep. Maxine Waters (D-CA)",
        "summary": "Defines which digital assets are securities vs. commodities. Would give CFTC primary oversight of Bitcoin. Aims to end SEC vs CFTC jurisdiction battles.",
        "impact": "VERY HIGH — Would definitively classify Bitcoin as a commodity, removing SEC enforcement uncertainty. Major catalyst for institutional adoption.",
        "btc_impact": "VERY BULLISH",
        "url": "",
    },
    {
        "id": "bitcoin-act-2025",
        "title": "BITCOIN Act (Boosting Innovation, Technology, and Competitiveness through Optimized Investment Nationwide)",
        "category": "US Federal",
        "type": "Legislation",
        "status": "Introduced",
        "status_color": "yellow",
        "date_introduced": "2025-03-11",
        "date_updated": "2025-03-11",
        "sponsors": "Sen. Cynthia Lummis (R-WY)",
        "summary": "Proposes the US government acquire up to 1 million BTC over 5 years as a strategic reserve asset, funded by revaluing Federal Reserve gold certificates.",
        "impact": "EXTREME — If passed, would be the largest single Bitcoin purchase in history. Would establish BTC as a US strategic reserve asset alongside gold.",
        "btc_impact": "EXTREMELY BULLISH",
        "url": "",
    },
    {
        "id": "us-strategic-btc-reserve",
        "title": "US Strategic Bitcoin Reserve (Executive Order)",
        "category": "US Federal",
        "type": "Executive Order",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2025-03-06",
        "date_updated": "2025-03-06",
        "sponsors": "President Trump",
        "summary": "Executive order establishing a Strategic Bitcoin Reserve using BTC seized in criminal/civil forfeiture proceedings. Directs Treasury and Commerce to evaluate budget-neutral strategies to acquire additional BTC.",
        "impact": "HIGH — US government officially treats Bitcoin as a strategic reserve asset. Signals long-term government support.",
        "btc_impact": "BULLISH",
        "url": "",
    },
    
    # US STATE-LEVEL
    {
        "id": "texas-btc-reserve",
        "title": "Texas Strategic Bitcoin Reserve (SB 778)",
        "category": "US State",
        "type": "Legislation",
        "status": "Passed Senate",
        "status_color": "green",
        "date_introduced": "2025-01-15",
        "date_updated": "2025-03-12",
        "sponsors": "Sen. Charles Schwertner (R)",
        "summary": "Allows Texas Comptroller to invest state funds in Bitcoin. Would make Texas the first state with an official BTC reserve.",
        "impact": "HIGH — If Texas leads, other states will follow. Creates a domino effect of state-level Bitcoin adoption.",
        "btc_impact": "BULLISH",
        "url": "",
    },
    {
        "id": "arizona-btc-reserve",
        "title": "Arizona Bitcoin Reserve Act (SB 1025)",
        "category": "US State",
        "type": "Legislation",
        "status": "Passed Legislature",
        "status_color": "green",
        "date_introduced": "2025-01-01",
        "date_updated": "2025-03-10",
        "sponsors": "Sen. Wendy Rogers (R)",
        "summary": "Allows Arizona to allocate up to 10% of state treasury and pension funds to Bitcoin and digital assets.",
        "impact": "MEDIUM — Sets precedent for state pension fund BTC allocation.",
        "btc_impact": "BULLISH",
        "url": "",
    },
    {
        "id": "new-hampshire-btc",
        "title": "New Hampshire Bitcoin Reserve (HB 302)",
        "category": "US State",
        "type": "Legislation",
        "status": "Signed into Law",
        "status_color": "green",
        "date_introduced": "2025-01-08",
        "date_updated": "2025-05-06",
        "sponsors": "",
        "summary": "Authorizes the state treasurer to invest up to 5% of certain state funds in Bitcoin and precious metals. First state to sign a BTC reserve bill into law.",
        "impact": "HIGH — First state to officially adopt BTC reserve. Historic precedent.",
        "btc_impact": "BULLISH",
        "url": "",
    },
    {
        "id": "oklahoma-btc",
        "title": "Oklahoma Strategic Bitcoin Reserve (HB 1203)",
        "category": "US State",
        "type": "Legislation",
        "status": "Failed in Committee",
        "status_color": "red",
        "date_introduced": "2025-01-01",
        "date_updated": "2025-02-28",
        "sponsors": "",
        "summary": "Proposed allocating state funds to Bitcoin. Failed to advance out of committee.",
        "impact": "LOW — Failed, but indicates growing state-level interest.",
        "btc_impact": "NEUTRAL",
        "url": "",
    },
    
    # GLOBAL
    {
        "id": "el-salvador-btc",
        "title": "El Salvador Bitcoin Legal Tender",
        "category": "Global",
        "type": "Law",
        "status": "Active (Modified)",
        "status_color": "green",
        "date_introduced": "2021-09-07",
        "date_updated": "2025-02-01",
        "sponsors": "President Nayib Bukele",
        "summary": "Bitcoin is legal tender in El Salvador. Government holds ~6,000+ BTC. Modified terms with IMF to make merchant acceptance voluntary rather than mandatory.",
        "impact": "MEDIUM — First nation-state to adopt BTC as legal tender. Proof of concept for other nations.",
        "btc_impact": "BULLISH",
        "url": "",
    },
    {
        "id": "eu-mica",
        "title": "EU MiCA Regulation (Markets in Crypto-Assets)",
        "category": "Global",
        "type": "Regulation",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2023-06-29",
        "date_updated": "2025-01-01",
        "sponsors": "European Commission",
        "summary": "Comprehensive crypto regulatory framework for the EU. Requires licensing for crypto service providers. Full implementation effective Jan 2025.",
        "impact": "HIGH — Provides regulatory clarity for European institutional Bitcoin adoption. Removes uncertainty for EU-based treasury companies.",
        "btc_impact": "BULLISH",
        "url": "",
    },
    {
        "id": "japan-crypto-reform",
        "title": "Japan Crypto Tax Reform Proposal",
        "category": "Global",
        "type": "Legislation",
        "status": "Under Review",
        "status_color": "yellow",
        "date_introduced": "2025-01-01",
        "date_updated": "2025-03-01",
        "sponsors": "Japan Financial Services Agency",
        "summary": "Proposal to reclassify crypto as financial assets rather than miscellaneous income, reducing tax rate from up to 55% to 20%. Would make corporate BTC holdings much more tax-efficient.",
        "impact": "HIGH — Japan has a large crypto market. Tax reform would accelerate corporate adoption (see: Metaplanet).",
        "btc_impact": "BULLISH",
        "url": "",
    },
    {
        "id": "brazil-btc-reserve",
        "title": "Brazil Strategic Bitcoin Reserve Proposal",
        "category": "Global",
        "type": "Legislation",
        "status": "Introduced",
        "status_color": "yellow",
        "date_introduced": "2025-01-01",
        "date_updated": "2025-02-15",
        "sponsors": "Deputy Eros Biondini",
        "summary": "Proposes Brazil establish a 'Sovereign Strategic Bitcoin Reserve' with up to 5% of international reserves allocated to Bitcoin.",
        "impact": "MEDIUM — Major emerging economy considering BTC reserves.",
        "btc_impact": "BULLISH",
        "url": "",
    },
    {
        "id": "czech-btc-reserve",
        "title": "Czech National Bank Bitcoin Reserve Proposal",
        "category": "Global",
        "type": "Policy",
        "status": "Under Review",
        "status_color": "yellow",
        "date_introduced": "2025-01-01",
        "date_updated": "2025-02-01",
        "sponsors": "CNB Governor Ales Michl",
        "summary": "Czech National Bank governor proposed allocating up to 5% of reserves to Bitcoin. Would be first European central bank to hold BTC.",
        "impact": "HIGH — European central bank considering BTC. If adopted, could trigger other central banks to follow.",
        "btc_impact": "VERY BULLISH",
        "url": "",
    },
]


def get_all_regulatory_items():
    """Get all regulatory items."""
    return REGULATORY_ITEMS


def get_by_category(category):
    """Get items filtered by category (US Federal, US State, Global)."""
    return [r for r in REGULATORY_ITEMS if r["category"] == category]


def get_by_status(status_color):
    """Get items by status color (green=active/passed, yellow=pending, red=failed)."""
    return [r for r in REGULATORY_ITEMS if r["status_color"] == status_color]


def get_bullish_items():
    """Get all items with bullish BTC impact."""
    return [r for r in REGULATORY_ITEMS if "BULLISH" in r.get("btc_impact", "")]


def get_summary_stats():
    """Get summary statistics of regulatory landscape."""
    all_items = REGULATORY_ITEMS
    
    return {
        "total_items": len(all_items),
        "us_federal": len([r for r in all_items if r["category"] == "US Federal"]),
        "us_state": len([r for r in all_items if r["category"] == "US State"]),
        "global": len([r for r in all_items if r["category"] == "Global"]),
        "active_passed": len([r for r in all_items if r["status_color"] == "green"]),
        "pending": len([r for r in all_items if r["status_color"] == "yellow"]),
        "failed": len([r for r in all_items if r["status_color"] == "red"]),
        "bullish": len([r for r in all_items if "BULLISH" in r.get("btc_impact", "")]),
    }


def format_regulatory_briefing():
    """Format a regulatory summary for email/Telegram."""
    stats = get_summary_stats()
    active = get_by_status("green")
    pending = get_by_status("yellow")
    
    lines = []
    lines.append("🏛️ GOVERNMENT & REGULATORY TRACKER\n")
    lines.append(f"Tracking {stats['total_items']} regulatory items")
    lines.append(f"  US Federal: {stats['us_federal']} | US State: {stats['us_state']} | Global: {stats['global']}")
    lines.append(f"  ✅ Active/Passed: {stats['active_passed']}")
    lines.append(f"  🟡 Pending: {stats['pending']}")
    lines.append(f"  ❌ Failed: {stats['failed']}")
    lines.append(f"  📈 Bullish for BTC: {stats['bullish']}")
    lines.append("")
    
    lines.append("✅ ACTIVE / PASSED:")
    for r in active:
        lines.append(f"  • {r['title']}")
        lines.append(f"    Status: {r['status']} | Impact: {r['btc_impact']}")
    lines.append("")
    
    lines.append("🟡 PENDING / IN PROGRESS:")
    for r in pending:
        lines.append(f"  • {r['title']}")
        lines.append(f"    Status: {r['status']} | Impact: {r['btc_impact']}")
    
    lines.append("\n---")
    lines.append("Treasury Signal Intelligence")
    lines.append("Government & Regulatory Tracker™")
    
    return "\n".join(lines)


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    print("\nGovernment & Regulatory Bitcoin Tracker\n")
    print("=" * 70)
    
    stats = get_summary_stats()
    print(f"\n  Total items tracked: {stats['total_items']}")
    print(f"  US Federal: {stats['us_federal']}")
    print(f"  US State: {stats['us_state']}")
    print(f"  Global: {stats['global']}")
    print(f"  Active/Passed: {stats['active_passed']}")
    print(f"  Pending: {stats['pending']}")
    print(f"  Bullish for BTC: {stats['bullish']}")
    
    print("\n\nTelegram/Email Format:\n")
    print(format_regulatory_briefing())
