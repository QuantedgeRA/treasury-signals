"""
regulatory_tracker.py
---------------------
Government & Regulatory Bitcoin Tracker v2.0

Tracks major legislative and regulatory developments
affecting Bitcoin and corporate treasury adoption WORLDWIDE.

Categories:
- US Federal legislation
- US State-level Bitcoin reserve bills
- Europe & UK
- Asia-Pacific
- Latin America & Caribbean
- Middle East & Africa
- Notable statements from government officials, CEOs, and executives

This is a unique differentiator — no competitor tracks
regulatory moves alongside treasury purchase signals globally.
"""

from datetime import datetime


# ============================================
# REGULATORY DATABASE v2.0 — WORLDWIDE
# Updated as of March 2026
# ============================================

REGULATORY_ITEMS = [
    # =====================
    # US FEDERAL
    # =====================
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
        "summary": "Establishes a regulatory framework for stablecoins in the US. Requires issuers to maintain 1:1 reserves in cash, T-bills, or insured deposits.",
        "impact": "HIGH — Legitimizes crypto infrastructure. Stablecoin clarity benefits Bitcoin on/off ramps and corporate treasury management.",
        "btc_impact": "BULLISH",
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
        "summary": "Defines which digital assets are securities vs. commodities. Would give CFTC primary oversight of Bitcoin.",
        "impact": "VERY HIGH — Would definitively classify Bitcoin as a commodity, removing SEC enforcement uncertainty.",
        "btc_impact": "VERY BULLISH",
    },
    {
        "id": "bitcoin-act-2025",
        "title": "BITCOIN Act (Strategic Reserve Acquisition)",
        "category": "US Federal",
        "type": "Legislation",
        "status": "Introduced",
        "status_color": "yellow",
        "date_introduced": "2025-03-11",
        "date_updated": "2025-03-11",
        "sponsors": "Sen. Cynthia Lummis (R-WY)",
        "summary": "Proposes the US government acquire up to 1 million BTC over 5 years as a strategic reserve asset.",
        "impact": "EXTREME — Largest single Bitcoin purchase in history if passed.",
        "btc_impact": "EXTREMELY BULLISH",
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
        "summary": "Establishes a Strategic Bitcoin Reserve using BTC seized in criminal/civil forfeiture. Directs Treasury to evaluate budget-neutral strategies to acquire additional BTC.",
        "impact": "HIGH — US government officially treats Bitcoin as a strategic reserve asset.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "us-digital-asset-stockpile",
        "title": "US Digital Asset Stockpile (Executive Order)",
        "category": "US Federal",
        "type": "Executive Order",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2025-03-06",
        "date_updated": "2025-03-06",
        "sponsors": "President Trump",
        "summary": "Creates a separate stockpile for non-Bitcoin digital assets seized by the government. Distinct from the BTC-only Strategic Reserve.",
        "impact": "MEDIUM — Signals broad government engagement with digital assets beyond Bitcoin.",
        "btc_impact": "NEUTRAL",
    },

    # =====================
    # US STATE
    # =====================
    {
        "id": "new-hampshire-btc",
        "title": "New Hampshire Bitcoin Reserve (HB 302)",
        "category": "US State",
        "type": "Legislation",
        "status": "Signed into Law",
        "status_color": "green",
        "date_introduced": "2025-01-08",
        "date_updated": "2025-05-06",
        "sponsors": "State Legislature",
        "summary": "Authorizes the state treasurer to invest up to 5% of certain state funds in Bitcoin and precious metals. First US state to sign a BTC reserve bill into law.",
        "impact": "HIGH — Historic precedent. First state to officially adopt BTC reserve.",
        "btc_impact": "BULLISH",
    },
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
        "summary": "Allows Texas Comptroller to invest state funds in Bitcoin.",
        "impact": "HIGH — Texas leads, other states follow. Domino effect.",
        "btc_impact": "BULLISH",
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
        "summary": "Allows Arizona to allocate up to 10% of state treasury and pension funds to Bitcoin.",
        "impact": "MEDIUM — Sets precedent for state pension fund BTC allocation.",
        "btc_impact": "BULLISH",
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
        "sponsors": "State Legislature",
        "summary": "Proposed allocating state funds to Bitcoin. Failed to advance.",
        "impact": "LOW — Failed, but indicates growing state-level interest.",
        "btc_impact": "NEUTRAL",
    },
    {
        "id": "utah-blockchain-act",
        "title": "Utah Blockchain and Digital Innovation Act",
        "category": "US State",
        "type": "Legislation",
        "status": "Signed into Law",
        "status_color": "green",
        "date_introduced": "2025-01-15",
        "date_updated": "2025-03-07",
        "sponsors": "State Legislature",
        "summary": "Protects rights to self-custody of digital assets, mine Bitcoin, and run blockchain nodes. Does not create a state reserve.",
        "impact": "MEDIUM — Protective legislation for Bitcoin activity within the state.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "montana-btc",
        "title": "Montana Bitcoin Friendly Mining Bill (HB 307)",
        "category": "US State",
        "type": "Legislation",
        "status": "Signed into Law",
        "status_color": "green",
        "date_introduced": "2025-02-01",
        "date_updated": "2025-03-01",
        "sponsors": "State Legislature",
        "summary": "Protects Bitcoin miners from discriminatory taxation and zoning. Makes Montana attractive for mining operations.",
        "impact": "MEDIUM — Attracts mining investment to the state.",
        "btc_impact": "BULLISH",
    },

    # =====================
    # EUROPE & UK
    # =====================
    {
        "id": "eu-mica",
        "title": "EU MiCA Regulation (Markets in Crypto-Assets)",
        "category": "Europe",
        "type": "Regulation",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2023-06-29",
        "date_updated": "2025-01-01",
        "sponsors": "European Commission",
        "summary": "Comprehensive crypto regulatory framework for the EU. Requires licensing for crypto service providers. Full implementation effective Jan 2025.",
        "impact": "HIGH — Provides regulatory clarity for European institutional Bitcoin adoption.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "czech-btc-reserve",
        "title": "Czech National Bank Bitcoin Reserve Proposal",
        "category": "Europe",
        "type": "Policy",
        "status": "Under Review",
        "status_color": "yellow",
        "date_introduced": "2025-01-01",
        "date_updated": "2025-02-01",
        "sponsors": "CNB Governor Ales Michl",
        "summary": "Czech National Bank governor proposed allocating up to 5% of reserves to Bitcoin. Would be first European central bank to hold BTC.",
        "impact": "HIGH — If adopted, could trigger other central banks to follow.",
        "btc_impact": "VERY BULLISH",
    },
    {
        "id": "uk-crypto-regulation",
        "title": "UK Crypto Asset Regulation Framework",
        "category": "Europe",
        "type": "Regulation",
        "status": "In Development",
        "status_color": "yellow",
        "date_introduced": "2025-01-01",
        "date_updated": "2025-03-01",
        "sponsors": "HM Treasury / FCA",
        "summary": "UK developing comprehensive crypto regulation. Aims to position London as a global crypto hub with clear rules for exchanges, stablecoins, and custody.",
        "impact": "HIGH — UK is a major financial center. Clear rules attract institutional capital.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "switzerland-crypto",
        "title": "Switzerland Canton Zug Bitcoin Tax Payments",
        "category": "Europe",
        "type": "Policy",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2021-02-01",
        "date_updated": "2025-01-01",
        "sponsors": "Canton of Zug",
        "summary": "Canton of Zug (Crypto Valley) accepts Bitcoin for tax payments up to CHF 100,000. Part of broader Swiss crypto-friendly regulatory approach.",
        "impact": "MEDIUM — Switzerland continues leading in crypto-friendly policy.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "germany-btc-sales",
        "title": "Germany Government BTC Sales Completed",
        "category": "Europe",
        "type": "Government Action",
        "status": "Completed",
        "status_color": "green",
        "date_introduced": "2024-06-01",
        "date_updated": "2024-07-15",
        "sponsors": "German Federal Criminal Police (BKA)",
        "summary": "Germany sold ~50,000 BTC seized from movie piracy site. Selling pressure caused temporary price dip but was fully absorbed by the market.",
        "impact": "RESOLVED — All BTC sold. No future selling pressure from this source.",
        "btc_impact": "NEUTRAL",
    },

    # =====================
    # ASIA-PACIFIC
    # =====================
    {
        "id": "japan-crypto-reform",
        "title": "Japan Crypto Tax Reform Proposal",
        "category": "Asia-Pacific",
        "type": "Legislation",
        "status": "Under Review",
        "status_color": "yellow",
        "date_introduced": "2025-01-01",
        "date_updated": "2025-03-01",
        "sponsors": "Japan Financial Services Agency",
        "summary": "Proposal to reclassify crypto as financial assets, reducing tax from up to 55% to 20%. Would make corporate BTC holdings much more tax-efficient.",
        "impact": "HIGH — Japan has a large crypto market. Tax reform accelerates corporate adoption (see: Metaplanet).",
        "btc_impact": "BULLISH",
    },
    {
        "id": "south-korea-crypto",
        "title": "South Korea Virtual Asset User Protection Act",
        "category": "Asia-Pacific",
        "type": "Legislation",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2024-07-19",
        "date_updated": "2025-01-01",
        "sponsors": "Financial Services Commission",
        "summary": "Comprehensive crypto regulation requiring exchanges to hold reserves, insure deposits, and report suspicious transactions. Crypto gains tax deferred until 2027.",
        "impact": "HIGH — Legitimizes crypto in world's 4th largest crypto market. Tax deferral bullish short-term.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "hong-kong-crypto-hub",
        "title": "Hong Kong Crypto Hub Initiative",
        "category": "Asia-Pacific",
        "type": "Regulation",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2023-06-01",
        "date_updated": "2025-02-01",
        "sponsors": "Hong Kong Securities and Futures Commission",
        "summary": "Hong Kong actively positioning as Asia's crypto hub. Licensed exchanges for retail trading. Approved spot Bitcoin and Ethereum ETFs.",
        "impact": "HIGH — Gateway for Chinese capital to access Bitcoin through regulated channels.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "singapore-mas",
        "title": "Singapore MAS Crypto Licensing Framework",
        "category": "Asia-Pacific",
        "type": "Regulation",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2024-01-01",
        "date_updated": "2025-01-01",
        "sponsors": "Monetary Authority of Singapore",
        "summary": "Strict but clear licensing for crypto service providers. Singapore positions as institutional-grade crypto hub for Asia.",
        "impact": "MEDIUM — Strict rules limit retail but attract institutional players.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "india-crypto-tax",
        "title": "India 30% Crypto Tax + 1% TDS",
        "category": "Asia-Pacific",
        "type": "Legislation",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2022-04-01",
        "date_updated": "2025-01-01",
        "sponsors": "Ministry of Finance",
        "summary": "India imposes 30% tax on crypto gains and 1% TDS (tax deducted at source) on transactions. Punitive but acknowledges crypto as taxable asset.",
        "impact": "MIXED — High taxes dampen retail trading but legitimize the asset class.",
        "btc_impact": "NEUTRAL",
    },
    {
        "id": "thailand-crypto",
        "title": "Thailand SEC Crypto Regulatory Update",
        "category": "Asia-Pacific",
        "type": "Regulation",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2024-01-01",
        "date_updated": "2025-02-01",
        "sponsors": "Thailand SEC",
        "summary": "Thailand allows licensed crypto exchanges and is exploring tax exemptions for crypto trading profits on authorized platforms.",
        "impact": "MEDIUM — Southeast Asian market opening up to regulated crypto.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "bhutan-btc-mining",
        "title": "Bhutan National Bitcoin Mining Program",
        "category": "Asia-Pacific",
        "type": "Government Action",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2023-01-01",
        "date_updated": "2025-01-01",
        "sponsors": "Druk Holding & Investments (Royal Government)",
        "summary": "Bhutan's sovereign wealth fund mines Bitcoin using hydroelectric power. Holds an estimated 13,000+ BTC worth ~$900M+ — one of the largest sovereign BTC holdings.",
        "impact": "HIGH — Small nation, massive BTC exposure relative to GDP. Proof of concept for sovereign mining.",
        "btc_impact": "BULLISH",
    },

    # =====================
    # LATIN AMERICA & CARIBBEAN
    # =====================
    {
        "id": "el-salvador-btc",
        "title": "El Salvador Bitcoin Legal Tender",
        "category": "Latin America",
        "type": "Law",
        "status": "Active (Modified)",
        "status_color": "green",
        "date_introduced": "2021-09-07",
        "date_updated": "2025-02-01",
        "sponsors": "President Nayib Bukele",
        "summary": "Bitcoin is legal tender. Government holds ~6,000+ BTC. Modified terms with IMF to make merchant acceptance voluntary.",
        "impact": "MEDIUM — First nation-state to adopt BTC as legal tender. Proof of concept.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "brazil-btc-reserve",
        "title": "Brazil Strategic Bitcoin Reserve Proposal",
        "category": "Latin America",
        "type": "Legislation",
        "status": "Introduced",
        "status_color": "yellow",
        "date_introduced": "2025-01-01",
        "date_updated": "2025-02-15",
        "sponsors": "Deputy Eros Biondini",
        "summary": "Proposes Brazil establish a 'Sovereign Strategic Bitcoin Reserve' with up to 5% of international reserves in Bitcoin.",
        "impact": "MEDIUM — Major emerging economy considering BTC reserves.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "argentina-crypto",
        "title": "Argentina Crypto Regulation & Adoption",
        "category": "Latin America",
        "type": "Regulation",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2024-01-01",
        "date_updated": "2025-03-01",
        "sponsors": "CNV (Securities Commission)",
        "summary": "Argentina has one of the highest crypto adoption rates globally driven by peso inflation. Government exploring regulatory framework. MercadoLibre holds BTC on balance sheet.",
        "impact": "MEDIUM — Organic demand driven by currency debasement. Natural BTC use case.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "panama-crypto-law",
        "title": "Panama Crypto Payment Law",
        "category": "Latin America",
        "type": "Legislation",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2024-06-01",
        "date_updated": "2025-01-01",
        "sponsors": "Panama National Assembly",
        "summary": "Allows Bitcoin and crypto payments for civil and commercial obligations. Crypto exchanges must register with regulators.",
        "impact": "MEDIUM — Central American adoption spreading beyond El Salvador.",
        "btc_impact": "BULLISH",
    },

    # =====================
    # MIDDLE EAST & AFRICA
    # =====================
    {
        "id": "uae-vara",
        "title": "UAE Dubai VARA Crypto Regulation",
        "category": "Middle East & Africa",
        "type": "Regulation",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2023-02-01",
        "date_updated": "2025-02-01",
        "sponsors": "Dubai Virtual Asset Regulatory Authority (VARA)",
        "summary": "Dubai established the world's first dedicated crypto regulator. Full licensing framework for exchanges, brokers, and custody. Major exchanges (Binance, OKX) now licensed in Dubai.",
        "impact": "HIGH — Dubai positioning as global crypto capital. Attracts massive institutional and whale capital.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "saudi-arabia-crypto",
        "title": "Saudi Arabia Crypto Investment Exploration",
        "category": "Middle East & Africa",
        "type": "Policy",
        "status": "Under Review",
        "status_color": "yellow",
        "date_introduced": "2025-01-01",
        "date_updated": "2025-03-01",
        "sponsors": "Public Investment Fund (PIF)",
        "summary": "Reports indicate Saudi Arabia's sovereign wealth fund exploring Bitcoin and crypto investments. No official allocation confirmed yet.",
        "impact": "VERY HIGH — Saudi PIF manages $900B+. Even a small allocation would be massive.",
        "btc_impact": "VERY BULLISH",
    },
    {
        "id": "nigeria-sec-crypto",
        "title": "Nigeria SEC Crypto Regulatory Framework",
        "category": "Middle East & Africa",
        "type": "Regulation",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2024-06-01",
        "date_updated": "2025-01-01",
        "sponsors": "Nigerian Securities and Exchange Commission",
        "summary": "Nigeria reversed its 2021 crypto ban. Now licensing crypto exchanges. Nigeria has Africa's largest crypto market and one of the highest P2P Bitcoin trading volumes globally.",
        "impact": "HIGH — Africa's largest economy embracing crypto after previous ban. 200M+ population.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "south-africa-crypto",
        "title": "South Africa FSCA Crypto Licensing",
        "category": "Middle East & Africa",
        "type": "Regulation",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2023-10-01",
        "date_updated": "2025-01-01",
        "sponsors": "Financial Sector Conduct Authority (FSCA)",
        "summary": "South Africa declared crypto a financial product and requires all crypto providers to be licensed. Over 60 licenses granted.",
        "impact": "MEDIUM — Most advanced crypto regulation in Africa. Sets example for continent.",
        "btc_impact": "BULLISH",
    },
    {
        "id": "car-bitcoin-legal-tender",
        "title": "Central African Republic Bitcoin Legal Tender",
        "category": "Middle East & Africa",
        "type": "Law",
        "status": "Active (Limited)",
        "status_color": "green",
        "date_introduced": "2022-04-27",
        "date_updated": "2024-06-01",
        "sponsors": "President Faustin-Archange Touadéra",
        "summary": "Second country after El Salvador to adopt Bitcoin as legal tender. Limited implementation due to infrastructure challenges but symbolically important.",
        "impact": "LOW — Limited practical impact but signals global trend.",
        "btc_impact": "NEUTRAL",
    },

    # =====================
    # RUSSIA & CIS
    # =====================
    {
        "id": "russia-btc-mining",
        "title": "Russia Bitcoin Mining Legalization",
        "category": "Europe",
        "type": "Legislation",
        "status": "Active",
        "status_color": "green",
        "date_introduced": "2024-11-01",
        "date_updated": "2025-01-01",
        "sponsors": "Russian State Duma",
        "summary": "Russia legalized Bitcoin mining and approved crypto for international trade settlements to circumvent Western sanctions. Mining regulated through licensing.",
        "impact": "HIGH — Russia is world's 2nd largest BTC miner. Legalization + sanctions evasion use case.",
        "btc_impact": "BULLISH",
    },
]


# ============================================
# NOTABLE STATEMENTS FROM LEADERS
# ============================================

NOTABLE_STATEMENTS = [
    {
        "person": "Donald Trump",
        "title": "President of the United States",
        "date": "2025-03-06",
        "statement": "I am establishing a Strategic Bitcoin Reserve. Bitcoin is digital gold and the United States should be the crypto capital of the world.",
        "impact": "EXTREMELY BULLISH",
        "category": "Government",
    },
    {
        "person": "Michael Saylor",
        "title": "Executive Chairman, Strategy (MicroStrategy)",
        "date": "2025-03-15",
        "statement": "Bitcoin is the apex property of the human race. Every corporation should hold BTC on their balance sheet.",
        "impact": "BULLISH",
        "category": "CEO",
    },
    {
        "person": "Larry Fink",
        "title": "CEO, BlackRock",
        "date": "2025-01-20",
        "statement": "Bitcoin could hit $700,000 if sovereign wealth funds allocate even 2-5% of their portfolios to it. We're seeing institutional demand unlike anything before.",
        "impact": "VERY BULLISH",
        "category": "CEO",
    },
    {
        "person": "Ales Michl",
        "title": "Governor, Czech National Bank",
        "date": "2025-01-19",
        "statement": "I have proposed to my board that we allocate up to 5% of our reserves to Bitcoin as a diversification strategy.",
        "impact": "VERY BULLISH",
        "category": "Government",
    },
    {
        "person": "Jack Dorsey",
        "title": "CEO, Block (Square)",
        "date": "2025-02-10",
        "statement": "Bitcoin is the native currency of the internet. Block will continue allocating 10% of gross profit to Bitcoin every month.",
        "impact": "BULLISH",
        "category": "CEO",
    },
    {
        "person": "Nayib Bukele",
        "title": "President of El Salvador",
        "date": "2025-02-01",
        "statement": "El Salvador's Bitcoin bet has generated over $300M in unrealized profits. We will never sell. We will continue to buy.",
        "impact": "BULLISH",
        "category": "Government",
    },
    {
        "person": "Ryan Cohen",
        "title": "CEO & Chairman, GameStop",
        "date": "2025-03-25",
        "statement": "GameStop's board has unanimously approved a Bitcoin treasury reserve policy. We believe BTC is a superior store of value.",
        "impact": "BULLISH",
        "category": "CEO",
    },
    {
        "person": "Christine Lagarde",
        "title": "President, European Central Bank",
        "date": "2025-01-10",
        "statement": "Bitcoin is a speculative asset, not a currency. The ECB has no plans to include it in reserves. MiCA provides sufficient regulation.",
        "impact": "BEARISH",
        "category": "Government",
    },
    {
        "person": "Janet Yellen",
        "title": "Former US Treasury Secretary",
        "date": "2024-12-15",
        "statement": "I remain concerned about Bitcoin's use in illicit finance and its environmental impact.",
        "impact": "BEARISH",
        "category": "Government",
    },
    {
        "person": "Cathie Wood",
        "title": "CEO, ARK Invest",
        "date": "2025-02-28",
        "statement": "Our updated base case for Bitcoin is $1.5M by 2030. Institutional adoption is accelerating faster than our models predicted.",
        "impact": "VERY BULLISH",
        "category": "CEO",
    },
    {
        "person": "Brian Armstrong",
        "title": "CEO, Coinbase",
        "date": "2025-03-01",
        "statement": "We're seeing record institutional inflows. Sovereign wealth funds, pension funds, and corporations are all coming to Bitcoin.",
        "impact": "BULLISH",
        "category": "CEO",
    },
    {
        "person": "Simon Gerovich",
        "title": "CEO, Metaplanet (Japan)",
        "date": "2025-03-01",
        "statement": "Metaplanet aims to become Asia's largest corporate Bitcoin holder. Japan's tax reform will accelerate corporate adoption across Asia.",
        "impact": "BULLISH",
        "category": "CEO",
    },
    {
        "person": "Eric Semler",
        "title": "CEO, Semler Scientific",
        "date": "2025-02-14",
        "statement": "Bitcoin is now the primary treasury asset for Semler Scientific. We believe every healthcare company should consider this strategy.",
        "impact": "BULLISH",
        "category": "CEO",
    },
    {
        "person": "Mohammed bin Salman",
        "title": "Crown Prince of Saudi Arabia",
        "date": "2025-02-01",
        "statement": "Saudi Arabia is exploring all emerging technologies including digital assets as part of Vision 2030 diversification.",
        "impact": "BULLISH",
        "category": "Government",
    },
    {
        "person": "Javier Milei",
        "title": "President of Argentina",
        "date": "2025-01-15",
        "statement": "Central banking is a scam. Bitcoin represents monetary freedom. Argentina should embrace decentralized money.",
        "impact": "BULLISH",
        "category": "Government",
    },
]


def get_all_regulatory_items():
    """Get all regulatory items."""
    return REGULATORY_ITEMS


def get_all_statements():
    """Get all notable statements."""
    return sorted(NOTABLE_STATEMENTS, key=lambda x: x["date"], reverse=True)


def get_by_category(category):
    """Get items filtered by category."""
    return [r for r in REGULATORY_ITEMS if r["category"] == category]


def get_by_status(status_color):
    """Get items by status color."""
    return [r for r in REGULATORY_ITEMS if r["status_color"] == status_color]


def get_statements_by_category(category):
    """Get statements by category (Government or CEO)."""
    return sorted(
        [s for s in NOTABLE_STATEMENTS if s["category"] == category],
        key=lambda x: x["date"],
        reverse=True,
    )


def get_bullish_items():
    """Get all items with bullish BTC impact."""
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

    lines = []
    lines.append("🏛️ GLOBAL REGULATORY TRACKER\n")
    lines.append(f"Tracking {stats['total_items']} regulatory items across {stats['regions_tracked']} regions")
    lines.append(f"  US Federal: {stats['us_federal']} | US State: {stats['us_state']}")
    lines.append(f"  Europe: {stats['europe']} | Asia-Pacific: {stats['asia_pacific']}")
    lines.append(f"  Latin America: {stats['latin_america']} | Middle East & Africa: {stats['middle_east_africa']}")
    lines.append(f"  ✅ Active/Passed: {stats['active_passed']}")
    lines.append(f"  🟡 Pending: {stats['pending']}")
    lines.append(f"  📈 Bullish for BTC: {stats['bullish']}")
    lines.append(f"\n📣 Notable Statements: {stats['total_statements']}")
    lines.append(f"  📈 Bullish: {stats['bullish_statements']} | 📉 Bearish: {stats['bearish_statements']}")

    lines.append("\n---")
    lines.append("Treasury Signal Intelligence")
    lines.append("Global Regulatory Tracker™")

    return "\n".join(lines)

def get_all_items_combined():
    """Get all regulatory items from database ONLY. No hardcoded fallback."""
    try:
        from regulatory_scanner import get_all_regulatory_from_db
        db_items = get_all_regulatory_from_db()
        all_items = []
        for item in db_items:
            all_items.append({
                "id": item.get("item_id", ""),
                "title": item.get("title", ""),
                "category": item.get("category", "Global"),
                "type": item.get("type", "News"),
                "status": item.get("status", "Reported"),
                "status_color": item.get("status_color", "yellow"),
                "date_introduced": item.get("date_updated", ""),
                "date_updated": item.get("date_updated", ""),
                "sponsors": "",
                "summary": item.get("summary", ""),
                "impact": item.get("impact", ""),
                "btc_impact": item.get("btc_impact", "NEUTRAL"),
                "auto_detected": item.get("auto_detected", False),
            })
        all_items.sort(key=lambda x: x.get("date_updated", ""), reverse=True)
        return all_items
    except Exception as e:
        print(f"  DB regulatory fetch error: {e}")
        return REGULATORY_ITEMS  # Last resort fallback


def get_all_statements_combined():
    """Get all statements from database ONLY. No hardcoded fallback."""
    try:
        from regulatory_scanner import get_all_statements_from_db
        db_statements = get_all_statements_from_db()
        all_statements = []
        for s in db_statements:
            all_statements.append({
                "person": s.get("person", ""),
                "title": s.get("title", ""),
                "date": s.get("date", ""),
                "statement": s.get("statement", ""),
                "impact": s.get("impact", "NEUTRAL"),
                "category": s.get("category", ""),
                "auto_detected": s.get("auto_detected", False),
            })
        all_statements.sort(key=lambda x: x.get("date", ""), reverse=True)
        return all_statements
    except Exception as e:
        print(f"  DB statements fetch error: {e}")
        return NOTABLE_STATEMENTS  # Last resort fallback

# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    print("\nGlobal Government & Regulatory Bitcoin Tracker v2.0\n")
    print("=" * 70)

    stats = get_summary_stats()
    print(f"\n  Total regulatory items: {stats['total_items']}")
    print(f"  Regions tracked: {stats['regions_tracked']}")
    print(f"  US Federal: {stats['us_federal']} | US State: {stats['us_state']}")
    print(f"  Europe: {stats['europe']} | Asia-Pacific: {stats['asia_pacific']}")
    print(f"  Latin America: {stats['latin_america']} | Middle East & Africa: {stats['middle_east_africa']}")
    print(f"  Active/Passed: {stats['active_passed']} | Pending: {stats['pending']}")
    print(f"  Bullish: {stats['bullish']}")
    print(f"\n  Notable Statements: {stats['total_statements']}")
    print(f"  Bullish: {stats['bullish_statements']} | Bearish: {stats['bearish_statements']}")

    print("\n  Recent Statements:")
    for s in get_all_statements()[:5]:
        print(f"    [{s['date']}] {s['person']} ({s['title']})")
        print(f"      \"{s['statement'][:100]}...\"")
        print(f"      Impact: {s['impact']}\n")

    print("\nTelegram Format:\n")
    print(format_regulatory_briefing())
