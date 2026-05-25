"""
One-shot: update Stripe product descriptions + statement descriptors to
match the trader-led copy from [[stripe_crisp_copy_pending]].

Without this, Stripe Checkout still describes the pre-pivot product
(workflow tool, board-ready PDF, proposal wizard) — customer trust
erodes at the exact moment they're choosing to pay. The strategic
review at 2026-05-21 flagged this as a Trivial-effort fix that's been
sitting un-done.

DESIGN
======
Lists every Product in the Stripe account, auto-matches Pro/Team/
Enterprise by name (case-insensitive), and shows what would change.
On --apply, updates description + statement_descriptor.

Crisp trigger messages can NOT be updated via this script (Crisp's API
requires plugin tokens not commonly available, and trigger-message
editing is UI-only). Crisp copy remains a manual paste — see the
"Crisp manual checklist" section printed at the end.

Usage:
    pip install stripe
    set STRIPE_SECRET_KEY=sk_live_...   (PowerShell: $env:STRIPE_SECRET_KEY="sk_live_...")
    python scripts/update_stripe_product_copy.py            # dry-run, shows diff
    python scripts/update_stripe_product_copy.py --apply    # writes

Heredoc-quoted strings below are reproduced verbatim from
[[stripe_crisp_copy_pending]] memory. If/when copy is changed,
update both this script and the memory together.
"""
from __future__ import annotations

import os
import sys

try:
    import stripe
except ImportError:
    sys.exit("Missing dep: pip install stripe")

key = os.environ.get("STRIPE_SECRET_KEY")
if not key:
    sys.exit("STRIPE_SECRET_KEY env var not set. Use a LIVE or TEST key.")

stripe.api_key = key
apply = "--apply" in sys.argv
mode = "LIVE" if key.startswith("sk_live_") else "TEST" if key.startswith("sk_test_") else "UNKNOWN"

print(f"Mode: {mode}  |  {'APPLYING' if apply else 'DRY-RUN'}")
print("=" * 72)


# ─── Target copy (from memory/stripe_crisp_copy_pending.md) ──────────────

PLAN_COPY = {
    "pro": {
        "match_keywords": ["pro"],
        "description": (
            "Treasury Signal Intelligence Pro — Sub-60-second alerts on every "
            "BTC treasury 8-K across ~200 public companies (US, Japan, Korea, EU). "
            "Catches the filing the moment it hits EDGAR/DART/EDINET — before the "
            "news reaches Twitter. Claude-scored excerpts from 8-K, 10-Q, 10-K "
            "filings (skip the PDF, read the 3 sentences that matter). "
            "Pre-announcement signals across 7 data streams (filings + on-chain + "
            "social + news). Real-time delivery via email, Telegram, Slack. "
            "REST API + Google Sheets add-on. 7-day free trial. Cancel anytime."
        ),
        "statement_descriptor": "TSI PRO",
    },
    "team": {
        "match_keywords": ["team"],
        "description": (
            "Treasury Signal Intelligence Team — Everything in Pro for up to 5 "
            "seats. Team-shared watchlists, Slack channel delivery of high-impact "
            "filing excerpts (per-team threshold + cooldown), CSV export, saved "
            "views, and audit log. Built for hedge fund desks and IR teams "
            "tracking the BTC treasury tape."
        ),
        "statement_descriptor": "TSI TEAM",
    },
    "enterprise": {
        "match_keywords": ["enterprise"],
        "description": (
            "Treasury Signal Intelligence Enterprise — Custom-priced, sales-led. "
            "Includes Team plus negotiated API rate limits, SLA, dedicated "
            "support, custom data sources, and (when scoped) SSO. Contact "
            "contact@quantedgeriskadvisory.com."
        ),
        "statement_descriptor": "TSI ENT",
    },
}


def list_products() -> list:
    """Return all products (active first). Paginates automatically."""
    out = []
    for p in stripe.Product.list(active=True, limit=100).auto_paging_iter():
        out.append(p)
    return out


def auto_match(products: list) -> dict:
    """Return {plan_key: matching_stripe_product or None}."""
    matched = {}
    for plan_key, spec in PLAN_COPY.items():
        keywords = spec["match_keywords"]
        candidates = []
        for p in products:
            name_lower = (p.name or "").lower()
            if any(kw in name_lower for kw in keywords):
                candidates.append(p)
        if not candidates:
            matched[plan_key] = None
        elif len(candidates) == 1:
            matched[plan_key] = candidates[0]
        else:
            # Multiple matches — prefer exact name match, else first
            exact = [c for c in candidates if (c.name or "").lower() == plan_key]
            matched[plan_key] = (exact[0] if exact else candidates[0])
            print(f"  !! {plan_key}: {len(candidates)} candidates found, picked '{matched[plan_key].name}'")
    return matched


def fmt_short(s, n=80):
    s = (s or "").replace("\n", " ").strip()
    return s[:n] + ("..." if len(s) > n else "")


def main():
    print("Listing Stripe products...")
    products = list_products()
    print(f"Found {len(products)} active products")
    print()

    matched = auto_match(products)

    actions = []
    for plan_key, spec in PLAN_COPY.items():
        product = matched.get(plan_key)
        if not product:
            print(f"  [{plan_key.upper()}] NO MATCH — create the product manually first, then re-run")
            continue
        cur_desc = product.description or ""
        cur_sd = (getattr(product, "statement_descriptor", "") or "")
        new_desc = spec["description"]
        new_sd = spec["statement_descriptor"]

        desc_diff = cur_desc.strip() != new_desc.strip()
        sd_diff = cur_sd.strip().upper() != new_sd.strip().upper()

        print(f"[{plan_key.upper()}]  {product.id}  '{product.name}'")
        print(f"  description: {'CHANGE' if desc_diff else 'no change'}")
        if desc_diff:
            print(f"    OLD: {fmt_short(cur_desc, 100)}")
            print(f"    NEW: {fmt_short(new_desc, 100)}")
        print(f"  statement_descriptor: {'CHANGE' if sd_diff else 'no change'}  ({cur_sd!r} -> {new_sd!r})")
        print()

        if desc_diff or sd_diff:
            actions.append((product.id, plan_key, new_desc, new_sd))

    if not actions:
        print("Nothing to update — Stripe already matches.")
        _print_crisp_checklist()
        return

    if not apply:
        print(f"=> {len(actions)} product(s) need updating.")
        print("   Re-run with --apply to write to Stripe.")
        _print_crisp_checklist()
        return

    print("Applying...")
    ok = fail = 0
    for product_id, plan_key, desc, sd in actions:
        try:
            stripe.Product.modify(product_id, description=desc, statement_descriptor=sd)
            print(f"  OK   {product_id} ({plan_key})")
            ok += 1
        except Exception as e:
            print(f"  FAIL {product_id} ({plan_key}): {e}")
            fail += 1
    print()
    print(f"Done: {ok} updated, {fail} failed.")
    _print_crisp_checklist()


def _print_crisp_checklist():
    print()
    print("=" * 72)
    print("CRISP: still manual (no programmatic API for trigger messages).")
    print("Paste the following into Crisp dashboard -> Plugins -> Triggers")
    print("=" * 72)
    print()
    print("[Off-hours welcome]")
    print()
    print("👋 Hey — Treasury Signal Intelligence support here.")
    print()
    print("I'm usually around weekdays 9am-6pm ET. Drop your question and I'll")
    print("reply first thing in the morning.")
    print()
    print("Quick links while you wait:")
    print("• /filings — Claude-scored 8-K excerpts firing every cycle")
    print("• /docs — REST API + Google Sheets add-on")
    print("• /signals — pre-announcement signal feed (experimental)")
    print()
    print("What can I help you with?")
    print()
    print("---")
    print()
    print("[New-signup welcome]")
    print()
    print("Welcome to TSI Pro 👋 — your 7-day trial is live. Three things most")
    print("users do first:")
    print("1. Add the tickers you trade to your watchlist (alerts fire only for those)")
    print("2. Connect Slack if you want alerts fastest (email and Telegram also active)")
    print("3. Open /filings — the Claude-scored 8-K excerpts firing every cycle")
    print()
    print("Reply here with any question, or hit /docs for the full API guide.")


if __name__ == "__main__":
    main()
