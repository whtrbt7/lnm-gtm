"""
fix_tiktok_pixel.py — Update outdated TikTok pixel tags and publish.

Targets the 55 containers with the old arrow-function pixel snippet.
Updates "TikTok - Pixel - Base" HTML to canonical, creates a version, publishes.
Writes unpublished.csv for any container that fails to publish.

Usage:
  python fix_tiktok_pixel.py
  python fix_tiktok_pixel.py --dry-run
  python fix_tiktok_pixel.py --token-file token_analytics2.json
"""

import argparse
import csv
import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, 'gtm_id_cache.json')

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
SB_HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
}

TAG_NAME = 'TikTok - Pixel - Base'

CANONICAL_HTML = (
    "<script>\n"
    "!function (w, d, t) {\n"
    "  w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];ttq.methods=[\"page\",\"track\",\"identify\",\"instances\",\"debug\",\"on\",\"off\",\"once\",\"ready\",\"alias\",\"group\",\"enableCookie\",\"disableCookie\"],ttq.setAndLog=function(t,e){t.split(\".\").reduce(function(t,e){t[e]=t[e]||{};return t[e];},ttq).log=e};ttq.instance=function(t){for(var e=ttq._i[t]||[],n=0;n<ttq.methods.length;n++)ttq.setAndLog(e,ttq.methods[n]);return e};ttq.load=function(e,n){var i=\"https://analytics.tiktok.com/i18n/pixel/events.js\";ttq._i=ttq._i||{},ttq._i[e]=[],ttq._i[e]._u=i,ttq._t=ttq._t||+new Date,ttq._o=ttq._o||{},ttq._o[e]=n||{};var o=document.createElement(\"script\");o.type=\"text/javascript\",o.async=!0,o.src=i+\"?sdkid=\"+e+\"&lib=\"+t;var a=document.getElementsByTagName(\"script\")[0];a.parentNode.insertBefore(o,a)};\n"
    "  ttq.load('{{C - TikTok Pixel ID}}');\n"
    "  ttq.page();\n"
    "}(window, document, 'ttq');\n"
    "</script>"
)

# 55 outdated containers from audit (2026-05-20)
OUTDATED_GTM_IDS = [
    'GTM-NBX5M3FJ', 'GTM-NQDWRVCW', 'GTM-TNL3DTF6', 'GTM-NQZK62K3',
    'GTM-KX9KC2ZM', 'GTM-MP98PVFB', 'GTM-KSXMVJM9', 'GTM-MH5CCF65',
    'GTM-WJ3HC3VG', 'GTM-MM8PJ7RJ', 'GTM-KP2T96DP', 'GTM-MS8BXRQF',
    'GTM-M4NPMNBN', 'GTM-NB5W2DNB', 'GTM-T6MF69GF', 'GTM-PB7RPLXG',
    'GTM-WST4VJVJ', 'GTM-N6HSX7JH', 'GTM-MPSTSLDR', 'GTM-P7ZF39LL',
    'GTM-M6K3LHSZ', 'GTM-W6WW7QMP', 'GTM-MTRC5XMG', 'GTM-NQJQ8KT9',
    'GTM-PX2TMWGJ', 'GTM-TKP6NZT4', 'GTM-N2NRW2DW', 'GTM-5X3MFWDD',
    'GTM-TRFRMLVC', 'GTM-K5P58VWH', 'GTM-M7LVQFT3', 'GTM-N8C6LX5R',
    'GTM-5ZLR7R6C', 'GTM-WDV4NNHP', 'GTM-M22LTFZR', 'GTM-WSQRQ8RP',
    'GTM-T6SVW4MD', 'GTM-TK8LZFXZ', 'GTM-PMCQZKFR', 'GTM-WSWPT69C',
    'GTM-NVN248CT', 'GTM-K2F9L8W9', 'GTM-MXK86BGF', 'GTM-WCLPJR2S',
    'GTM-NPKK594R', 'GTM-WVFLPKLW', 'GTM-5HH553N7', 'GTM-NG5VRVX2',
    'GTM-5J699H4V', 'GTM-W2ZGQB8C', 'GTM-5JR7DCKJ', 'GTM-KJ32H8VR',
    'GTM-TF8859D7', 'GTM-N4MB5R96', 'GTM-NZL83B8S',
]


def fetch_locations_by_gtm_ids(gtm_ids: list[str]) -> dict[str, dict]:
    result = {}
    for i in range(0, len(gtm_ids), 50):
        batch = gtm_ids[i:i+50]
        ids_param = '(' + ','.join(f'"{g}"' for g in batch) + ')'
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/locations',
            params={
                'gtm_id': f'in.{ids_param}',
                'select': 'id,name,gtm_id,gtm_account_id,gtm_container_id,gtm_lnm_acct',
                'deleted_at': 'is.null',
            },
            headers=SB_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        for loc in r.json():
            result[loc['gtm_id']] = loc
    return result


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


def resolve_container(gtm_id, account_id, container_id):
    if account_id and container_id:
        return str(account_id), str(container_id)
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            cache = json.load(f)
    if gtm_id in cache:
        c = cache[gtm_id]
        return str(c['account_id']), str(c['container_id'])
    raise RuntimeError(f'{gtm_id} not in Supabase or cache')


def get_workspace_id(service, acct, ctr):
    ws = _call(lambda: service.accounts().containers().workspaces().list(
        parent=f'accounts/{acct}/containers/{ctr}'
    ).execute()).get('workspace', [])
    if not ws:
        raise RuntimeError('No workspace')
    return ws[0]['workspaceId']


def get_tiktok_tag(service, acct, ctr, ws):
    resp = _call(lambda: service.accounts().containers().workspaces().tags().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())
    for tag in resp.get('tag', []):
        if tag['name'] == TAG_NAME:
            return tag
    return None


def update_tag_html(service, acct, ctr, ws, tag, new_html):
    updated = dict(tag)
    updated['parameter'] = [
        {**p, 'value': new_html} if p['key'] == 'html' else p
        for p in tag.get('parameter', [])
    ]
    path = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}/tags/{tag["tagId"]}'
    return _call(lambda: service.accounts().containers().workspaces().tags().update(
        path=path, body=updated
    ).execute())


def publish(service, acct, ctr, ws):
    ver = _call(lambda: service.accounts().containers().workspaces().create_version(
        path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}',
        body={'name': 'LNM TikTok Pixel Fix', 'notes': 'Fix setAndLog arrow fn → regular fn for browser compat'},
    ).execute())
    if ver.get('compilerError'):
        raise RuntimeError(f'Compiler error: {ver["compilerError"]}')
    vid = ver['containerVersion']['containerVersionId']
    _call(lambda: service.accounts().containers().versions().publish(
        path=f'accounts/{acct}/containers/{ctr}/versions/{vid}',
    ).execute())
    return vid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--token-file', default=None)
    args = parser.parse_args()

    TOKEN_MAP = {
        'analytics@leadsnearme.com':  os.path.join(SCRIPT_DIR, 'token_analytics.json'),
        'analytics2@leadsnearme.com': os.path.join(SCRIPT_DIR, 'token_analytics2.json'),
        'reports@leadsnearme.com':    os.path.join(SCRIPT_DIR, 'token_reports.json'),
        'ga4@leadsnearme.com':        os.path.join(SCRIPT_DIR, 'token_ga4.json'),
    }
    default_token = args.token_file or os.path.join(SCRIPT_DIR, 'token_analytics.json')

    print(f'Fetching {len(OUTDATED_GTM_IDS)} location records from Supabase…')
    loc_map = fetch_locations_by_gtm_ids(OUTDATED_GTM_IDS)
    print(f'  Found {len(loc_map)} in Supabase\n')

    published = []
    failed = []

    for i, gtm_id in enumerate(OUTDATED_GTM_IDS, 1):
        loc = loc_map.get(gtm_id, {})
        name = loc.get('name', '?')
        lnm_acct = loc.get('gtm_lnm_acct') or ''
        token_file = TOKEN_MAP.get(lnm_acct, default_token)

        print(f'[{i}/{len(OUTDATED_GTM_IDS)}] {gtm_id}  {name}', end='  ', flush=True)

        try:
            service = get_gtm_service(token_file)
            acct_id, ctr_id = resolve_container(
                gtm_id,
                loc.get('gtm_account_id'), loc.get('gtm_container_id')
            )
            ws_id = get_workspace_id(service, acct_id, ctr_id)
            tag = get_tiktok_tag(service, acct_id, ctr_id, ws_id)

            if tag is None:
                print('SKIP (tag gone)')
                failed.append((gtm_id, name, 'tag not found'))
                continue

            # Verify still outdated
            actual_html = next((p['value'] for p in tag.get('parameter', []) if p['key'] == 'html'), '')
            if actual_html == CANONICAL_HTML:
                print('already fixed')
                published.append((gtm_id, name, 'already_fixed'))
                continue

            if args.dry_run:
                print('DRY-RUN would update+publish')
                continue

            update_tag_html(service, acct_id, ctr_id, ws_id, tag, CANONICAL_HTML)
            vid = publish(service, acct_id, ctr_id, ws_id)
            print(f'✓ published v{vid}')
            published.append((gtm_id, name, f'v{vid}'))

        except Exception as e:
            print(f'ERROR: {e}')
            failed.append((gtm_id, name, str(e)))

        time.sleep(0.2)

    print(f'\n{"="*60}')
    print(f'Published : {len([p for p in published if p[2] != "already_fixed"])}')
    print(f'Already fixed: {len([p for p in published if p[2] == "already_fixed"])}')
    print(f'Failed    : {len(failed)}')

    if failed:
        csv_path = os.path.join(SCRIPT_DIR, 'unpublished_tiktok.csv')
        with open(csv_path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['gtm_id', 'name', 'reason'])
            w.writerows(failed)
        print(f'\nUnpublished CSV → {csv_path}')
        for row in failed:
            print(f'  {row[0]}  {row[1]}: {row[2]}')


if __name__ == '__main__':
    main()
