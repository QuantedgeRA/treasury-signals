from dotenv import load_dotenv
load_dotenv()
import os
from supabase import create_client

url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_KEY')
print('KEY starts with:', key[:15] if key else 'MISSING')
print('KEY length:', len(key) if key else 0)

sb = create_client(url, key)

# Test 1: Can we read companies?
res = sb.table('treasury_companies').select('company').limit(1).execute()
print('Companies readable:', len(res.data) > 0)

# Test 2: Can we read subscribers?
res2 = sb.table('subscribers').select('email').limit(1).execute()
print('Subscribers readable:', len(res2.data) > 0)
print('Subscribers data:', res2.data)