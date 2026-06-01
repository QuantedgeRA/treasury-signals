"""
Draft / one-shot: create the Team and Enterprise Stripe products so the
trader-led copy in [[stripe_crisp_copy_pending]] can be sold via Checkout.

CONTEXT
=======
As of 2026-06-01 only the Pro product exists in Stripe (its copy was
updated by scripts/update_stripe_product_copy.py). Team and Enterprise
are referenced in the dashboard env scaffold
(STRIPE_PRICE_ID_TEAM_MONTHLY, etc.) but the products themselves were
never created — so update_stripe_product_copy.py reports them NO MATCH
and they can't be checked out.

This script creates them:
  - Team:       product + $99/mo recurring USD price, descriptor "TSI TEAM"
  - Enterprise: product ONLY (sales-led, custom-priced — no price object),
                descriptor "TSI ENT"

It is IDEMPOTENT: if a product whose name contains the tier keyword
already exists (active), it is reused, not duplicated. A monthly price is
only created if the matched Team product has no active $99/mo USD price.

Copy is reproduced verbatim from [[stripe_crisp_copy_pending]] and matches
PLAN_COPY in update_stripe_product_copy.py. Change all three together.

Usage:
    pip install stripe
    set STRIPE_SECRET_KEY=sk_live_...   (PS: $env:STRIPE_SECRET_KEY="sk_live_...")
    python scripts/create_team_enterprise_products.py            # dry-run
    python scripts/create_team_enterprise_products.py --apply    # creates

After --apply, paste the printed price IDs into the dashboard's
.env.local (and Vercel project env):
    STRIPE_PRICE_ID_TEAM_MONTHLY=price_...
Enterprise stays sales-led — no price ID, contact-sales CTA only.
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


# ─── Target spec (copy from memory/stripe_crisp_copy_pending.md) ─────────
TEAM = {
    "match_keywords": ["team"],
    "name": "Treasury Signal Intelligence Team",
    "description": (
        "Treasury Signal Intelligence Team — Everything in Pro for up to 5 "
        "seats. Team-shared watchlists, Slack channel delivery of high-impact "
        "filing excerpts (per-team threshold + cooldown), CSV export, saved "
        "views, and audit log. Built for hedge fund desks and IR teams "
        "tracking the BTC treasury tape."
    ),
    "statement_descriptor": "TSI TEAM",
    "unit_amount": 9900,          # $99.00 / month
    "currency": "usd",
    "interval": "month",
}
ENTERPRISE = {
    "match_keywords": ["enterprise"],
    "name": "Treasury Signal Intelligence Enterprise",
    "description": (
        "Treasury Signal Intelligence Enterprise — Custom-priced, sales-led. "
        "Includes Team plus negotiated API rate limits, SLA, dedicated "
        "support, custom data sources, and (when scoped) SSO. Contact "
        "contact@quantedgeriskadvisory.com."
    ),
    "statement_descriptor": "TSI ENT",
    # No price — sales-led / custom-quoted.
}


def all_products() -> list:
    return list(stripe.Product.list(active=True, limit=100).auto_paging_iter())


def find_by_keywords(products: list, keywords: list):
    for p in products:
        name_lower = (p.name or "").lower()
        if any(kw in name_lower for kw in keywords):
            return p
    return None


def has_matching_price(product_id: str, unit_amount: int, currency: str, interval: str):
    for pr in stripe.Price.list(product=product_id, active=True, limit=100).auto_paging_iter():
        if (pr.unit_amount == unit_amount and pr.currency == currency
                and pr.recurring and pr.recurring.interval == interval):
            return pr
    return None


def main():
    print("Listing existing products...")
    products = all_products()
    print(f"Found {len(products)} active products")
    print()

    created_env_lines = []

    # ── Team ────────────────────────────────────────────────────────────
    print("[TEAM]")
    team_product = find_by_keywords(products, TEAM["match_keywords"])
    if team_product:
        print(f"  product EXISTS: {team_product.id} '{team_product.name}' (reuse)")
    else:
        print(f"  product MISSING -> would CREATE '{TEAM['name']}' (descriptor {TEAM['statement_descriptor']})")

    existing_price = None
    if team_product:
        existing_price = has_matching_price(
            team_product.id, TEAM["unit_amount"], TEAM["currency"], TEAM["interval"]
        )
    if existing_price:
        print(f"  price EXISTS: {existing_price.id} (${TEAM['unit_amount']/100:.0f}/{TEAM['interval']}) (reuse)")
    else:
        print(f"  price MISSING -> would CREATE ${TEAM['unit_amount']/100:.0f}/{TEAM['interval']} {TEAM['currency'].upper()}")

    if apply:
        if not team_product:
            team_product = stripe.Product.create(
                name=TEAM["name"],
                description=TEAM["description"],
                statement_descriptor=TEAM["statement_descriptor"],
            )
            print(f"  CREATED product {team_product.id}")
        else:
            # keep copy in sync on reuse
            stripe.Product.modify(
                team_product.id,
                description=TEAM["description"],
                statement_descriptor=TEAM["statement_descriptor"],
            )
        if not existing_price:
            existing_price = stripe.Price.create(
                product=team_product.id,
                unit_amount=TEAM["unit_amount"],
                currency=TEAM["currency"],
                recurring={"interval": TEAM["interval"]},
            )
            print(f"  CREATED price {existing_price.id}")
        created_env_lines.append(f"STRIPE_PRICE_ID_TEAM_MONTHLY={existing_price.id}")
    print()

    # ── Enterprise (product only, no price) ─────────────────────────────
    print("[ENTERPRISE]  (sales-led — product only, no price)")
    ent_product = find_by_keywords(products, ENTERPRISE["match_keywords"])
    if ent_product:
        print(f"  product EXISTS: {ent_product.id} '{ent_product.name}' (reuse)")
    else:
        print(f"  product MISSING -> would CREATE '{ENTERPRISE['name']}' (descriptor {ENTERPRISE['statement_descriptor']})")

    if apply:
        if not ent_product:
            ent_product = stripe.Product.create(
                name=ENTERPRISE["name"],
                description=ENTERPRISE["description"],
                statement_descriptor=ENTERPRISE["statement_descriptor"],
            )
            print(f"  CREATED product {ent_product.id}")
        else:
            stripe.Product.modify(
                ent_product.id,
                description=ENTERPRISE["description"],
                statement_descriptor=ENTERPRISE["statement_descriptor"],
            )
    print()

    print("=" * 72)
    if not apply:
        print("DRY-RUN — nothing written. Re-run with --apply to create.")
    else:
        print("DONE. Paste into dashboard .env.local AND Vercel project env:")
        for ln in created_env_lines:
            print("    " + ln)
        print("Enterprise: sales-led, no price ID — keep the contact-sales CTA.")


if __name__ == "__main__":
    main()
