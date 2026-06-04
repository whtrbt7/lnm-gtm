"""Export all GTM IDs with their website URLs and live script status."""
import csv, os, sys, requests
from dotenv import load_dotenv
load_dotenv()

SB  = os.environ.get('SUPABASE_URL', 'https://supabase.alexanderchiu.com')
KEY = os.environ['SUPABASE_SERVICE_KEY']
H   = {'apikey': KEY, 'Authorization': f'Bearer {KEY}'}

rows, offset = [], 0
while True:
    r = requests.get(f'{SB}/rest/v1/locations',
        params={
            'select': 'name,gtm_id,url,gtm_connected,gtm_container_status,gtm_script_verified_at,gtm_injected_at',
            'gtm_id': 'not.is.null',
            'deleted_at': 'is.null',
            'offset': offset,
            'limit': 1000,
        },
        headers=H, timeout=15)
    r.raise_for_status()
    batch = r.json()
    rows.extend(batch)
    if len(batch) < 1000:
        break
    offset += 1000

out = '/tmp/gtm_urls.csv'
with open(out, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['gtm_id', 'location_name', 'url', 'gtm_connected', 'gtm_container_status', 'gtm_script_verified_at', 'gtm_injected_at'])
    for row in sorted(rows, key=lambda r: (r.get('gtm_id') or '', r.get('url') or '')):
        w.writerow([
            row.get('gtm_id', ''),
            row.get('name', ''),
            row.get('url', ''),
            row.get('gtm_connected', ''),
            row.get('gtm_container_status', ''),
            row.get('gtm_script_verified_at', ''),
            row.get('gtm_injected_at', ''),
        ])

print(f'rows={len(rows)} written={out}')
