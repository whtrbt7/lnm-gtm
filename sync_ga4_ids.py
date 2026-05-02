"""
sync_ga4_ids.py — Read GA4 measurement IDs from GTM container tags and write
to Supabase (ga4_measurement_id).

Looks up containers from container_index_cache.json (url_index), then reads
the GA4 Configuration tag (type=gaawc) from each workspace to extract the
measurementId (G-XXXXXXXXXX).

Usage:
  python sync_ga4_ids.py                 # dry run — shows matches, no writes
  python sync_ga4_ids.py --apply         # write to Supabase
  python sync_ga4_ids.py --apply --overwrite  # replace existing values too

Auth: uses token.json (GTM scope) — no new API to enable.
Rate limit: 8 req/min (GTM quota is 10 QPM). Expect ~2 min per 10 locations.
"""

import argparse
import json
import os
import re
import time
from typing import Optional

import requests
from dotenv import load_dotenv

from auth import get_gtm_service

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
SUPABASE_HEADERS = {
    'apikey':         SUPABASE_KEY,
    'Authorization':  f'Bearer {SUPABASE_KEY}',
    'Content-Type':   'application/json',
}

INDEX_CACHE_FILE = 'container_index_cache.json'
GTM_ID_CACHE     = 'gtm_id_cache.json'
CALL_INTERVAL    = 7.5   # seconds between GTM API calls (8 QPM safe)


# ── Cache loading ─────────────────────────────────────────────────────────────

def load_url_index() -> dict[str, list]:
    """Returns {domain: [account_id, container_id, gtm_public_id]}"""
    if not os.path.exists(INDEX_CACHE_FILE):
        return {}
    with open(INDEX_CACHE_FILE) as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get('url_index', {})
    return {}


def load_gtm_id_cache() -> dict[str, dict]:
    """Returns {GTM-XXXXX: {account_id, container_id}}"""
    if not os.path.exists(GTM_ID_CACHE):
        return {}
    with open(GTM_ID_CACHE) as f:
        return json.load(f)


# ── Domain helpers ────────────────────────────────────────────────────────────

def normalize_domain(url: str) -> str:
    if not url:
        return ''
    d = re.sub(r'^https?://', '', str(url)).rstrip('/')
    d = re.sub(r'^www\.', '', d)
    return d.lower()


# ── GTM API helpers ───────────────────────────────────────────────────────────

_workspace_cache: dict[str, str] = {}   # "acct/ctr" → workspace_id
_last_call = 0.0


def _throttled_call(fn):
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < CALL_INTERVAL:
        time.sleep(CALL_INTERVAL - elapsed)
    result = fn()
    _last_call = time.time()
    return result


def get_default_workspace(service, account_id: str, container_id: str) -> Optional[str]:
    key = f'{account_id}/{container_id}'
    if key in _workspace_cache:
        return _workspace_cache[key]
    try:
        resp = _throttled_call(
            lambda: service.accounts().containers().workspaces()
                    .list(parent=f'accounts/{account_id}/containers/{container_id}')
                    .execute()
        )
        workspaces = resp.get('workspace', [])
        if not workspaces:
            return None
        ws_id = workspaces[0]['workspaceId']
        _workspace_cache[key] = ws_id
        return ws_id
    except Exception as e:
        print(f'  [warn] workspace lookup failed {account_id}/{container_id}: {e}')
        return None


def get_measurement_id_from_tags(service, account_id: str, container_id: str, workspace_id: str) -> Optional[str]:
    try:
        resp = _throttled_call(
            lambda: service.accounts().containers().workspaces().tags()
                    .list(parent=f'accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}')
                    .execute()
        )
    except Exception as e:
        print(f'  [warn] tag list failed {account_id}/{container_id}/ws{workspace_id}: {e}')
        return None

    for tag in resp.get('tag', []):
        if tag.get('type') != 'gaawc':
            continue
        for param in tag.get('parameter', []):
            if param.get('key') == 'measurementId':
                return param.get('value')
    return None


# ── Supabase ──────────────────────────────────────────────────────────────────

def fetch_locations() -> list[dict]:
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={
            'select':  'id,name,url,gads_cid,gtm_id,ga4_measurement_id',
            'churned': 'eq.false',
        },
        headers=SUPABASE_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def update_location(gads_cid: str, measurement_id: str):
    r = requests.patch(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={'gads_cid': f'eq.{gads_cid}'},
        headers={**SUPABASE_HEADERS, 'Prefer': 'return=minimal'},
        json={'ga4_measurement_id': measurement_id},
        timeout=10,
    )
    r.raise_for_status()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Sync GA4 measurement IDs from GTM tags to Supabase.')
    parser.add_argument('--apply',     action='store_true', help='Write to Supabase (default: dry run)')
    parser.add_argument('--overwrite', action='store_true', help='Replace existing ga4_measurement_id values')
    args = parser.parse_args()

    if not args.apply:
        print('[DRY RUN] Pass --apply to write changes.\n')

    print('Loading caches...')
    url_index   = load_url_index()
    gtm_id_cache = load_gtm_id_cache()
    print(f'  url_index: {len(url_index)} domains  |  gtm_id_cache: {len(gtm_id_cache)} containers')

    print('Fetching locations from Supabase...')
    locations = fetch_locations()
    print(f'  {len(locations)} active locations\n')

    service = get_gtm_service()

    results   = []   # (loc, measurement_id)
    skipped   = []   # already set
    no_cache  = []   # container not in cache
    no_tag    = []   # container found but no GA4 config tag

    for i, loc in enumerate(locations):
        domain = normalize_domain(loc.get('url', ''))
        gtm_id = loc.get('gtm_id', '')
        name   = loc.get('name', '')

        if loc.get('ga4_measurement_id') and not args.overwrite:
            skipped.append(name)
            continue

        # Resolve (account_id, container_id) — try url_index then gtm_id_cache
        account_id = container_id = None

        if domain and domain in url_index:
            entry = url_index[domain]
            account_id, container_id = str(entry[0]), str(entry[1])
        elif gtm_id and gtm_id in gtm_id_cache:
            entry = gtm_id_cache[gtm_id]
            account_id  = str(entry.get('account_id', ''))
            container_id = str(entry.get('container_id', ''))

        if not account_id or not container_id:
            no_cache.append((name, domain or gtm_id))
            continue

        print(f'[{i+1}/{len(locations)}] {name[:45]:<45} container={container_id}')

        ws_id = get_default_workspace(service, account_id, container_id)
        if not ws_id:
            no_tag.append((name, 'no workspace'))
            continue

        m_id = get_measurement_id_from_tags(service, account_id, container_id, ws_id)
        if not m_id:
            no_tag.append((name, 'no GA4 config tag'))
            continue

        print(f'  → {m_id}')
        results.append((loc, m_id))

    # ── Summary ───────────────────────────────────────────────────────────────

    print(f'\n{"─"*60}')
    print(f'  Found measurement IDs  : {len(results)}')
    print(f'  Already set (skipped)  : {len(skipped)}')
    print(f'  Not in cache           : {len(no_cache)}')
    print(f'  No GA4 config tag      : {len(no_tag)}')
    print(f'{"─"*60}')

    if no_cache:
        print(f'\nNot in cache (need --account-id or manual entry):')
        for name, key in no_cache[:20]:
            print(f'  {name[:45]:<45}  {key}')
        if len(no_cache) > 20:
            print(f'  ... and {len(no_cache) - 20} more')

    if no_tag:
        print(f'\nContainer found but no GA4 config tag:')
        for name, reason in no_tag[:20]:
            print(f'  {name[:45]:<45}  ({reason})')

    # ── Apply ─────────────────────────────────────────────────────────────────

    if args.apply and results:
        print(f'\nWriting {len(results)} updates to Supabase...')
        ok = fail = 0
        for loc, m_id in results:
            try:
                update_location(loc['gads_cid'], m_id)
                ok += 1
            except Exception as e:
                print(f'  [error] {loc["name"]}: {e}')
                fail += 1
        print(f'  Done. {ok} updated, {fail} failed.')
    elif not args.apply and results:
        print(f'\nRun with --apply to write {len(results)} changes.')


if __name__ == '__main__':
    main()
