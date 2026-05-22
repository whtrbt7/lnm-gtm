"""
fix_autoops_tags.py — Delete "GA4 - Event - ao-appointment-booked" from any GTM
container that already has "GA4 - Event - AutoOps Events".

Targets all Supabase locations with scheduler_type ilike autoops or steercrm
that have a GTM container configured. Deduplicates by container so shared
containers (MSO) are only processed once.

Usage:
  python fix_autoops_tags.py
  python fix_autoops_tags.py --dry-run
  python fix_autoops_tags.py --token-file token_analytics2.json
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
SB_HEADERS   = {
    'apikey':        SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
}

OLD_TAG = 'GA4 - Event - ao-appointment-booked'
NEW_TAG = 'GA4 - Event - AutoOps Events'


# ── Supabase ──────────────────────────────────────────────────────────────────

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
            headers=SB_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        results.extend(r.json())
    return results


# ── GTM Auth ──────────────────────────────────────────────────────────────────

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


# ── GTM helpers ───────────────────────────────────────────────────────────────

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


def _seed_cache(gtm_id, account_id, container_id):
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            cache = json.load(f)
    cache[gtm_id] = {'account_id': str(account_id), 'container_id': str(container_id)}
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)


def resolve_container(service, gtm_id, account_id, container_id):
    """Return (acct_id, ctr_id), seeding cache."""
    if account_id and container_id:
        _seed_cache(gtm_id, account_id, container_id)
        return str(account_id), str(container_id)
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            cache = json.load(f)
    if gtm_id in cache:
        c = cache[gtm_id]
        return str(c['account_id']), str(c['container_id'])
    raise RuntimeError(f'{gtm_id} not in Supabase or cache — run setup_tags.py first')


def get_workspace(service, acct, ctr):
    ws = _call(lambda: service.accounts().containers().workspaces().list(
        parent=f'accounts/{acct}/containers/{ctr}'
    ).execute()).get('workspace', [])
    if not ws:
        raise RuntimeError('No workspace')
    return ws[0]['workspaceId']


def list_tags(service, acct, ctr, ws):
    resp = _call(lambda: service.accounts().containers().workspaces().tags().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())
    return {t['name']: t['tagId'] for t in resp.get('tag', [])}


def delete_tag(service, acct, ctr, ws, tag_id):
    _call(lambda: service.accounts().containers().workspaces().tags().delete(
        path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}/tags/{tag_id}'
    ).execute())


def publish_version(service, acct, ctr, ws, note):
    ver = _call(lambda: service.accounts().containers().workspaces().create_version(
        path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}',
        body={'name': 'LNM AutoOps Cleanup', 'notes': note},
    ).execute())
    if ver.get('compilerError'):
        raise RuntimeError('GTM compiler error')
    vid = ver['containerVersion']['containerVersionId']
    _call(lambda: service.accounts().containers().versions().publish(
        path=f'accounts/{acct}/containers/{ctr}/versions/{vid}',
    ).execute())
    return vid


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run',    action='store_true')
    parser.add_argument('--token-file', default=None,
                        help='Default token file; overridden per-container by gtm_lnm_acct')
    args = parser.parse_args()

    TOKEN_MAP = {
        'analytics@leadsnearme.com':  os.path.join(SCRIPT_DIR, 'token_analytics.json'),
        'analytics2@leadsnearme.com': os.path.join(SCRIPT_DIR, 'token_analytics2.json'),
        'reports@leadsnearme.com':    os.path.join(SCRIPT_DIR, 'token_reports.json'),
        'ga4@leadsnearme.com':        os.path.join(SCRIPT_DIR, 'token_ga4.json'),
    }
    default_token = args.token_file or os.path.join(SCRIPT_DIR, 'token_analytics.json')

    print('Fetching AutoOps/SteerCRM locations from Supabase…')
    locs = fetch_autoops_locations()
    print(f'  {len(locs)} location(s) found\n')

    # Deduplicate by GTM container — shared containers only processed once
    seen_containers: dict[str, list[str]] = {}  # gtm_id → [location names]
    ordered: list[dict] = []
    for loc in locs:
        gtm_id = loc.get('gtm_id')
        if not gtm_id:
            print(f'  [skip] {loc["name"]} — no gtm_id')
            continue
        if gtm_id in seen_containers:
            seen_containers[gtm_id].append(loc['name'])
        else:
            seen_containers[gtm_id] = [loc['name']]
            ordered.append(loc)

    print(f'  {len(ordered)} unique container(s) to check\n')

    fixed = 0
    skipped = 0

    for loc in ordered:
        gtm_id   = loc['gtm_id']
        names    = seen_containers[gtm_id]
        lnm_acct = loc.get('gtm_lnm_acct') or ''
        token_file = TOKEN_MAP.get(lnm_acct, default_token)

        print(f'Container {gtm_id}  ({", ".join(names)})')

        try:
            service = get_gtm_service(token_file)
            acct_id, ctr_id = resolve_container(
                service, gtm_id,
                loc.get('gtm_account_id'), loc.get('gtm_container_id')
            )
            ws_id = get_workspace(service, acct_id, ctr_id)
            tags  = list_tags(service, acct_id, ctr_id, ws_id)
        except Exception as e:
            print(f'  [error] Could not connect: {e}')
            skipped += 1
            continue

        has_new = NEW_TAG in tags
        has_old = OLD_TAG in tags

        print(f'  "{NEW_TAG}": {"✓" if has_new else "✗"}')
        print(f'  "{OLD_TAG}": {"✓" if has_old else "✗"}')

        if not has_new:
            print(f'  [skip] AutoOps Events tag absent — no cleanup needed')
            skipped += 1
            continue

        if not has_old:
            print(f'  [skip] ao-appointment-booked already absent — nothing to do')
            skipped += 1
            continue

        if args.dry_run:
            print(f'  [dry-run] Would delete: {OLD_TAG}')
            fixed += 1
            continue

        try:
            delete_tag(service, acct_id, ctr_id, ws_id, tags[OLD_TAG])
            print(f'  ✓ Deleted: {OLD_TAG}')
            vid = publish_version(service, acct_id, ctr_id, ws_id,
                                  f'Removed redundant ao-appointment-booked tag (covered by AutoOps Events)')
            print(f'  ✓ Published version {vid}')
            fixed += 1
        except Exception as e:
            print(f'  [error] {e}')
            skipped += 1

        print()

    print(f'\n=== Done: {fixed} container(s) fixed, {skipped} skipped ===')


if __name__ == '__main__':
    main()
