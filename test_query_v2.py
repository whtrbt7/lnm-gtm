import os
import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']

SUPABASE_HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
}

gads_cid = '1404487674'
select = 'id,name,url,websites:websites!websites_location_id_fkey(pixel_meta)'
params = {'gads_cid': f'eq.{gads_cid}', 'select': select}
r = requests.get(
    f'{SUPABASE_URL}/rest/v1/locations',
    params=params,
    headers=SUPABASE_HEADERS,
    timeout=10,
)
print(f'Status: {r.status_code}')
print(f'Body: {r.text}')
