"""
scenario_calculator.py — What-If Scenario Modeling
-----------------------------------------------------
Interactive calculator that lets a CEO model:
"If we buy X BTC at $Y, what happens?"

Outputs:
- New leaderboard rank (before vs after)
- Total holdings and value
- Cost breakdown (new purchase + existing)
- P&L projections at 5 different BTC price scenarios
- Companies they'd overtake
- Companies that would still be ahead

Usage:
    from scenario_calculator import calculate_scenario

    result = calculate_scenario(
        subscriber_email="ceo@company.com",
        btc_to_buy=500,
        buy_price=72000,
        current_btc_price=72000,
        leaderboard_companies=companies,
    )
"""

from logger import get_logger

logger = get_logger(__name__)


def calculate_scenario(subscriber_email, btc_to_buy, buy_price, current_btc_price,
                       leaderboard_companies, subscriber_profile=None):
    """
    Calculate the full impact of a hypothetical BTC purchase.

    Args:
        subscriber_email: Subscriber's email
        btc_to_buy: Number of BTC to buy in this scenario
        buy_price: Price per BTC for the hypothetical purchase
        current_btc_price: Current live BTC price (for valuation)
        leaderboard_companies: Current leaderboard data
        subscriber_profile: Subscriber profile dict (optional, fetched if not provided)

    Returns:
        Dict with before/after analysis, P&L projections, rank changes, etc.
    """

    # Get subscriber profile
    if not subscriber_profile:
        try:
            from subscriber_manager import subscribers
            subscriber_profile = subscribers.get_by_email(subscriber_email)
        except Exception as e:
            logger.error(f"Could not load subscriber for scenario: {e}")
            return None

    if not subscriber_profile:
        return None

    # Current state
    current_btc = float(subscriber_profile.get("btc_holdings", 0))
    current_avg_price = float(subscriber_profile.get("avg_purchase_price", 0))
    current_total_cost = float(subscriber_profile.get("total_invested_usd", 0))
    company_name = subscriber_profile.get("company_name", "Your Company")
    ticker = subscriber_profile.get("ticker", "")

    # New state after purchase
    new_btc = current_btc + btc_to_buy
    purchase_cost = btc_to_buy * buy_price
    new_total_cost = current_total_cost + purchase_cost

    # New average price (weighted)
    if new_btc > 0:
        new_avg_price = new_total_cost / new_btc
    else:
        new_avg_price = 0

    # Current values
    current_value = current_btc * current_btc_price
    new_value = new_btc * current_btc_price

    # Current P&L
    current_pnl = current_value - current_total_cost if current_total_cost > 0 else 0
    current_pnl_pct = (current_pnl / current_total_cost * 100) if current_total_cost > 0 else 0

    # New P&L (at current BTC price)
    new_pnl = new_value - new_total_cost if new_total_cost > 0 else 0
    new_pnl_pct = (new_pnl / new_total_cost * 100) if new_total_cost > 0 else 0

    # Get corporate leaderboard (exclude governments)
    corporate = [c for c in leaderboard_companies if not c.get("is_government") and c.get("btc_holdings", 0) > 0]
    corporate.sort(key=lambda x: x.get("btc_holdings", 0), reverse=True)

    # Current rank
    current_rank = len(corporate) + 1
    for i, c in enumerate(corporate):
        if current_btc >= c.get("btc_holdings", 0):
            current_rank = i + 1
            break

    # New rank
    new_rank = len(corporate) + 1
    for i, c in enumerate(corporate):
        if new_btc >= c.get("btc_holdings", 0):
            new_rank = i + 1
            break

    ranks_gained = current_rank - new_rank

    # Companies overtaken
    companies_overtaken = []
    for c in corporate:
        c_btc = c.get("btc_holdings", 0)
        if c_btc > current_btc and c_btc <= new_btc:
            companies_overtaken.append({
                "company": c["company"],
                "ticker": c.get("ticker", ""),
                "btc_holdings": c_btc,
                "rank": c.get("rank", 0),
            })

    # Companies still ahead after purchase
    still_ahead = []
    for c in corporate:
        c_btc = c.get("btc_holdings", 0)
        if c_btc > new_btc:
            still_ahead.append({
                "company": c["company"],
                "ticker": c.get("ticker", ""),
                "btc_holdings": c_btc,
                "gap": c_btc - new_btc,
                "rank": c.get("rank", 0),
            })
    still_ahead = still_ahead[-3:]  # Closest 3 above

    # Next rank gap after purchase
    next_rank_gap = 0
    if new_rank > 1:
        for c in corporate:
            if c.get("btc_holdings", 0) > new_btc:
                next_rank_gap = c["btc_holdings"] - new_btc
        # More precisely: the company at new_rank - 1
        if new_rank - 2 >= 0 and new_rank - 2 < len(corporate):
            next_rank_gap = corporate[new_rank - 2]["btc_holdings"] - new_btc

    # P&L projections at different BTC prices
    price_scenarios = [
        {"label": "Bear Case (-30%)", "price": round(current_btc_price * 0.7)},
        {"label": "Moderate Dip (-15%)", "price": round(current_btc_price * 0.85)},
        {"label": "Current Price", "price": round(current_btc_price)},
        {"label": "Moderate Rally (+25%)", "price": round(current_btc_price * 1.25)},
        {"label": "Bull Case (+50%)", "price": round(current_btc_price * 1.5)},
        {"label": "Moon (+100%)", "price": round(current_btc_price * 2.0)},
    ]

    projections = []
    for scenario in price_scenarios:
        projected_value = new_btc * scenario["price"]
        projected_pnl = projected_value - new_total_cost
        projected_pnl_pct = (projected_pnl / new_total_cost * 100) if new_total_cost > 0 else 0

        projections.append({
            "label": scenario["label"],
            "btc_price": scenario["price"],
            "portfolio_value": projected_value,
            "pnl_usd": projected_pnl,
            "pnl_pct": round(projected_pnl_pct, 1),
        })

    # Break-even price
    break_even_price = round(new_total_cost / new_btc) if new_btc > 0 else 0

    return {
        "company_name": company_name,
        "ticker": ticker,

        # Purchase details
        "btc_to_buy": btc_to_buy,
        "buy_price": buy_price,
        "purchase_cost": purchase_cost,
        "purchase_cost_m": round(purchase_cost / 1_000_000, 1),

        # Before
        "before": {
            "btc_holdings": current_btc,
            "total_cost": current_total_cost,
            "avg_price": current_avg_price,
            "value": current_value,
            "value_m": round(current_value / 1_000_000, 1),
            "pnl": current_pnl,
            "pnl_pct": round(current_pnl_pct, 1),
            "rank": current_rank,
        },

        # After
        "after": {
            "btc_holdings": new_btc,
            "total_cost": new_total_cost,
            "avg_price": round(new_avg_price),
            "value": new_value,
            "value_m": round(new_value / 1_000_000, 1),
            "pnl": new_pnl,
            "pnl_pct": round(new_pnl_pct, 1),
            "rank": new_rank,
        },

        # Rank impact
        "ranks_gained": ranks_gained,
        "companies_overtaken": companies_overtaken,
        "still_ahead": still_ahead,
        "next_rank_gap": next_rank_gap,
        "total_companies": len(corporate),

        # Projections
        "projections": projections,
        "break_even_price": break_even_price,
        "current_btc_price": current_btc_price,
    }


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Scenario Calculator — testing...")

    # Simulate a scenario without real data
    mock_leaderboard = [
        {"company": "Strategy", "ticker": "MSTR", "btc_holdings": 499096, "rank": 1},
        {"company": "MARA", "ticker": "MARA", "btc_holdings": 46374, "rank": 2},
        {"company": "Riot", "ticker": "RIOT", "btc_holdings": 19223, "rank": 3},
        {"company": "Tesla", "ticker": "TSLA", "btc_holdings": 11509, "rank": 4},
        {"company": "Semler", "ticker": "SMLR", "btc_holdings": 3192, "rank": 5},
        {"company": "Metaplanet", "ticker": "3350.T", "btc_holdings": 3050, "rank": 6},
    ]

    mock_profile = {
        "company_name": "Test Corp",
        "ticker": "TEST",
        "btc_holdings": 2000,
        "avg_purchase_price": 50000,
        "total_invested_usd": 100000000,
        "email": "test@test.com",
    }

    result = calculate_scenario(
        subscriber_email="test@test.com",
        btc_to_buy=1500,
        buy_price=72000,
        current_btc_price=72000,
        leaderboard_companies=mock_leaderboard,
        subscriber_profile=mock_profile,
    )

    if result:
        print(f"\n{'='*50}")
        print(f"  SCENARIO: Buy {result['btc_to_buy']:,} BTC at ${result['buy_price']:,}")
        print(f"{'='*50}")
        print(f"  Cost: ${result['purchase_cost_m']}M")
        print(f"  Before: {result['before']['btc_holdings']:,.0f} BTC (#{result['before']['rank']})")
        print(f"  After:  {result['after']['btc_holdings']:,.0f} BTC (#{result['after']['rank']})")
        print(f"  Ranks gained: {result['ranks_gained']}")
        print(f"  Overtaken: {[c['company'] for c in result['companies_overtaken']]}")
        print(f"  Break-even: ${result['break_even_price']:,}")
        print(f"\n  Projections:")
        for p in result['projections']:
            print(f"    {p['label']}: ${p['btc_price']:,} → ${p['portfolio_value']/1_000_000:,.1f}M ({p['pnl_pct']:+.1f}%)")

    logger.info("Scenario Calculator test complete")
