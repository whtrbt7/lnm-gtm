"""
publish_pending_workspaces.py — Publish GTM workspaces that have pending changes.

Scans all AutoOps/SteerCRM location containers, checks each workspace for
uncommitted changes, and publishes them. Used to recover from a partial run
where tags were deleted but the publish step failed.

Usage:
  python publish_pending_workspaces.py
  python publish_pending_workspaces.py --dry-run
"""

import argparse
import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE   = os.path.join(SCRIPT_DIR, 'gtm_id_cache.json')

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
SB_HEADERS   = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'}

TOKEN_MAP = {
    'analytics@leadsnearme.com':  os.path.join(SCRIPT_DIR, 'token_analytics.json'),
    'analytics2@leadsnearme.com': os.path.join(SCRIPT_DIR, 'token_analytics2.json'),
    'reports@leadsnearme.com':    os.path.join(SCRIPT_DIR, 'token_reports.json'),
}
DEFAULT_TOKEN = os.path.join(SCRIPT_DIR, 'token_analytics.json')

_service_cache: dict[str, object] = {}


def get_gtm_service(token_file: str):
    if token_file in _service_cache:
        return _service_cache[token_file]
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    with open(token_file) as f:
        data = json.load(f)
    creds = Credentials(
        token=data.get('token'),
        refresh_token=data.get('refresh_token'),
        token_uri=data.get('token_uri', 'https://oauth2.googleapis.com/token'),
        client_id=data.get('client_id'),
        client_secret=data.get('client_secret'),
        scopes=data.get('scopes'),
    )
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        data['token'] = creds.token
        data['expiry'] = creds.expiry.isoformat() if creds.expiry else None
        with open(token_file, 'w') as f:
            json.dump(data, f, indent=2)
    svc = build('tagmanager', 'v2', credentials=creds)
    _service_cache[token_file] = svc
    return svc


def _call(fn, max_retries=8, base_delay=3.0):
    from googleapiclient.errors import HttpError
    delay = base_delay
    for attempt in range(max_retries):
        try:
            return fn()
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < max_retries - 1:
                print(f'    [retry] HTTP {e.resp.status}, waiting {delay:.0f}s…')
                time.sleep(delay)
                delay = min(delay * 2, 60)
            else:
                raise


def fetch_autoops_locations() -> list[dict]:
    results = []
    for sched in ('autoops', 'steercrm'):
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/locations',
            params={
                'scheduler_type': f'ilike.*{sched}*',
                'select': 'id,name,gtm_id,gtm_account_id,gtm_container_id,gtm_lnm_acct',
                'deleted_at': 'is.null',
            },
            headers=SB_HEADERS, timeout=10,
        )
        r.raise_for_status()
        results.extend(r.json())
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print('Fetching AutoOps/SteerCRM locations…')
    locs = fetch_autoops_locations()

    # Deduplicate by container
    seen: dict[str, dict] = {}
    for loc in locs:
        gtm_id = loc.get('gtm_id')
        if not gtm_id or gtm_id in seen:
            continue
        if not loc.get('gtm_account_id') or not loc.get('gtm_container_id'):
            cache = {}
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE) as f:
                    cache = json.load(f)
            if gtm_id not in cache:
                continue
            loc['gtm_account_id'] = cache[gtm_id]['account_id']
            loc['gtm_container_id'] = cache[gtm_id]['container_id']
        seen[gtm_id] = loc

    print(f'  {len(seen)} unique containers with known IDs\n')

    published = 0
    clean = 0
    errors = 0

    for gtm_id, loc in seen.items():
        acct = str(loc['gtm_account_id'])
        ctr  = str(loc['gtm_container_id'])
        lnm_acct = loc.get('gtm_lnm_acct') or ''
        token_file = TOKEN_MAP.get(lnm_acct, DEFAULT_TOKEN)

        try:
            svc = get_gtm_service(token_file)

            # Get workspace
            ws_list = _call(lambda: svc.accounts().containers().workspaces().list(
                parent=f'accounts/{acct}/containers/{ctr}'
            ).execute()).get('workspace', [])
            if not ws_list:
                print(f'{gtm_id}: no workspace')
                errors += 1
                continue
            ws_id = ws_list[0]['workspaceId']

            # Check for pending changes
            status = _call(lambda: svc.accounts().containers().workspaces().getStatus(
                path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws_id}'
            ).execute())
            changes = status.get('workspaceChange', [])

            if not changes:
                clean += 1
                continue

            change_summary = ', '.join(
                f'{c.get("changeStatus","?")} {list(c.keys() - {"changeStatus"})[0] if len(c) > 1 else "?"}'
                for c in changes[:3]
            )
            print(f'{gtm_id}  ({loc["name"]})  — {len(changes)} pending change(s): {change_summary}')

            if args.dry_run:
                print(f'  [dry-run] Would publish')
                published += 1
                continue

            ver = _call(lambda: svc.accounts().containers().workspaces().create_version(
                path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws_id}',
                body={'name': 'LNM AutoOps Cleanup', 'notes': 'Publish pending workspace changes'},
            ).execute())
            if ver.get('compilerError'):
                print(f'  [error] Compiler error')
                errors += 1
                continue
            vid = ver['containerVersion']['containerVersionId']
            _call(lambda: svc.accounts().containers().versions().publish(
                path=f'accounts/{acct}/containers/{ctr}/versions/{vid}',
            ).execute())
            print(f'  ✓ Published version {vid}')
            published += 1

        except Exception as e:
            print(f'{gtm_id}: [error] {e}')
            errors += 1

    label = 'would publish' if args.dry_run else 'published'
    print(f'\n=== Done: {published} {label}, {clean} already clean, {errors} errors ===')


if __name__ == '__main__':
    main()
