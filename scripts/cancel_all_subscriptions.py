"""
One-shot: cancel every active Stripe subscription on the account.

Usage:
    pip install stripe
    set STRIPE_SECRET_KEY=sk_live_...   (PowerShell: $env:STRIPE_SECRET_KEY="sk_live_...")
    python scripts/cancel_all_subscriptions.py            # dry-run, prints what it would cancel
    python scripts/cancel_all_subscriptions.py --apply    # actually cancels

Run twice if you also want to wipe Test mode:
    set STRIPE_SECRET_KEY=sk_test_...
    python scripts/cancel_all_subscriptions.py --apply

Cancels immediately (not at period end). Does not refund anything.
"""
import os
import sys

import stripe

key = os.environ.get("STRIPE_SECRET_KEY")
if not key:
    sys.exit("STRIPE_SECRET_KEY env var not set")

stripe.api_key = key
apply = "--apply" in sys.argv
mode = "LIVE" if key.startswith("sk_live_") else "TEST"

print(f"Mode: {mode}  |  {'APPLYING' if apply else 'DRY-RUN'}")
print("-" * 60)

count = 0
for sub in stripe.Subscription.list(status="active", limit=100).auto_paging_iter():
    customer_email = ""
    try:
        customer_email = stripe.Customer.retrieve(sub.customer).email or ""
    except Exception:
        pass
    print(f"{sub.id}  {customer_email:<40}  {sub.items.data[0].price.id}")
    if apply:
        stripe.Subscription.delete(sub.id)
    count += 1

print("-" * 60)
print(f"{'Cancelled' if apply else 'Would cancel'}: {count} subscription(s)")
if not apply:
    print("\nRe-run with --apply to actually cancel.")
