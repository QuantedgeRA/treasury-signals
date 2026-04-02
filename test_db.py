# test_db.py
from dotenv import load_dotenv
load_dotenv()
import os
from supabase import create_client

url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_KEY')
print('URL:', url[:30] if url else 'MISSING')
print('KEY:', key[:20] if key else 'MISSING')

sb = create_client(url, key)
res = sb.table('treasury_companies').select('company, btc_holdings').gt('btc_holdings', 0).order('btc_holdings', ascending=False).limit(3).execute()
print('Companies:', len(res.data))
for c in res.data:
    print(' ', c['company'], c['btc_holdings'])

snap = sb.table('leaderboard_snapshots').select('btc_price').order('snapshot_date', ascending=False).limit(1).execute()
print('BTC price:', snap.data[0]['btc_price'] if snap.data else 'NONE')