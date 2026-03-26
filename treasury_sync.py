"""
treasury_sync.py — Master Data Sync Engine v4.0
-------------------------------------------------
Data pipeline architecture:

  LAYER 1 — PRIMARY (CoinGecko API)
  ├── Reliable structured API
  ├── ~148 public companies with cost basis
  └── Always runs first, data takes precedence

  LAYER 2 — SUPPLEMENT (BitcoinTreasuries.net HTML)
  ├── Adds private companies, ETFs, governments, DeFi
  ├── ~150+ additional entities CoinGecko doesn't have
  └── Only fills gaps — never overwrites CoinGecko data

  STALENESS MONITORING
  ├── Tracks last successful fetch per source
  ├── Alerts admin (never users) if data goes stale
  └── Logs warnings if entity counts drop unexpectedly

Usage:
    from treasury_sync import sync
    sync.run()
"""

import os
import re
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from bs4 import BeautifulSoup
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "contact@quantedgeriskadvisory.com")
EMAIL_FROM = os.getenv("EMAIL_FROM_ADDRESS", "briefing@quantedgeriskadvisory.com")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

BT_PAGES = [
    {"url": "https://bitcointreasuries.net/", "category": "public_company", "label": "Public Companies", "is_government": False},
    {"url": "https://bitcointreasuries.net/private-companies", "category": "private_company", "label": "Private Companies", "is_government": False},
    {"url": "https://bitcointreasuries.net/governments", "category": "government", "label": "Government Entities", "is_government": True},
    {"url": "https://bitcointreasuries.net/etfs-and-exchanges", "category": "etf", "label": "ETFs and Exchanges", "is_government": False},
    {"url": "https://bitcointreasuries.net/defi-and-other", "category": "defi", "label": "DeFi and Other", "is_government": False},
]

SOVEREIGN_FLAGS = {
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
    "tonga": ("🇹🇴 Tonga", "TO-GOV", "TO"),
    "kazakhstan": ("🇰🇿 Kazakhstan", "KZ-GOV", "KZ"),
    "hong kong": ("🇭🇰 Hong Kong", "HK-GOV", "HK"),
    "ethiopia": ("🇪🇹 Ethiopia", "ET-GOV", "ET"),
    "myanmar": ("🇲🇲 Myanmar", "MM-GOV", "MM"),
    "colombia": ("🇨🇴 Colombia", "CO-GOV", "CO"),
    "liechtenstein": ("🇱🇮 Liechtenstein", "LI-GOV", "LI"),
    "montenegro": ("🇲🇪 Montenegro", "ME-GOV", "ME"),
}

# ═══════════════════════════════════════════════════════════════
# STALENESS TRACKER
# ═══════════════════════════════════════════════════════════════

class StalenessTracker:
    """Tracks data freshness per source and alerts admin if stale."""

    def __init__(self):
        self._last_success = {}      # source -> datetime
        self._last_counts = {}       # source -> entity count
        self._alert_sent_today = {}  # source -> date string (one alert per day per source)

    def record_success(self, source, count):
        self._last_success[source] = datetime.now()
        self._last_counts[source] = count

    def record_failure(self, source, error=""):
        logger.warning(f"STALENESS: {source} failed — {error}")

    def check_and_alert(self):
        """Check all sources for staleness. Alert admin if needed."""
        issues = []
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # Check CoinGecko (primary) — should succeed every cycle
        cg_last = self._last_success.get("coingecko")
        if not cg_last:
            issues.append("CoinGecko (PRIMARY): never succeeded this session")
        elif (now - cg_last).total_seconds() > 7200:  # 2 hours
            issues.append(f"CoinGecko (PRIMARY): last success {cg_last.strftime('%H:%M')} ({int((now - cg_last).total_seconds() / 60)}min ago)")

        # Check BT pages — supplement, less critical but still important
        for page in BT_PAGES:
            key = f"bt_{page['category']}"
            bt_last = self._last_success.get(key)
            count = self._last_counts.get(key, 0)
            expected_min = {"public_company": 80, "private_company": 20, "government": 5, "etf": 15, "defi": 5}
            min_expected = expected_min.get(page["category"], 5)

            if not bt_last:
                issues.append(f"BT {page['label']}: never succeeded this session")
            elif count < min_expected:
                issues.append(f"BT {page['label']}: only {count} entities (expected {min_expected}+) — parser may be broken")

        # Check total entity count
        total = sum(self._last_counts.values())
        if total < 200:
            issues.append(f"TOTAL ENTITIES: only {total} (expected 300+) — data may be incomplete")

        if not issues:
            return

        # Only alert once per day per issue set
        issue_key = "|".join(sorted(issues))
        if self._alert_sent_today.get(issue_key) == today:
            return

        # Log all issues
        logger.warning("=" * 50)
        logger.warning("STALENESS ALERT — Data pipeline issues detected:")
        for issue in issues:
            logger.warning(f"  ⚠️  {issue}")
        logger.warning("=" * 50)

        # Send email to admin (NOT users)
        self._send_admin_alert(issues)
        self._alert_sent_today[issue_key] = today

    def _send_admin_alert(self, issues):
        """Send staleness alert email to admin only."""
        if not RESEND_API_KEY:
            logger.debug("Staleness alert: no RESEND_API_KEY, skipping email")
            return

        subject = f"⚠️ TSI Data Pipeline Alert — {len(issues)} issue(s)"
        body_lines = [
            "<h2>Treasury Sync — Staleness Alert</h2>",
            f"<p>Detected at {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</p>",
            "<p>The following data sources have issues:</p>",
            "<ul>",
        ]
        for issue in issues:
            body_lines.append(f"<li><strong>{issue}</strong></li>")
        body_lines.extend([
            "</ul>",
            "<h3>Source Status</h3>",
            "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;'>",
            "<tr><th>Source</th><th>Last Success</th><th>Entities</th></tr>",
        ])
        for source, last in self._last_success.items():
            count = self._last_counts.get(source, 0)
            body_lines.append(f"<tr><td>{source}</td><td>{last.strftime('%H:%M')}</td><td>{count}</td></tr>")
        body_lines.extend([
            "</table>",
            "<p style='color:#999;font-size:12px;'>This alert is sent to admin only. Users are not affected unless data becomes significantly outdated.</p>",
            "<p style='color:#999;font-size:12px;'>Check Render logs for details. If BT scraping broke, the parser may need updating for HTML changes.</p>",
        ])

        try:
            resp = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                json={
                    "from": f"TSI Alerts <{EMAIL_FROM}>",
                    "to": [ADMIN_EMAIL],
                    "subject": subject,
                    "html": "\n".join(body_lines),
                },
                timeout=10,
            )
            if resp.status_code in (200, 201):
                logger.info(f"Staleness alert sent to {ADMIN_EMAIL}")
            else:
                logger.debug(f"Staleness alert email failed: {resp.status_code} {resp.text[:100]}")
        except Exception as e:
            logger.debug(f"Staleness alert email error: {e}")


# ═══════════════════════════════════════════════════════════════
# MAIN SYNC ENGINE
# ═══════════════════════════════════════════════════════════════

class TreasurySync:

    def __init__(self):
        self._last_sync = None
        self._entity_count = 0
        self._staleness = StalenessTracker()

    def run(self):
        logger.info("Treasury Sync v4: starting full entity sync...")

        all_entities = {}

        # ═══════════════════════════════════════════════════════
        # LAYER 1 — PRIMARY: CoinGecko API
        # Data takes precedence. Always runs first.
        # ═══════════════════════════════════════════════════════
        logger.info("─── Layer 1: CoinGecko (PRIMARY) ───")
        try:
            cg_entities = self._fetch_coingecko()
            for e in cg_entities:
                all_entities[e["ticker"]] = e
            self._staleness.record_success("coingecko", len(cg_entities))
            logger.info(f"  CoinGecko               -> {len(cg_entities)} public companies (PRIMARY)")
        except Exception as e:
            self._staleness.record_failure("coingecko", str(e))
            logger.warning(f"  CoinGecko FAILED: {e}")

        # ═══════════════════════════════════════════════════════
        # LAYER 2 — SUPPLEMENT: BitcoinTreasuries.net HTML
        # Fills gaps only. Never overwrites CoinGecko data.
        # ═══════════════════════════════════════════════════════
        logger.info("─── Layer 2: BitcoinTreasuries.net (SUPPLEMENT) ───")
        for page in BT_PAGES:
            try:
                entities = self._scrape_page(page)
                new = 0
                updated = 0
                for e in entities:
                    key = e["ticker"]
                    if key not in all_entities:
                        # New entity not in CoinGecko — add it
                        all_entities[key] = e
                        new += 1
                    else:
                        # Entity already from CoinGecko — only supplement missing fields
                        existing = all_entities[key]
                        if not existing.get("country") or existing["country"] in ("", "Unknown"):
                            if e.get("country"):
                                existing["country"] = e["country"]
                                updated += 1
                        if not existing.get("sector") or existing["sector"] == "Technology":
                            if e.get("sector") and e["sector"] != "Technology":
                                existing["sector"] = e["sector"]
                        # NEVER overwrite CoinGecko btc_holdings or cost data

                self._staleness.record_success(f"bt_{page['category']}", len(entities))
                suffix = f" (+{updated} enriched)" if updated else ""
                logger.info(f"  {page['label']:25s} -> {len(entities):>4} scraped, {new:>4} new{suffix}")

            except Exception as e:
                self._staleness.record_failure(f"bt_{page['category']}", str(e))
                logger.warning(f"  {page['label']:25s} -> FAILED: {e}")

        if not all_entities:
            logger.warning("Treasury Sync: no entities fetched from any source")
            self._staleness.check_and_alert()
            return 0

        # ═══════════════════════════════════════════════════════
        # UPSERT + SNAPSHOT
        # ═══════════════════════════════════════════════════════
        count = self._upsert_all(all_entities)
        self._last_sync = datetime.now()
        self._entity_count = count
        self._update_snapshot(all_entities)

        # ═══════════════════════════════════════════════════════
        # STALENESS CHECK
        # ═══════════════════════════════════════════════════════
        self._staleness.check_and_alert()

        # ═══════════════════════════════════════════════════════
        # SUMMARY
        # ═══════════════════════════════════════════════════════
        by_type = {}
        for e in all_entities.values():
            t = e.get("entity_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        type_str = ", ".join(f"{v} {k}" for k, v in sorted(by_type.items(), key=lambda x: -x[1]))
        total_btc = sum(e.get("btc_holdings", 0) for e in all_entities.values())

        cg_count = self._staleness._last_counts.get("coingecko", 0)
        bt_count = count - cg_count
        logger.info(f"Treasury Sync COMPLETE: {count} entities ({cg_count} from CoinGecko, {bt_count} from BT supplement), {total_btc:,} BTC")
        logger.info(f"  Breakdown: {type_str}")
        return count

    # ═══════════════════════════════════════════════════════════
    # LAYER 1: COINGECKO (PRIMARY)
    # ═══════════════════════════════════════════════════════════

    def _fetch_coingecko(self):
        entities = []
        resp = requests.get(
            "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin",
            headers=HEADERS, timeout=15
        )
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}")

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
                    "ticker": ticker, "company": name, "btc_holdings": btc,
                    "avg_purchase_price": avg, "total_cost_usd": cost,
                    "country": item.get("country", ""), "sector": "Technology",
                    "is_government": False, "entity_type": "public_company",
                    "data_source": "coingecko",
                })
            except Exception:
                continue
        return entities

    # ═══════════════════════════════════════════════════════════
    # LAYER 2: BITCOINTREASURIES.NET (SUPPLEMENT)
    # ═══════════════════════════════════════════════════════════

    def _scrape_page(self, page):
        entities = []
        resp = requests.get(page["url"], headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}")

        soup = BeautifulSoup(resp.text, "lxml")
        tables = soup.find_all("table")

        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            first_row_cols = rows[1].find_all("td")
            first_texts = [td.get_text(strip=True) for td in first_row_cols]
            fmt = self._detect_format(first_texts)

            for row in rows[1:]:
                cols = row.find_all("td")
                if len(cols) < 3:
                    continue
                try:
                    entity = self._parse_row(cols, fmt, page)
                    if entity and entity.get("btc_holdings", 0) > 0:
                        entities.append(entity)
                except Exception:
                    continue
        return entities

    def _detect_format(self, texts):
        if len(texts) < 4:
            return "A"
        col1 = texts[1]
        col1_is_flag = len(col1) <= 6 and not col1.isascii()
        if not col1_is_flag and len(col1) > 3:
            return "B"
        return "A"

    def _parse_row(self, cols, fmt, page):
        texts = [td.get_text(strip=True) for td in cols]
        if fmt == "B":
            return self._parse_format_b(texts, page)
        return self._parse_format_a(texts, page)

    def _parse_format_a(self, texts, page):
        """[rank, flag, name, ₿btc, $usd, %supply]"""
        if len(texts) < 4:
            return None

        raw_name = texts[2]
        if not raw_name:
            return None

        btc = self._extract_btc(texts[3])
        if btc <= 0:
            for t in texts[3:]:
                btc = self._extract_btc(t)
                if btc > 0:
                    break
        if btc <= 0:
            return None

        name, ticker = self._extract_name_ticker(raw_name)
        if not name:
            return None
        if not ticker:
            ticker = re.sub(r'[^A-Za-z0-9]', '', name.upper()[:10])
        if not ticker:
            return None

        is_gov = page["is_government"]
        entity_type = page["category"]

        if is_gov:
            for key, (display, gov_ticker, country) in SOVEREIGN_FLAGS.items():
                if key in name.lower():
                    name = display
                    ticker = gov_ticker
                    break
            else:
                if not ticker.endswith("-GOV"):
                    ticker = f"{ticker[:5]}-GOV"

        return {
            "ticker": ticker.upper(), "company": name[:200], "btc_holdings": btc,
            "avg_purchase_price": 0, "total_cost_usd": 0,
            "country": self._get_country(name, is_gov),
            "sector": self._guess_sector(name, entity_type),
            "is_government": is_gov, "entity_type": entity_type,
            "data_source": f"bt_{page['category']}",
        }

    def _parse_format_b(self, texts, page):
        """[rank, name, flag, ticker, btc_number, ratio]"""
        if len(texts) < 5:
            return None
        name = texts[1]
        ticker = texts[3] if len(texts) > 3 else ""
        if not name:
            return None
        btc_text = texts[4] if len(texts) > 4 else "0"
        btc_clean = re.sub(r'[^\d.]', '', btc_text.replace(",", ""))
        btc = 0
        if btc_clean:
            try:
                btc = int(float(btc_clean))
            except:
                pass
        if btc <= 0:
            return None
        if not ticker:
            ticker = re.sub(r'[^A-Za-z0-9]', '', name.upper()[:10])
        return {
            "ticker": ticker.upper(), "company": name[:200], "btc_holdings": btc,
            "avg_purchase_price": 0, "total_cost_usd": 0, "country": "",
            "sector": self._guess_sector(name, page["category"]),
            "is_government": False, "entity_type": "public_company",
            "data_source": "bt_public_top",
        }

    def _extract_btc(self, text):
        if not text:
            return 0
        clean = text.replace("\u20bf", "").replace("₿", "").replace(",", "").replace(" ", "")
        clean = re.sub(r'[^\d.]', '', clean)
        if clean:
            try:
                return int(float(clean))
            except:
                pass
        return 0

    def _extract_name_ticker(self, raw):
        if not raw:
            return "", ""
        match = re.search(r'^(.+?)([A-Z][A-Z0-9]{1,7})(Buy|Sel)?$', raw)
        if match and len(match.group(1).strip()) >= 2:
            return match.group(1).strip(), match.group(2)
        return raw.strip(), ""

    def _get_country(self, name, is_gov):
        if is_gov:
            for key, (_, _, country) in SOVEREIGN_FLAGS.items():
                if key in name.lower():
                    return country
        return ""

    def _guess_sector(self, name, entity_type):
        n = name.lower()
        if entity_type == "government":
            return "Government"
        if entity_type == "etf":
            return "ETF / Fund"
        if entity_type == "defi":
            return "DeFi / Protocol"
        if entity_type == "private_company":
            return "Private Company"
        if any(kw in n for kw in ["mining", "miner", "mara", "riot", "cleanspark", "bitfarms", "hut 8", "iris", "core scientific", "bitfufu", "canaan"]):
            return "Bitcoin Mining"
        if any(kw in n for kw in ["exchange", "coinbase", "kraken", "binance"]):
            return "Crypto Exchange"
        if any(kw in n for kw in ["bank", "financial", "capital"]):
            return "Financial Services"
        if any(kw in n for kw in ["tesla"]):
            return "Automotive"
        if any(kw in n for kw in ["block", "square", "payment"]):
            return "Fintech / Payments"
        return "Technology"

    # ═══════════════════════════════════════════════════════════
    # DATABASE
    # ═══════════════════════════════════════════════════════════

    def _upsert_all(self, all_entities):
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
                supabase.table("treasury_companies").upsert(row, on_conflict="ticker").execute()
                count += 1
            except Exception as e:
                errors += 1
                if errors <= 3:
                    logger.debug(f"Upsert error {ticker}: {e}")
        if errors > 0:
            logger.warning(f"Treasury Sync: {errors} upsert errors")
        return count

    def _update_snapshot(self, all_entities):
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            total_btc = sum(e.get("btc_holdings", 0) for e in all_entities.values())
            supabase.table("leaderboard_snapshots").upsert({
                "snapshot_date": today,
                "total_btc": total_btc,
                "entity_count": len(all_entities),
            }, on_conflict="snapshot_date").execute()
        except Exception as e:
            logger.debug(f"Snapshot update failed: {e}")


# ============================================
# GLOBAL INSTANCE
# ============================================
sync = TreasurySync()

if __name__ == "__main__":
    logger.info("Treasury Sync v4 — full sync...")
    count = sync.run()
    print(f"\n{'='*60}")
    print(f"  TREASURY SYNC v4 COMPLETE")
    print(f"  {count} entities synced to Supabase")
    print(f"{'='*60}\n")
