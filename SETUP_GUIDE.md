# Treasury Sync — Setup Guide

## What This Fixes

Your `treasury_companies` table only has 14 hardcoded companies.
BitcoinTreasuries.net tracks 100+ entities (public companies, private companies,
ETFs, governments). This module fetches ALL of them and syncs to Supabase every
scan cycle — so your landing page, leaderboard, adoption tracker, and every
other page shows accurate, up-to-date data.

---

## Step 1 — Run this SQL in Supabase SQL Editor

```sql
-- Add entity_type and ensure last_updated columns exist
ALTER TABLE treasury_companies 
  ADD COLUMN IF NOT EXISTS entity_type TEXT DEFAULT 'public_company';

ALTER TABLE treasury_companies 
  ADD COLUMN IF NOT EXISTS last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW();

-- Add entity_count to leaderboard_snapshots if not exists
ALTER TABLE leaderboard_snapshots 
  ADD COLUMN IF NOT EXISTS entity_count INTEGER DEFAULT 0;

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_treasury_companies_holdings 
  ON treasury_companies(btc_holdings DESC);

CREATE INDEX IF NOT EXISTS idx_treasury_companies_type 
  ON treasury_companies(entity_type);
```

## Step 2 — Add treasury_sync.py to your Python scanner folder

Copy `treasury_sync.py` into your `treasury-signals` folder alongside the
other Python files.

## Step 3 — Update main.py

Add this import at the top with the other imports:
```python
from treasury_sync import sync as treasury_sync
```

Find the leaderboard section in your scan loop (search for "leaderboard" or
"save_leaderboard_to_db") and add this RIGHT AFTER the leaderboard save:

```python
        # Sync all entities to treasury_companies table
        try:
            treasury_sync.run()
        except Exception as e:
            logger.debug(f"Treasury sync: {e}")
```

## Step 4 — Push to Render

```
cd "treasury-signals folder"
git add .
git commit -m "Add treasury sync - fetch all entities from BitcoinTreasuries.net"
git push
```

## Step 5 — Run it manually first (optional)

If you want to populate the data immediately without waiting for the
next scan cycle:

```
python treasury_sync.py
```

This will fetch all entities and upsert them into Supabase right away.

---

## What Happens After Setup

1. **Every scan cycle (60 min)**, the sync module runs
2. It fetches from BitcoinTreasuries.net API → CoinGecko → HTML scrape (fallback)
3. All entities are upserted into `treasury_companies`
4. The `leaderboard_snapshots` table gets updated with the accurate entity count
5. **Every page in your dashboard** automatically shows the correct numbers
   because they all read from `treasury_companies`

## Expected Results

After the first sync, your landing page should show:
- **100+** companies tracked (instead of 14)
- **2,000,000+** total BTC monitored (instead of 655,881)
- Accurate sovereign holder count
- Accurate signal count

The Live Data page, Leaderboard, Adoption Tracker, Competitive Intelligence,
and all other pages will also update automatically.
