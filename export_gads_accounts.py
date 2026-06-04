"""Export all GAds accounts with CID, location count, URLs, and names to CSV."""
import csv, os, sys, requests
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv()

SB  = os.environ.get('SUPABASE_URL', 'https://supabase.alexanderchiu.com')
KEY = os.environ['SUPABASE_SERVICE_KEY']
H   = {'apikey': KEY, 'Authorization': f'Bearer {KEY}'}

rows, offset = [], 0
while True:
    r = requests.get(f'{SB}/rest/v1/locations',
        params={'select': 'gads_cid,url,name', 'gads_cid': 'not.is.null',
                'deleted_at': 'is.null', 'offset': offset, 'limit': 1000},
        headers=H, timeout=15)
    r.raise_for_status()
    batch = r.json()
    rows.extend(batch)
    if len(batch) < 1000:
        break
    offset += 1000

accounts: dict[str, dict] = defaultdict(lambda: {'urls': set(), 'names': set()})
for row in rows:
    cid  = str(row['gads_cid']).strip()
    url  = (row.get('url') or '').strip().rstrip('/')
    name = (row.get('name') or '').strip()
    if cid:
        if url:  accounts[cid]['urls'].add(url)
        if name: accounts[cid]['names'].add(name)

out = '/tmp/gads_accounts.csv'
with open(out, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['gads_cid', 'location_count', 'urls', 'location_names'])
    for cid, data in sorted(accounts.items()):
        urls  = ' | '.join(sorted(data['urls']))
        names = ' | '.join(sorted(data['names']))
        w.writerow([cid, len(data['names']), urls, names])

print(f'rows={len(rows)} unique_cids={len(accounts)} written={out}')
