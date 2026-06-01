"""
scrape_purchase_history.py — Automated Purchase History Scraper
=================================================================
Scrapes purchase/balance history from bitbo.io for all public companies
in treasury_companies and inserts into confirmed_purchases.

Bitbo.io has free web pages at bitbo.io/treasuries/{slug}/ with purchase
history tables for most tracked entities. This script:

1. Reads all public companies from treasury_companies
2. Skips companies that already have confirmed_purchases entries
3. Constructs bitbo.io slug from company name
4. Fetches and parses the purchase history table
5. Inserts positive balance changes as purchases
6. Inserts negative balance changes as sales

Table formats on bitbo.io:
  Format A (rare, Strategy only): Date | BTC Purchased | Amount | Total | Total Dollars
  Format B (common): Date | BTC Balance | Change

Requirements: pip install requests beautifulsoup4

Usage:
    python scrape_purchase_history.py          # Dry run
    python scrape_purchase_history.py --apply  # Insert into database
"""

import os
import sys
import re
import time
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import create_client
from treasury_signals.logger import get_logger
from treasury_signals.pipelines.purchase_keys import is_duplicate_key_error

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# ═══════════════════════════════════════════════════════════
# SLUG MAPPING — maps company names/tickers to bitbo.io slugs
# bitbo.io URL pattern: https://bitbo.io/treasuries/{slug}/
# ═══════════════════════════════════════════════════════════

KNOWN_SLUGS = {
    # Already backfilled (skip these) — included for reference
    "MSTR": "microstrategy",
    "TSLA": "tesla",
    "GME": "gamestop",
    "XYZ": "block",
    "MARA": "marathon",
    "3350.T": "metaplanet",
    "SMLR": "semler-scientific",
    "HUT": "hut-8",
    "KULR": "kulr-technology",
    "COIN": "coinbase",
    "RIOT": "riot",
    "CLSK": "cleanspark",
    "DJT": "trump-media",
    "XXI": "twenty-one",
    "CANG": "cango",
    "GLXY": "galaxy-digital",
    "RUM": "rumble",
    # New entities
    "ABTC": "american-bitcoin",
    "BRR": "procap-financial",
    "NAKA": "nakamoto",
    "GDC": "gd-culture-group",
    "NXTT": "next-technology",
    "BTDR": "bitdeer",
    "CIFR": "cipher-mining",
    "IREN": "iris-energy",
    "CORZ": "core-scientific",
    "BITF": "bitfarms",
    "MELI": "mercado-libre",
    "WULF": "terawulf",
    "BTBT": "bit-digital",
    "BTCT.V": "btc-inc",
    "MIGI": "mawson",
    "DGHI": "digihost",
    "APLD": "applied-digital",
    "ARBK": "argo-blockchain",
    "SATO.ST": "sato-technologies",
    "BRPHF": "brasil-potash",
    "EXOD": "exodus",
    "MSTR.US": "microstrategy",
    "ASST": "strive",
    "GNS": "genius-group",
    "BTCS": "btcs",
    "FLD": "fold",
    "STI": "solidion",
    "ACXP": "acurx",
    "WKSP": "worksport",
    "TZUP": "thumzup",
    "HOLO": "micro-cloud-hologram",
    "SOS": "sos-limited",
    "1357.HK": "meitu",
    "0434.HK": "boyaa-interactive",
    "434.HK": "boyaa-interactive",
    "OBTC3.SA": "oranjebtc",
    "NEDSE.AS": "coinshares",
    # Recently cleared placeholders (slugs to try)
    "BITF": "bitfarms",
    "FUFU": "bitfufu",
    "BITFUFU": "bitfufu",
    "BLSH": "bullish",
    "GEMI": "gemini",
    "DEFI": "defi-technologies",
    "EMPD": "empery-digital",
    "ALCPB.PA": "capital-b",
    "SWC.AQ": "smarter-web-company",
    "ADE": "bitcoin-group-se",
    "3659.T": "nexon",
    "3189.T": "anap-holdings",
    "3825.T": "remixpoint",
    "6574.T": "convano",
    "GS9.F": "h100-group",
    "ZOOZ": "zooz-power",
    "ZOOZ.TA": "zooz-power",
    "FIG": "figma",
    "FIGR": "figure-technology",
    "PHX.AD": "phoenix-group",
    "CEPO": "bitcoin-standard-treasury",
    "BTCT": "bitcoin-treasury-corp",
    "BTM": "bitcoin-depot",
    "KEEL": "keel-infrastructure",
    "SQNS": "sequans",
    "UUU": "3u-holding",
    "WNDR.TO": "wonderfi",
    "ABTS": "abits-group",
    "254A.T": "ai-fusion-capital",
    "ARLP": "alliance-resource-partners",
    "ANGX": "angel-studios",
    "SORA": "asiastrategy",
    "ATAI": "atai-life-sciences",
    "HODL.AQ": "b-hodl",
    "BNXA.V": "banxa",
    "BLGV.CN": "belgravia-hartford",
    "BIGG": "bigg-digital",
    "T3D.AX": "333d",
    "377030.KQ": "bitmax",
    "SRAG.DU": "samara-asset-group",
    "CMSG": "consensus-mining",
    "NTHOL.E.IS": "net-holding",
}


def _generate_slug(company_name, ticker):
    """Generate possible bitbo.io slugs from company name."""
    if not company_name:
        return []

    name = company_name.strip()
    # Remove common suffixes
    for suffix in [" Inc.", " Inc", " Corp.", " Corp", " Ltd.", " Ltd",
                   " PLC", " plc", " S.A.", " SE", " AG", " ASA",
                   " Holdings", " Group", " Co.", " (MicroStrategy)",
                   " International", " Technologies", " Technology"]:
        name = name.replace(suffix, "")

    name = name.strip()
    # Convert to slug: lowercase, spaces to hyphens, remove special chars
    slug = re.sub(r'[^a-z0-9\s-]', '', name.lower())
    slug = re.sub(r'\s+', '-', slug.strip())
    slug = re.sub(r'-+', '-', slug)

    slugs = [slug]

    # Also try first word only (e.g., "marathon" from "Marathon Digital Holdings")
    first_word = name.lower().split()[0] if name.split() else ""
    if first_word and first_word != slug:
        slugs.append(first_word)

    # Try first two words
    words = name.lower().split()
    if len(words) >= 2:
        two_word = f"{words[0]}-{words[1]}"
        if two_word not in slugs:
            slugs.append(two_word)

    return slugs


def _parse_purchase_table(html, company_name, ticker):
    """Parse bitbo.io purchase history table from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    entries = []

    # Find all tables
    tables = soup.find_all("table")
    if not tables:
        return []

    # Look for the purchase history table (usually the last/largest table)
    history_table = None
    for table in tables:
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if any("date" in h for h in headers) and any("btc" in h or "balance" in h or "change" in h or "purchased" in h for h in headers):
            history_table = table
            break

    if not history_table:
        # Try last table as fallback
        history_table = tables[-1]

    rows = history_table.find_all("tr")
    if len(rows) < 2:
        return []

    # Determine table format from headers
    headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
    is_format_a = any("purchased" in h for h in headers)  # Strategy-style detailed table
    is_format_b = any("balance" in h for h in headers)     # Balance + Change format

    for row in rows[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
        if len(cells) < 2:
            continue

        try:
            # Parse date
            date_str = cells[0].strip().replace("**", "").strip()
            if not date_str or not re.search(r'\d', date_str):
                continue

            # Try multiple date formats
            parsed_date = None
            for fmt in ["%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%Y-%m-%d",
                        "%B %d, %Y", "%d %b %Y", "%d/%m/%Y"]:
                try:
                    parsed_date = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue

            if not parsed_date:
                # Try partial dates like "4/1/2024 - 5/1/2024" (ranges)
                range_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', date_str)
                if range_match:
                    try:
                        parsed_date = datetime.strptime(range_match.group(1), "%m/%d/%Y")
                    except:
                        continue
                else:
                    continue

            filing_date = parsed_date.strftime("%Y-%m-%d")

            if is_format_a and len(cells) >= 4:
                # Format A: Date | BTC Purchased | Amount | Total Bitcoin | Total Dollars
                btc_str = cells[1].replace("**", "").replace(",", "").strip()
                usd_str = cells[2].replace("**", "").replace("$", "").replace(",", "").replace("M", "").replace("B", "").strip()

                btc = float(btc_str) if btc_str else 0
                usd_m = 0
                if usd_str:
                    try:
                        usd_m = float(usd_str)
                        # If original had B suffix, multiply
                        if "B" in cells[2].upper():
                            usd_m *= 1000
                    except:
                        usd_m = 0

                if btc != 0:
                    entries.append({
                        "date": filing_date,
                        "btc": btc,
                        "usd_m": usd_m,
                        "is_sale": btc < 0,
                    })

            elif is_format_b and len(cells) >= 3:
                # Format B: Date | BTC Balance | Change
                change_str = cells[2].replace("**", "").replace(",", "").strip()
                balance_str = cells[1].replace("**", "").replace(",", "").strip()

                change = 0
                try:
                    change = float(change_str)
                except:
                    continue

                if change != 0:
                    entries.append({
                        "date": filing_date,
                        "btc": abs(change),
                        "usd_m": 0,
                        "is_sale": change < 0,
                    })

            elif len(cells) >= 3:
                # Unknown format — try to extract any numeric change
                for cell in cells[1:]:
                    clean = cell.replace("**", "").replace(",", "").replace("+", "").strip()
                    try:
                        val = float(clean)
                        if abs(val) > 0.1 and abs(val) < 1000000:
                            # Looks like a BTC amount change
                            entries.append({
                                "date": filing_date,
                                "btc": abs(val),
                                "usd_m": 0,
                                "is_sale": val < 0 or "-" in cell,
                            })
                            break
                    except:
                        continue

        except Exception as e:
            continue

    return entries


def _fetch_history(slug):
    """Fetch purchase history page from bitbo.io."""
    url = f"https://bitbo.io/treasuries/{slug}/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            return resp.text
    except:
        pass
    return None


def normalize_ticker(t):
    return re.sub(r'\.[A-Z]+$', '', (t or '').strip(), flags=re.IGNORECASE).upper()


def scrape_all(dry_run=True):
    """Scrape purchase history for all public companies."""
    print(f"\n{'=' * 70}")
    print(f"Automated Purchase History Scraper (bitbo.io)")
    print(f"{'=' * 70}")
    print(f"Mode: {'DRY RUN' if dry_run else '⚡ LIVE'}")
    print(f"{'=' * 70}\n")

    # Get all public companies
    result = supabase.table("treasury_companies").select(
        "id, company, ticker, btc_holdings, entity_type"
    ).eq("entity_type", "public_company").gt("btc_holdings", 0).order(
        "btc_holdings", desc=True
    ).execute()
    companies = result.data or []

    # Get already-covered tickers
    existing = supabase.table("confirmed_purchases").select("ticker").execute()
    covered_tickers = set()
    if existing.data:
        for row in existing.data:
            tk = (row.get("ticker") or "").strip()
            covered_tickers.add(tk.upper())
            covered_tickers.add(normalize_ticker(tk))

    # Filter to uncovered companies
    uncovered = []
    for c in companies:
        tk = (c.get("ticker") or "").strip()
        if not tk:
            continue
        if tk.upper() in covered_tickers or normalize_ticker(tk) in covered_tickers:
            continue
        # Skip garbled names
        name = (c.get("company") or "").strip()
        if name and not re.match(r'^[A-Za-z0-9]', name):
            continue
        uncovered.append(c)

    print(f"Total public companies: {len(companies)}")
    print(f"Already covered:        {len(companies) - len(uncovered)}")
    print(f"Need scraping:          {len(uncovered)}\n")

    total_scraped = 0
    total_entries = 0
    total_failed = 0
    total_dupe = 0
    total_no_page = 0

    for c in uncovered:
        ticker = (c.get("ticker") or "").strip()
        company_name = (c.get("company") or "").strip()
        btc = c.get("btc_holdings", 0)

        # Determine slugs to try
        clean_tk = normalize_ticker(ticker)
        slugs_to_try = []

        if ticker in KNOWN_SLUGS:
            slugs_to_try.append(KNOWN_SLUGS[ticker])
        elif clean_tk in KNOWN_SLUGS:
            slugs_to_try.append(KNOWN_SLUGS[clean_tk])

        slugs_to_try.extend(_generate_slug(company_name, ticker))

        # Try each slug
        html = None
        used_slug = None
        for slug in slugs_to_try:
            if not slug:
                continue
            html = _fetch_history(slug)
            if html and "Purchase History" in html:
                used_slug = slug
                break
            # Small delay to be respectful
            time.sleep(0.3)

        if not html or not used_slug:
            total_no_page += 1
            print(f"  ⚪ {ticker:<14} | {company_name[:30]:<30} | No bitbo page found — skipped")
            continue

        # Parse the purchase history table
        entries = _parse_purchase_table(html, company_name, ticker)

        if not entries:
            total_no_page += 1
            print(f"  ⚪ {ticker:<14} | {company_name[:30]:<30} | Page found but no parseable history — skipped")
            continue

        # Insert entries
        total_scraped += 1
        print(f"  ✅ {ticker:<14} | {company_name[:30]:<30} | {len(entries)} entries from /{used_slug}/")

        for entry in entries:
            btc_amt = entry["btc"]
            usd = int(entry["usd_m"] * 1_000_000)
            price = round(usd / btc_amt) if btc_amt > 0 and usd > 0 else 0

            if entry["is_sale"]:
                sale_id = f"scraped_sale_{ticker}_{entry['date']}_{int(btc_amt)}"
                if dry_run:
                    print(f"      [DRY SALE] {entry['date']} | -{btc_amt:,.1f} BTC")
                    total_entries += 1
                else:
                    try:
                        supabase.table("confirmed_sales").upsert({
                            "sale_id": sale_id,
                            "company": company_name,
                            "ticker": ticker,
                            "btc_amount": btc_amt,
                            "usd_amount": usd,
                            "price_per_btc": price,
                            "filing_date": entry["date"],
                            "filing_url": f"https://bitbo.io/treasuries/{used_slug}/",
                            "source": f"Scraped from bitbo.io/treasuries/{used_slug}/",
                        }, on_conflict="sale_id").execute()
                        total_entries += 1
                    except Exception as e:
                        # A natural-key collision (migration 0022's unique index)
                        # means this sale is already recorded by another source —
                        # benign skip, not a failure.
                        if is_duplicate_key_error(e):
                            total_dupe += 1
                        else:
                            total_failed += 1
            else:
                purchase_id = f"scraped_{ticker}_{entry['date']}_{int(btc_amt)}"
                if dry_run:
                    print(f"      [DRY] {entry['date']} | +{btc_amt:,.1f} BTC | ${entry['usd_m']:,.1f}M")
                    total_entries += 1
                else:
                    try:
                        supabase.table("confirmed_purchases").upsert({
                            "purchase_id": purchase_id,
                            "company": company_name,
                            "ticker": ticker,
                            "btc_amount": btc_amt,
                            "usd_amount": usd,
                            "price_per_btc": price,
                            "filing_date": entry["date"],
                            "filing_url": f"https://bitbo.io/treasuries/{used_slug}/",
                            "was_predicted": False,
                            "source": f"Scraped from bitbo.io/treasuries/{used_slug}/",
                        }, on_conflict="purchase_id").execute()
                        total_entries += 1
                    except Exception as e:
                        # A natural-key collision (migration 0022's unique index)
                        # means this purchase is already recorded by another
                        # source — benign skip, not a failure.
                        if is_duplicate_key_error(e):
                            total_dupe += 1
                        else:
                            total_failed += 1

        time.sleep(0.5)  # Rate limit between companies

    print(f"\n{'=' * 70}")
    print(f"RESULTS:")
    print(f"  Companies with scraped history: {total_scraped}")
    print(f"  Companies without bitbo page:   {total_no_page}")
    print(f"  Total entries created:          {total_entries}")
    print(f"  Duplicates skipped (already in): {total_dupe}")
    print(f"  Errors:                         {total_failed}")
    print(f"{'=' * 70}")

    return {
        "scraped": total_scraped,
        "no_page": total_no_page,
        "entries": total_entries,
        "dupe_skipped": total_dupe,
        "failed": total_failed,
    }


if __name__ == "__main__":
    apply = "--apply" in sys.argv

    if not apply:
        print("\n⚠️  DRY RUN MODE — no data will be written.")
        print("   Run with --apply to insert into database.\n")

    result = scrape_all(dry_run=not apply)

    if not apply and result["entries"] > 0:
        print(f"\n💡 To apply, run:")
        print(f"   python scrape_purchase_history.py --apply")
