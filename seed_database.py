"""
seed_database.py — One-Time Database Seeder
---------------------------------------------
Run this ONCE to populate all Supabase tables with seed data.
After seeding, the database is the single source of truth.
Hardcoded data in Python files is NEVER used for display again.

Usage:
    python seed_database.py

This is idempotent — running it multiple times won't create duplicates.
It checks for existing records before inserting.

Tables seeded:
1. regulatory_items       (from regulatory_tracker.REGULATORY_ITEMS)
2. notable_statements     (from regulatory_tracker.NOTABLE_STATEMENTS)
3. confirmed_purchases    (from purchase_tracker.KNOWN_PURCHASES)
4. treasury_companies     (NEW — company metadata for leaderboard)
5. sovereign_holders      (NEW — government BTC holders)
6. edgar_companies        (NEW — SEC EDGAR CIK mappings)
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
# SQL TO CREATE ALL TABLES
# Run this in Supabase SQL Editor BEFORE running this script
# ============================================

SETUP_SQL = """
-- ==========================================
-- Run this ENTIRE block in Supabase SQL Editor
-- ==========================================

-- Regulatory items (legislation, executive orders, etc.)
CREATE TABLE IF NOT EXISTS regulatory_items (
    id BIGSERIAL PRIMARY KEY,
    item_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    category TEXT DEFAULT 'Global',
    type TEXT DEFAULT 'News',
    status TEXT DEFAULT 'Reported',
    status_color TEXT DEFAULT 'yellow',
    date_updated TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    impact TEXT DEFAULT '',
    btc_impact TEXT DEFAULT 'NEUTRAL',
    country TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    auto_detected BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Notable statements from CEOs, politicians, etc.
CREATE TABLE IF NOT EXISTS notable_statements (
    id BIGSERIAL PRIMARY KEY,
    statement_id TEXT UNIQUE NOT NULL,
    person TEXT NOT NULL,
    title TEXT DEFAULT '',
    date TEXT DEFAULT '',
    statement TEXT DEFAULT '',
    impact TEXT DEFAULT 'NEUTRAL',
    category TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    auto_detected BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Confirmed BTC purchases
CREATE TABLE IF NOT EXISTS confirmed_purchases (
    id BIGSERIAL PRIMARY KEY,
    purchase_id TEXT UNIQUE NOT NULL,
    company TEXT NOT NULL,
    ticker TEXT DEFAULT '',
    btc_amount DECIMAL DEFAULT 0,
    usd_amount DECIMAL DEFAULT 0,
    price_per_btc DECIMAL DEFAULT 0,
    filing_date TEXT NOT NULL,
    filing_url TEXT DEFAULT '',
    was_predicted BOOLEAN DEFAULT FALSE,
    prediction_id TEXT DEFAULT NULL,
    prediction_lead_time_hours DECIMAL DEFAULT NULL,
    confirmed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Predictions (for accuracy tracking)
CREATE TABLE IF NOT EXISTS predictions (
    id BIGSERIAL PRIMARY KEY,
    prediction_id TEXT UNIQUE NOT NULL,
    company TEXT NOT NULL,
    ticker TEXT DEFAULT '',
    signal_type TEXT NOT NULL,
    signal_score INTEGER DEFAULT 0,
    signal_details TEXT DEFAULT '',
    predicted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    was_correct BOOLEAN DEFAULT NULL,
    matched_purchase_id TEXT DEFAULT NULL,
    notes TEXT DEFAULT ''
);

-- Leaderboard snapshots (daily)
CREATE TABLE IF NOT EXISTS leaderboard_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date TEXT UNIQUE NOT NULL,
    btc_price DECIMAL DEFAULT 0,
    total_btc BIGINT DEFAULT 0,
    total_value_b DECIMAL DEFAULT 0,
    companies_json JSONB DEFAULT '{}'::jsonb
);

-- Data freshness tracking
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

-- Tweets
CREATE TABLE IF NOT EXISTS tweets (
    id BIGSERIAL PRIMARY KEY,
    tweet_id TEXT UNIQUE NOT NULL,
    author_username TEXT DEFAULT '',
    company TEXT DEFAULT '',
    tweet_text TEXT DEFAULT '',
    tweet_url TEXT DEFAULT '',
    created_at TEXT DEFAULT '',
    like_count INTEGER DEFAULT 0,
    retweet_count INTEGER DEFAULT 0,
    view_count INTEGER DEFAULT 0,
    is_reply BOOLEAN DEFAULT FALSE,
    is_signal BOOLEAN DEFAULT FALSE,
    confidence_score INTEGER DEFAULT 0,
    processed BOOLEAN DEFAULT FALSE,
    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Treasury companies metadata (for smarter leaderboard)
CREATE TABLE IF NOT EXISTS treasury_companies (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT UNIQUE NOT NULL,
    company TEXT NOT NULL,
    btc_holdings INTEGER DEFAULT 0,
    avg_purchase_price DECIMAL DEFAULT 0,
    total_cost_usd DECIMAL DEFAULT 0,
    country TEXT DEFAULT '',
    sector TEXT DEFAULT '',
    is_government BOOLEAN DEFAULT FALSE,
    data_source TEXT DEFAULT 'seed',
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- SEC EDGAR company mappings
CREATE TABLE IF NOT EXISTS edgar_companies (
    id BIGSERIAL PRIMARY KEY,
    cik TEXT UNIQUE NOT NULL,
    company TEXT NOT NULL,
    ticker TEXT NOT NULL,
    priority TEXT DEFAULT 'medium',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Subscribers / Company Profiles
CREATE TABLE IF NOT EXISTS subscribers (
    id BIGSERIAL PRIMARY KEY,
    subscriber_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    role TEXT DEFAULT '',
    company_name TEXT NOT NULL,
    ticker TEXT DEFAULT '',
    sector TEXT DEFAULT '',
    country TEXT DEFAULT '',
    btc_holdings DECIMAL DEFAULT 0,
    avg_purchase_price DECIMAL DEFAULT 0,
    total_invested_usd DECIMAL DEFAULT 0,
    plan TEXT DEFAULT 'pro',
    is_active BOOLEAN DEFAULT TRUE,
    alert_frequency TEXT DEFAULT 'instant',
    email_briefing BOOLEAN DEFAULT TRUE,
    telegram_chat_id TEXT DEFAULT '',
    watchlist_json JSONB DEFAULT '[]'::jsonb,
    password_hash TEXT DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_active TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscribers_email ON subscribers(email);
CREATE INDEX IF NOT EXISTS idx_subscribers_active ON subscribers(is_active);

-- Learned weights (accuracy feedback loop)
CREATE TABLE IF NOT EXISTS learned_weights (
    id BIGSERIAL PRIMARY KEY,
    weight_key TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL,
    original_weight DECIMAL DEFAULT 0,
    learned_adjustment DECIMAL DEFAULT 0,
    effective_weight DECIMAL DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    success_rate DECIMAL DEFAULT 0,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
"""


def seed_regulatory_items():
    """Seed regulatory items from hardcoded data."""
    from regulatory_tracker import REGULATORY_ITEMS
    from regulatory_scanner import generate_item_id

    logger.info("Seeding regulatory items...")
    seeded = 0
    skipped = 0

    for item in REGULATORY_ITEMS:
        item_id = f"seed_{generate_item_id(item['title'])}"
        try:
            existing = supabase.table("regulatory_items").select("item_id").eq("item_id", item_id).execute()
            if existing.data:
                skipped += 1
                continue
            row = {
                "item_id": item_id,
                "title": item["title"],
                "category": item["category"],
                "type": item["type"],
                "status": item["status"],
                "status_color": item["status_color"],
                "date_updated": item["date_updated"],
                "summary": item["summary"],
                "impact": item["impact"],
                "btc_impact": item["btc_impact"],
                "auto_detected": False,
            }
            supabase.table("regulatory_items").insert(row).execute()
            seeded += 1
        except Exception as e:
            logger.debug(f"Regulatory seed skip: {e}")

    logger.info(f"Regulatory items: {seeded} seeded, {skipped} already existed")
    return seeded, skipped


def seed_notable_statements():
    """Seed notable statements from hardcoded data."""
    from regulatory_tracker import NOTABLE_STATEMENTS
    from regulatory_scanner import generate_item_id

    logger.info("Seeding notable statements...")
    seeded = 0
    skipped = 0

    for s in NOTABLE_STATEMENTS:
        stmt_id = f"seed_{generate_item_id(s['person'] + s['date'])}"
        try:
            existing = supabase.table("notable_statements").select("statement_id").eq("statement_id", stmt_id).execute()
            if existing.data:
                skipped += 1
                continue
            row = {
                "statement_id": stmt_id,
                "person": s["person"],
                "title": s["title"],
                "date": s["date"],
                "statement": s["statement"],
                "impact": s["impact"],
                "category": s["category"],
                "auto_detected": False,
            }
            supabase.table("notable_statements").insert(row).execute()
            seeded += 1
        except Exception as e:
            logger.debug(f"Statement seed skip: {e}")

    logger.info(f"Statements: {seeded} seeded, {skipped} already existed")
    return seeded, skipped


def seed_confirmed_purchases():
    """Seed known historical purchases."""
    from purchase_tracker import KNOWN_PURCHASES

    logger.info("Seeding confirmed purchases...")
    seeded = 0
    skipped = 0

    for p in KNOWN_PURCHASES:
        purchase_id = f"buy_{p['ticker']}_{p['filing_date']}"
        try:
            existing = supabase.table("confirmed_purchases").select("purchase_id").eq("purchase_id", purchase_id).execute()
            if existing.data:
                skipped += 1
                continue
            row = {
                "purchase_id": purchase_id,
                "company": p["company"],
                "ticker": p["ticker"],
                "btc_amount": p["btc_amount"],
                "usd_amount": p["usd_amount"],
                "price_per_btc": p["price_per_btc"],
                "filing_date": p["filing_date"],
                "filing_url": "",
                "was_predicted": False,
            }
            supabase.table("confirmed_purchases").insert(row).execute()
            seeded += 1
            logger.info(f"  Seeded: {p['company']} — {p['btc_amount']:,} BTC on {p['filing_date']}")
        except Exception as e:
            logger.debug(f"Purchase seed skip: {e}")

    logger.info(f"Purchases: {seeded} seeded, {skipped} already existed")
    return seeded, skipped


def seed_treasury_companies():
    """Seed treasury company metadata for the leaderboard."""
    from treasury_leaderboard import FALLBACK_COMPANIES, SOVEREIGN_HOLDERS

    logger.info("Seeding treasury companies...")
    seeded = 0
    skipped = 0

    all_companies = FALLBACK_COMPANIES + SOVEREIGN_HOLDERS

    for c in all_companies:
        ticker = c.get("ticker", "")
        if not ticker:
            continue
        try:
            existing = supabase.table("treasury_companies").select("ticker").eq("ticker", ticker).execute()
            if existing.data:
                skipped += 1
                continue
            row = {
                "ticker": ticker,
                "company": c["company"],
                "btc_holdings": c.get("btc_holdings", 0),
                "avg_purchase_price": c.get("avg_purchase_price", 0),
                "total_cost_usd": c.get("total_cost_usd", 0),
                "country": c.get("country", ""),
                "sector": c.get("sector", ""),
                "is_government": c.get("is_government", False),
                "data_source": "seed",
            }
            supabase.table("treasury_companies").insert(row).execute()
            seeded += 1
        except Exception as e:
            logger.debug(f"Treasury company seed skip: {e}")

    logger.info(f"Treasury companies: {seeded} seeded, {skipped} already existed")
    return seeded, skipped


def seed_edgar_companies():
    """Seed SEC EDGAR CIK mappings."""
    from edgar_monitor import TREASURY_COMPANIES

    logger.info("Seeding EDGAR company mappings...")
    seeded = 0
    skipped = 0

    for cik, info in TREASURY_COMPANIES.items():
        try:
            existing = supabase.table("edgar_companies").select("cik").eq("cik", cik).execute()
            if existing.data:
                skipped += 1
                continue
            row = {
                "cik": cik,
                "company": info["name"],
                "ticker": info["ticker"],
                "priority": info.get("priority", "medium"),
                "is_active": True,
            }
            supabase.table("edgar_companies").insert(row).execute()
            seeded += 1
        except Exception as e:
            logger.debug(f"EDGAR company seed skip: {e}")

    logger.info(f"EDGAR companies: {seeded} seeded, {skipped} already existed")
    return seeded, skipped


def run_full_seed():
    """Run all seeders."""
    logger.info("=" * 60)
    logger.info("DATABASE SEEDER — Populating all tables")
    logger.info("=" * 60)

    results = {}
    results["regulatory"] = seed_regulatory_items()
    results["statements"] = seed_notable_statements()
    results["purchases"] = seed_confirmed_purchases()
    results["companies"] = seed_treasury_companies()
    results["edgar"] = seed_edgar_companies()

    logger.info("")
    logger.info("=" * 60)
    logger.info("SEED COMPLETE — Summary:")
    for name, (seeded, skipped) in results.items():
        logger.info(f"  {name}: {seeded} new, {skipped} existing")
    logger.info("=" * 60)
    logger.info("")
    logger.info("The database is now the single source of truth.")
    logger.info("Hardcoded data will NOT be used for display.")

    return results


# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  TREASURY SIGNAL INTELLIGENCE — Database Seeder")
    print("=" * 60)
    print()
    print("Before running this script, create the tables in Supabase.")
    print("Copy the SQL from SETUP_SQL and run it in Supabase SQL Editor.")
    print()
    print("Tables to create:")
    print("  - regulatory_items")
    print("  - notable_statements")
    print("  - confirmed_purchases")
    print("  - predictions")
    print("  - leaderboard_snapshots")
    print("  - data_freshness")
    print("  - tweets")
    print("  - treasury_companies  (NEW)")
    print("  - edgar_companies     (NEW)")
    print()

    response = input("Have you created the tables? (y/n): ").strip().lower()
    if response != "y":
        print("\nPlease create the tables first, then run this script again.")
        print(f"\nSQL to run:\n{SETUP_SQL}")
        exit()

    print()
    run_full_seed()
    print("\nDone! You can now run: python main.py")
