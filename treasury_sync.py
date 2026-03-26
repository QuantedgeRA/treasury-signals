"""
treasury_sync.py — Master Data Sync Engine
--------------------------------------------
Fetches ALL Bitcoin-holding entities from multiple sources and
upserts them into the treasury_companies Supabase table.

Sources (in priority order):
1. BitcoinTreasuries.net API (most comprehensive — public, private, ETFs, govs)
2. CoinGecko public companies API (good for public companies)
3. Hardcoded fallback (last resort)

Entity types tracked:
- public_company  (publicly traded companies)
- private_company (private companies)
- etf             (Bitcoin ETFs and funds)
- government      (sovereign/government holders)
- other           (anything else)

This runs once per scan cycle and ensures the treasury_companies
table always has the most up-to-date, comprehensive data.

Usage:
    from treasury_sync import sync
    sync.run()   # Full sync — call once per scan cycle
"""

import os
import json
import re
import requests
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


class TreasurySync:
    """Syncs ALL Bitcoin-holding entities to Supabase."""

    def __init__(self):
        self._last_sync = None
        self._entity_count = 0

    def run(self):
        """Full sync: fetch from all sources, merge, upsert to DB."""
        logger.info("Treasury Sync: starting full entity sync...")

        all_entities = {}  # ticker -> entity dict (deduped by ticker)

        # ─── Source 1: BitcoinTreasuries.net API (most comprehensive) ───
        bt_entities = self._fetch_bitcointreasuries_api()
        for e in bt_entities:
            key = e["ticker"]
            all_entities[key] = e

        # ─── Source 2: CoinGecko public companies ───
        cg_entities = self._fetch_coingecko()
        for e in cg_entities:
            key = e["ticker"]
            if key not in all_entities:
                all_entities[key] = e
            else:
                # Merge: CoinGecko sometimes has better country/cost data
                existing = all_entities[key]
                if not existing.get("country") or existing["country"] == "Unknown":
                    existing["country"] = e.get("country", existing.get("country", ""))
                if e.get("total_cost_usd", 0) > 0 and existing.get("total_cost_usd", 0) == 0:
                    existing["total_cost_usd"] = e["total_cost_usd"]
                    existing["avg_purchase_price"] = e.get("avg_purchase_price", 0)

        # ─── Source 3: BitcoinTreasuries.net sovereign API ───
        sov_entities = self._fetch_sovereign_api()
        for e in sov_entities:
            key = e["ticker"]
            if key not in all_entities:
                all_entities[key] = e
            else:
                # Update holdings if sovereign API has newer data
                if e.get("btc_holdings", 0) > all_entities[key].get("btc_holdings", 0):
                    all_entities[key]["btc_holdings"] = e["btc_holdings"]

        if not all_entities:
            logger.warning("Treasury Sync: no entities fetched from any source")
            return 0

        # ─── Upsert all to Supabase ───
        count = self._upsert_all(all_entities)
        self._last_sync = datetime.now()
        self._entity_count = count

        # ─── Update leaderboard snapshot entity_count ───
        self._update_snapshot_count(all_entities)

        logger.info(f"Treasury Sync: {count} entities synced to Supabase from {len(all_entities)} total")
        return count

    def _fetch_bitcointreasuries_api(self):
        """Fetch ALL entities from BitcoinTreasuries.net API."""
        entities = []

        # Try the main entities API
        endpoints = [
            ("https://api.bitcointreasuries.net/views/entities", "api_entities"),
            ("https://api.bitcointreasuries.net/views/treasuries", "api_treasuries"),
        ]

        for url, source_name in endpoints:
            try:
                logger.debug(f"Treasury Sync: trying {url}...")
                resp = requests.get(url, headers=HEADERS, timeout=20)
                if resp.status_code != 200:
                    logger.debug(f"Treasury Sync: {url} returned {resp.status_code}")
                    continue

                data = resp.json()
                if not isinstance(data, list):
                    logger.debug(f"Treasury Sync: {url} returned non-list")
                    continue

                for item in data:
                    try:
                        entity = self._parse_bt_entity(item, source_name)
                        if entity and entity.get("btc_holdings", 0) > 0:
                            entities.append(entity)
                    except Exception as e:
                        logger.debug(f"Treasury Sync: skip BT entity: {e}")
                        continue

                if entities:
                    logger.info(f"Treasury Sync: BitcoinTreasuries.net API — {len(entities)} entities from {source_name}")
                    return entities

            except Exception as e:
                logger.debug(f"Treasury Sync: {url} failed: {e}")
                continue

        # Fallback: scrape the HTML tables
        entities = self._scrape_bitcointreasuries_html()
        return entities

    def _parse_bt_entity(self, item, source):
        """Parse a single entity from BitcoinTreasuries.net API."""
        name = item.get("name") or item.get("company") or item.get("entity") or ""
        if not name:
            return None

        ticker = item.get("symbol") or item.get("ticker") or ""
        if not ticker:
            # Generate a ticker from the name
            ticker = re.sub(r'[^A-Za-z0-9]', '', name.upper()[:8])
        ticker = ticker.upper().strip()

        btc = 0
        for field in ["total_holdings", "btc", "btc_holdings", "holdings", "total_btc"]:
            val = item.get(field)
            if val:
                try:
                    btc = int(float(str(val).replace(",", "")))
                    break
                except:
                    pass

        country = item.get("country") or item.get("domicile") or ""

        # Determine entity type
        entity_type = "public_company"
        category = (item.get("category") or item.get("type") or "").lower()
        is_gov = False

        if any(kw in category for kw in ["gov", "country", "nation", "sovereign", "state"]):
            entity_type = "government"
            is_gov = True
        elif any(kw in category for kw in ["etf", "fund", "trust", "etp"]):
            entity_type = "etf"
        elif any(kw in category for kw in ["private"]):
            entity_type = "private_company"
        elif any(kw in name.lower() for kw in ["government", "gov ", " gov"]):
            entity_type = "government"
            is_gov = True
        elif any(kw in name.lower() for kw in ["etf", " fund", "trust", "grayscale", "ishares", "fidelity wise"]):
            entity_type = "etf"

        # Sector mapping
        sector = item.get("sector") or item.get("industry") or ""
        if not sector:
            if entity_type == "government":
                sector = "Government"
            elif entity_type == "etf":
                sector = "ETF / Fund"
            elif any(kw in name.lower() for kw in ["mining", "miner", "mara", "riot", "cleanspark", "bitfarms", "hut 8"]):
                sector = "Bitcoin Mining"
            elif any(kw in name.lower() for kw in ["exchange", "coinbase", "kraken"]):
                sector = "Crypto Exchange"
            else:
                sector = "Technology"

        cost = 0
        avg_price = 0
        for field in ["total_entry_value_usd", "total_cost_usd", "cost_basis"]:
            val = item.get(field)
            if val:
                try:
                    cost = int(float(str(val).replace(",", "")))
                    if btc > 0:
                        avg_price = int(cost / btc)
                    break
                except:
                    pass

        return {
            "ticker": ticker,
            "company": name,
            "btc_holdings": btc,
            "avg_purchase_price": avg_price,
            "total_cost_usd": cost,
            "country": country,
            "sector": sector,
            "is_government": is_gov,
            "entity_type": entity_type,
            "data_source": f"bitcointreasuries_{source}",
        }

    def _scrape_bitcointreasuries_html(self):
        """Fallback: scrape HTML tables from BitcoinTreasuries.net."""
        entities = []
        try:
            logger.debug("Treasury Sync: scraping BitcoinTreasuries.net HTML...")
            from bs4 import BeautifulSoup
            resp = requests.get("https://bitcointreasuries.net/", headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "lxml")
            tables = soup.find_all("table")

            for table in tables:
                rows = table.find_all("tr")[1:]  # skip header
                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) < 3:
                        continue
                    try:
                        name = cols[0].get_text(strip=True)
                        ticker = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                        btc_text = cols[2].get_text(strip=True).replace(",", "").replace(" ", "") if len(cols) > 2 else "0"

                        # Try to parse BTC
                        btc = 0
                        btc_clean = re.sub(r'[^\d.]', '', btc_text)
                        if btc_clean:
                            btc = int(float(btc_clean))

                        if not name or btc <= 0:
                            continue

                        if not ticker:
                            ticker = re.sub(r'[^A-Za-z0-9]', '', name.upper()[:8])

                        # Guess entity type from table context
                        entity_type = "public_company"
                        is_gov = False
                        section_header = ""
                        prev = table.find_previous(["h1", "h2", "h3", "h4"])
                        if prev:
                            section_header = prev.get_text(strip=True).lower()

                        if any(kw in section_header for kw in ["gov", "country", "nation"]):
                            entity_type = "government"
                            is_gov = True
                        elif any(kw in section_header for kw in ["etf", "fund"]):
                            entity_type = "etf"
                        elif any(kw in section_header for kw in ["private"]):
                            entity_type = "private_company"

                        entities.append({
                            "ticker": ticker.upper(),
                            "company": name,
                            "btc_holdings": btc,
                            "avg_purchase_price": 0,
                            "total_cost_usd": 0,
                            "country": "Unknown",
                            "sector": "BTC Treasury",
                            "is_government": is_gov,
                            "entity_type": entity_type,
                            "data_source": "bitcointreasuries_html",
                        })
                    except Exception as e:
                        logger.debug(f"Treasury Sync: skip HTML row: {e}")
                        continue

            if entities:
                logger.info(f"Treasury Sync: scraped {len(entities)} entities from HTML")

        except Exception as e:
            logger.warning(f"Treasury Sync: HTML scrape failed: {e}")

        return entities

    def _fetch_coingecko(self):
        """Fetch public companies from CoinGecko."""
        entities = []
        try:
            logger.debug("Treasury Sync: fetching CoinGecko public companies...")
            resp = requests.get(
                "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin",
                headers=HEADERS, timeout=15
            )
            if resp.status_code != 200:
                logger.debug(f"Treasury Sync: CoinGecko returned {resp.status_code}")
                return []

            data = resp.json()
            for item in data.get("companies", []):
                try:
                    ticker = (item.get("symbol") or "").upper()
                    name = item.get("name") or ""
                    btc = int(item.get("total_holdings", 0))
                    if not ticker or not name or btc <= 0:
                        continue

                    cost = int(float(item.get("total_entry_value_usd", 0) or 0))
                    avg = int(cost / btc) if btc > 0 and cost > 0 else 0

                    entities.append({
                        "ticker": ticker,
                        "company": name,
                        "btc_holdings": btc,
                        "avg_purchase_price": avg,
                        "total_cost_usd": cost,
                        "country": item.get("country", "Unknown"),
                        "sector": "Technology",
                        "is_government": False,
                        "entity_type": "public_company",
                        "data_source": "coingecko",
                    })
                except Exception as e:
                    logger.debug(f"Treasury Sync: skip CoinGecko entry: {e}")
                    continue

            if entities:
                logger.info(f"Treasury Sync: CoinGecko — {len(entities)} public companies")

        except Exception as e:
            logger.debug(f"Treasury Sync: CoinGecko failed: {e}")

        return entities

    def _fetch_sovereign_api(self):
        """Fetch government holders from BitcoinTreasuries.net API."""
        entities = []
        try:
            logger.debug("Treasury Sync: fetching sovereign holders...")
            resp = requests.get(
                "https://api.bitcointreasuries.net/views/countries",
                headers=HEADERS, timeout=15
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            if not isinstance(data, list):
                return []

            flag_map = {
                "united states": ("🇺🇸 United States", "US-GOV", "US"),
                "china": ("🇨🇳 China", "CN-GOV", "CN"),
                "united kingdom": ("🇬🇧 United Kingdom", "UK-GOV", "GB"),
                "ukraine": ("🇺🇦 Ukraine", "UA-GOV", "UA"),
                "bhutan": ("🇧🇹 Bhutan", "BT-GOV", "BT"),
                "el salvador": ("🇸🇻 El Salvador", "SV-GOV", "SV"),
                "finland": ("🇫🇮 Finland", "FI-GOV", "FI"),
                "germany": ("🇩🇪 Germany", "DE-GOV", "DE"),
                "georgia": ("🇬🇪 Georgia", "GE-GOV", "GE"),
                "czech": ("🇨🇿 Czech Republic", "CZ-GOV", "CZ"),
                "north korea": ("🇰🇵 North Korea", "KP-GOV", "KP"),
                "japan": ("🇯🇵 Japan", "JP-GOV", "JP"),
                "switzerland": ("🇨🇭 Switzerland", "CH-GOV", "CH"),
                "russia": ("🇷🇺 Russia", "RU-GOV", "RU"),
                "brazil": ("🇧🇷 Brazil", "BR-GOV", "BR"),
                "canada": ("🇨🇦 Canada", "CA-GOV", "CA"),
                "australia": ("🇦🇺 Australia", "AU-GOV", "AU"),
                "india": ("🇮🇳 India", "IN-GOV", "IN"),
                "norway": ("🇳🇴 Norway", "NO-GOV", "NO"),
                "poland": ("🇵🇱 Poland", "PL-GOV", "PL"),
                "thailand": ("🇹🇭 Thailand", "TH-GOV", "TH"),
                "singapore": ("🇸🇬 Singapore", "SG-GOV", "SG"),
                "saudi": ("🇸🇦 Saudi Arabia", "SA-GOV", "SA"),
                "venezuela": ("🇻🇪 Venezuela", "VE-GOV", "VE"),
                "iran": ("🇮🇷 Iran", "IR-GOV", "IR"),
                "turkey": ("🇹🇷 Turkey", "TR-GOV", "TR"),
            }

            for item in data:
                try:
                    name = item.get("name") or item.get("country") or ""
                    btc = int(float(item.get("total_holdings", 0) or 0))
                    if btc <= 0:
                        continue

                    name_lower = name.lower()
                    matched = None
                    for key, (display, ticker, country) in flag_map.items():
                        if key in name_lower:
                            matched = {
                                "ticker": ticker, "company": display, "btc_holdings": btc,
                                "avg_purchase_price": 0, "total_cost_usd": 0,
                                "country": country, "sector": "Government",
                                "is_government": True, "entity_type": "government",
                                "data_source": "bitcointreasuries_sovereign",
                            }
                            break

                    if not matched:
                        ticker = f"{name[:2].upper()}-GOV"
                        matched = {
                            "ticker": ticker, "company": f"🏛️ {name}", "btc_holdings": btc,
                            "avg_purchase_price": 0, "total_cost_usd": 0,
                            "country": "", "sector": "Government",
                            "is_government": True, "entity_type": "government",
                            "data_source": "bitcointreasuries_sovereign",
                        }

                    entities.append(matched)
                except Exception as e:
                    logger.debug(f"Treasury Sync: skip sovereign: {e}")

            if entities:
                logger.info(f"Treasury Sync: {len(entities)} sovereign holders from API")

        except Exception as e:
            logger.debug(f"Treasury Sync: sovereign API failed: {e}")

        return entities

    def _upsert_all(self, all_entities):
        """Upsert all entities to treasury_companies table."""
        count = 0
        errors = 0

        for ticker, entity in all_entities.items():
            try:
                row = {
                    "ticker": ticker,
                    "company": entity["company"][:200],
                    "btc_holdings": entity.get("btc_holdings", 0),
                    "avg_purchase_price": entity.get("avg_purchase_price", 0),
                    "total_cost_usd": entity.get("total_cost_usd", 0),
                    "country": (entity.get("country") or "")[:100],
                    "sector": (entity.get("sector") or "")[:100],
                    "is_government": entity.get("is_government", False),
                    "data_source": entity.get("data_source", "sync"),
                    "last_updated": datetime.now().isoformat(),
                }

                supabase.table("treasury_companies").upsert(
                    row, on_conflict="ticker"
                ).execute()
                count += 1

            except Exception as e:
                errors += 1
                if errors <= 5:
                    logger.debug(f"Treasury Sync: upsert error for {ticker}: {e}")

        if errors > 5:
            logger.warning(f"Treasury Sync: {errors} total upsert errors (showing first 5)")

        return count

    def _update_snapshot_count(self, all_entities):
        """Update today's leaderboard snapshot with accurate entity count."""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            corporate = [e for e in all_entities.values() if not e.get("is_government")]
            sovereign = [e for e in all_entities.values() if e.get("is_government")]
            total_btc = sum(e.get("btc_holdings", 0) for e in all_entities.values())

            supabase.table("leaderboard_snapshots").upsert({
                "snapshot_date": today,
                "total_btc": total_btc,
                "entity_count": len(all_entities),
            }, on_conflict="snapshot_date").execute()

            logger.debug(f"Treasury Sync: snapshot updated — {len(all_entities)} entities, {total_btc:,} BTC")
        except Exception as e:
            logger.debug(f"Treasury Sync: snapshot update failed: {e}")


# ============================================
# GLOBAL INSTANCE
# ============================================
sync = TreasurySync()


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Treasury Sync — running full sync test...")
    count = sync.run()
    print(f"\n{'='*60}")
    print(f"  TREASURY SYNC COMPLETE")
    print(f"  {count} entities synced to Supabase")
    print(f"{'='*60}\n")
