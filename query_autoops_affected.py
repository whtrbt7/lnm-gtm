"""
query_autoops_affected.py — Find GTM containers that had versions published
around May 11, 2026 (±3 days) for all autoops/steercrm locations.

Usage:
  python query_autoops_affected.py
"""

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

TOKEN_MAP = {
    'analytics@leadsnearme.com':  os.path.join(SCRIPT_DIR, 'token_analytics.json'),
    'analytics2@leadsnearme.com': os.path.join(SCRIPT_DIR, 'token_analytics2.json'),
    'reports@leadsnearme.com':    os.path.join(SCRIPT_DIR, 'token_reports.json'),
    'ga4@leadsnearme.com':        os.path.join(SCRIPT_DIR, 'token_ga4.json'),
}
_svc_cache = {}


def fetch_autoops_locations():
    results = []
    for sched in ('autoops', 'steercrm'):
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/locations',
            params={
                'scheduler_type': f'ilike.*{sched}*',
                'select': 'id,name,gtm_id,gtm_account_id,gtm_container_id,gtm_lnm_acct,ga4_measurement_id',
                'deleted_at': 'is.null',
            },
            headers=SB_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        results.extend(r.json())
    return results


def get_gtm_service(token_file):
    if token_file in _svc_cache:
        return _svc_cache[token_file]
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
        with open(token_file, 'w') as f:
            json.dump(data, f, indent=2)
    svc = build('tagmanager', 'v2', credentials=creds)
    _svc_cache[token_file] = svc
    return svc


def _call(fn, max_retries=6, base_delay=3.0):
    from googleapiclient.errors import HttpError
    delay = base_delay
    for attempt in range(max_retries):
        try:
            return fn()
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < max_retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60)
            else:
                raise


DATE_PATTERNS  = ['2026-05-08', '2026-05-09', '2026-05-10', '2026-05-11',
                  '2026-05-12', '2026-05-13', '2026-05-14']
NAME_KEYWORDS  = ['autoops', 'auto ops', 'AutoOps', 'Auto Ops', 'ao-appointment']


def list_versions_in_range(service, acct, ctr):
    """Return versions whose name contains a May 8-14 date or autoops keyword."""
    try:
        resp = _call(lambda: service.accounts().containers().version_headers().list(
            parent=f'accounts/{acct}/containers/{ctr}',
            includeDeleted=False,
        ).execute())
    except Exception as e:
        return None, str(e)

    hits = []
    for v in resp.get('containerVersionHeader', []):
        name = v.get('name', '')
        matched = (
            any(d in name for d in DATE_PATTERNS) or
            any(k.lower() in name.lower() for k in NAME_KEYWORDS)
        )
        if matched:
            hits.append({
                'version_id': v.get('containerVersionId'),
                'name':       name,
            })
    return hits, None


def main():
    print('Fetching AutoOps/SteerCRM locations from Supabase…')
    locs = fetch_autoops_locations()
    print(f'  {len(locs)} location(s)\n')

    # Deduplicate by container
    seen: dict[str, list[dict]] = {}
    for loc in locs:
        gtm_id = loc.get('gtm_id')
        if not gtm_id:
            continue
        seen.setdefault(gtm_id, []).append(loc)

    with open(CACHE_FILE) as f:
        cache = json.load(f)

    default_token = os.path.join(SCRIPT_DIR, 'token_analytics.json')

    affected = []
    not_affected = []
    errors = []

    total = len(seen)
    for i, (gtm_id, locs_for_ctr) in enumerate(seen.items(), 1):
        rep = locs_for_ctr[0]
        lnm_acct = rep.get('gtm_lnm_acct') or ''
        token_file = TOKEN_MAP.get(lnm_acct, default_token)

        acct_id = rep.get('gtm_account_id') or ''
        ctr_id  = rep.get('gtm_container_id') or ''
        if not acct_id or not ctr_id:
            if gtm_id in cache:
                acct_id = cache[gtm_id]['account_id']
                ctr_id  = cache[gtm_id]['container_id']
            else:
                errors.append({'gtm_id': gtm_id, 'reason': 'no container IDs'})
                continue

        names = [l['name'] for l in locs_for_ctr]
        print(f'[{i}/{total}] {gtm_id}  ({", ".join(names)})')

        try:
            svc = get_gtm_service(token_file)
            versions, err = list_versions_in_range(svc, acct_id, ctr_id)
        except Exception as e:
            errors.append({'gtm_id': gtm_id, 'names': names, 'reason': str(e)})
            print(f'  [error] {e}')
            continue

        if err:
            errors.append({'gtm_id': gtm_id, 'names': names, 'reason': err})
            print(f'  [error] {err}')
        elif versions:
            for v in versions:
                print(f'  ✓ v{v["version_id"]}  "{v["name"]}"')
            affected.append({
                'gtm_id':    gtm_id,
                'names':     names,
                'ga4_ids':   list({l.get('ga4_measurement_id') for l in locs_for_ctr if l.get('ga4_measurement_id')}),
                'versions':  versions,
            })
        else:
            print(f'  — no publish May 8-14')
            not_affected.append(gtm_id)

        time.sleep(0.15)

    print(f'\n{"="*60}')
    print(f'AFFECTED ({len(affected)} containers):')
    for a in affected:
        print(f'  {a["gtm_id"]}  {", ".join(a["names"])}')
        if a['ga4_ids']:
            print(f'    GA4: {", ".join(a["ga4_ids"])}')
        for v in a['versions']:
            print(f'    v{v["version_id"]}  "{v["name"]}"')
    print(f'\nNot affected: {len(not_affected)} containers')
    print(f'Errors:       {len(errors)} containers')
    if errors:
        for e in errors:
            print(f'  {e}')

    out = os.path.join(SCRIPT_DIR, 'autoops_affected_may11.json')
    with open(out, 'w') as f:
        json.dump({'affected': affected, 'errors': errors}, f, indent=2)
    print(f'\nFull results → {out}')


if __name__ == '__main__':
    main()
