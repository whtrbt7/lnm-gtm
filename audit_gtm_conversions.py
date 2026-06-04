"""
audit_gtm_conversions.py — Check every live GTM container for conversion ID/label issues.

Compares what's actually in the live container against expected values from gads_conversions.

Flags:
  - wrong_cid        : conversionId / AW Config tagId doesn't match expected
  - missing_cid      : no googtag or awct tags found
  - wrong_label      : conversionLabel doesn't match any expected label for this account
  - missing_label    : awct tag has no conversionLabel
  - cid_is_customer  : conversionId matches gads_cid (customer ID) not AW tracking ID
  - no_conversions   : location has no rows in gads_conversions
  - extra_cid        : multiple different conversionIds in one container

Usage:
  python audit_gtm_conversions.py             # all containers
  python audit_gtm_conversions.py --limit 50  # first 50
  python audit_gtm_conversions.py --active    # script_injected only
"""

import argparse
import csv
import json
import os
import time
from collections import defaultdict

import requests
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://supabase.alexanderchiu.com')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
SB_HEADERS   = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'}
TOKEN_MAP = {
    'analytics@leadsnearme.com':  os.path.join(SCRIPT_DIR, 'token_analytics.json'),
    'analytics2@leadsnearme.com': os.path.join(SCRIPT_DIR, 'token_analytics2.json'),
    'reports@leadsnearme.com':    os.path.join(SCRIPT_DIR, 'token_reports.json'),
}
DEFAULT_TOKEN = os.path.join(SCRIPT_DIR, 'token_developer.json')


# ── Supabase ──────────────────────────────────────────────────────────────────

def fetch_locations(active_only: bool) -> list[dict]:
    params = {
        'select': 'id,name,url,gads_cid,gtm_id,gtm_account_id,gtm_container_id,gtm_lnm_acct,gtm_container_status',
        'deleted_at': 'is.null',
        'gtm_id': 'not.is.null',
        'gtm_account_id': 'not.is.null',
        'gtm_container_id': 'not.is.null',
    }
    if active_only:
        params['gtm_container_status'] = 'eq.script_injected'

    results, offset = [], 0
    while True:
        r = requests.get(f'{SUPABASE_URL}/rest/v1/locations',
            params={**params, 'offset': offset, 'limit': 1000},
            headers=SB_HEADERS, timeout=15)
        r.raise_for_status()
        batch = r.json()
        results.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000
    return results


def fetch_conversions() -> dict[str, list[dict]]:
    """Returns {location_id: [{conversion_id, label, name, type}]}"""
    mapping: dict[str, list] = defaultdict(list)
    offset = 0
    while True:
        r = requests.get(f'{SUPABASE_URL}/rest/v1/gads_conversions',
            params={'select': 'location_id,conversion_id,label,name,type',
                    'offset': offset, 'limit': 1000},
            headers=SB_HEADERS, timeout=15)
        r.raise_for_status()
        batch = r.json()
        for row in batch:
            if row.get('location_id'):
                mapping[row['location_id']].append(row)
        if len(batch) < 1000:
            break
        offset += 1000
    return mapping


# ── GTM Auth ──────────────────────────────────────────────────────────────────

_svc_cache: dict[str, object] = {}

def get_gtm_service(token_file: str):
    if token_file in _svc_cache:
        return _svc_cache[token_file]
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    with open(token_file) as f:
        data = json.load(f)
    creds = Credentials(
        token=data.get('token'), refresh_token=data.get('refresh_token'),
        token_uri=data.get('token_uri', 'https://oauth2.googleapis.com/token'),
        client_id=data.get('client_id'), client_secret=data.get('client_secret'),
        scopes=data.get('scopes'))
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        data['token'] = creds.token
        with open(token_file, 'w') as f:
            json.dump(data, f, indent=2)
    svc = build('tagmanager', 'v2', credentials=creds)
    _svc_cache[token_file] = svc
    return svc


def _call(fn, max_retries=8, base_delay=3.0):
    from googleapiclient.errors import HttpError
    delay = base_delay
    for attempt in range(max_retries):
        try:
            return fn()
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < max_retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 120)
            else:
                raise


def get_live_tags(service, acct: str, ctr: str) -> list[dict]:
    try:
        live = _call(lambda: service.accounts().containers().versions().live(
            parent=f'accounts/{acct}/containers/{ctr}'
        ).execute())
        return live.get('tag', [])
    except Exception:
        return []


# ── Analysis ──────────────────────────────────────────────────────────────────

def analyse_container(tags: list[dict], expected_cids: set[str],
                      expected_labels: set[str], gads_cid: str) -> dict:
    """
    Returns dict with fields:
      live_aw_config_cid, live_conversion_ids, live_labels, flags (list)
    """
    aw_config_cids: list[str] = []
    awct_cids:      list[str] = []
    awct_labels:    list[str] = []

    for tag in tags:
        tag_type = tag.get('type')
        params   = {p['key']: p.get('value', '') for p in tag.get('parameter', [])}

        if tag_type == 'googtag':
            tid = params.get('tagId', '')
            if tid.startswith('AW-'):
                aw_config_cids.append(tid.replace('AW-', ''))

        elif tag_type == 'awct':
            cid   = str(params.get('conversionId', ''))
            label = params.get('conversionLabel', '')
            if cid:
                awct_cids.append(cid)
            if label:
                awct_labels.append(label)

    all_cids   = list(dict.fromkeys(aw_config_cids + awct_cids))
    unique_cids = list(dict.fromkeys(all_cids))

    flags = []

    if not aw_config_cids and not awct_cids:
        flags.append('missing_cid')
    else:
        # Wrong CID check
        for cid in unique_cids:
            if expected_cids and cid not in expected_cids:
                # Is it the customer CID?
                if str(gads_cid).replace('-', '') == cid:
                    flags.append('cid_is_customer')
                else:
                    flags.append('wrong_cid')

        # Extra / conflicting CIDs
        if len(set(unique_cids)) > 1:
            flags.append('extra_cid')

    # Label checks (only if we have awct tags)
    if awct_cids:
        if not awct_labels:
            flags.append('missing_label')
        elif expected_labels:
            bad = [l for l in awct_labels if l not in expected_labels]
            if bad:
                flags.append('wrong_label')

    if not expected_cids:
        flags.append('no_conversions')

    return {
        'live_aw_config_cid': ' | '.join(dict.fromkeys(aw_config_cids)),
        'live_conversion_ids': ' | '.join(dict.fromkeys(awct_cids)),
        'live_labels':         ' | '.join(dict.fromkeys(awct_labels)),
        'flags':               ', '.join(flags) if flags else 'ok',
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--active', action='store_true', help='Only script_injected containers')
    args = parser.parse_args()

    print('Fetching locations…')
    locs = fetch_locations(args.active)
    print(f'  {len(locs)} location(s)')

    print('Fetching gads_conversions…')
    conv_map = fetch_conversions()
    print(f'  {len(conv_map)} location(s) with conversion data\n')

    # Deduplicate by container — pick representative location per container
    seen: dict[tuple, dict] = {}
    for loc in locs:
        key = (str(loc['gtm_account_id']), str(loc['gtm_container_id']))
        if key not in seen:
            seen[key] = loc

    containers = list(seen.values())
    if args.limit:
        containers = containers[:args.limit]
    print(f'{len(containers)} unique container(s) to audit\n')

    out_path = '/tmp/gtm_audit.csv'
    fieldnames = [
        'gtm_id', 'location_name', 'url', 'gads_cid',
        'expected_conversion_ids', 'expected_labels',
        'live_aw_config_cid', 'live_conversion_ids', 'live_labels',
        'flags', 'gtm_container_status',
    ]

    ok = wrong = error = 0

    with open(out_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()

        for i, loc in enumerate(containers, 1):
            gtm_id   = loc.get('gtm_id', '?')
            name     = loc.get('name', '?')
            acct     = str(loc['gtm_account_id'])
            ctr      = str(loc['gtm_container_id'])
            gads_cid = str(loc.get('gads_cid', '') or '').replace('-', '')
            lnm_acct = loc.get('gtm_lnm_acct') or ''
            tf       = TOKEN_MAP.get(lnm_acct, DEFAULT_TOKEN)

            # Build expected sets from gads_conversions
            loc_convs     = conv_map.get(loc['id'], [])
            expected_cids = {str(c['conversion_id']) for c in loc_convs if c.get('conversion_id')}
            expected_lbls = {c['label'] for c in loc_convs if c.get('label')}

            if i % 50 == 0:
                print(f'  [{i}/{len(containers)}] …')

            try:
                svc  = get_gtm_service(tf)
                tags = get_live_tags(svc, acct, ctr)
                result = analyse_container(tags, expected_cids, expected_lbls, gads_cid)

                w.writerow({
                    'gtm_id': gtm_id,
                    'location_name': name,
                    'url': loc.get('url', ''),
                    'gads_cid': loc.get('gads_cid', ''),
                    'expected_conversion_ids': ' | '.join(sorted(expected_cids)),
                    'expected_labels': ' | '.join(sorted(expected_lbls)),
                    **result,
                    'gtm_container_status': loc.get('gtm_container_status', ''),
                })
                if result['flags'] == 'ok':
                    ok += 1
                else:
                    wrong += 1

            except Exception as e:
                w.writerow({
                    'gtm_id': gtm_id, 'location_name': name, 'url': loc.get('url', ''),
                    'gads_cid': loc.get('gads_cid', ''),
                    'expected_conversion_ids': ' | '.join(sorted(expected_cids)),
                    'expected_labels': ' | '.join(sorted(expected_lbls)),
                    'live_aw_config_cid': '', 'live_conversion_ids': '',
                    'live_labels': '', 'flags': f'api_error: {e}',
                    'gtm_container_status': loc.get('gtm_container_status', ''),
                })
                error += 1

            time.sleep(0.4)

    print(f'\n=== Done ===')
    print(f'  OK: {ok}  |  Issues: {wrong}  |  API errors: {error}')
    print(f'  Written: {out_path}')


if __name__ == '__main__':
    main()
