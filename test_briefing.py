from dotenv import load_dotenv
load_dotenv()
from pro_briefing import _get_market_data, _get_subscriber_position, _build_email_html
from supabase import create_client
import os

sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

# Get ANY subscriber (not just Pro) for testing
res = sb.table('subscribers').select('*').limit(1).execute()
if not res.data:
    print('No subscribers at all')
    exit()

sub = res.data[0]
sub['plan'] = 'pro'  # Fake Pro for preview
print(f"Testing with: {sub['name']} ({sub['email']})")

market = _get_market_data()
if not market:
    print('Could not fetch market data')
    exit()

print(f"BTC: ${market['btc_price']:,.0f}")
print(f"Companies: {len(market['companies'])}")
print(f"Purchases: {len(market['purchases'])}")
print(f"Signals: {len(market['signals'])}")

pos = _get_subscriber_position(sub, market['companies'], market['btc_price'])
print(f"Rank: #{pos['rank']} of {pos['total_corporate']}")

html = _build_email_html(sub, market, pos)
with open('test_briefing.html', 'w', encoding='utf-8') as f:
    f.write(html)
print(f'\nSaved test_briefing.html ({len(html):,} bytes)')
print('Open it in your browser to preview!')