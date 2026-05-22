"""
check_tiktok_pixel.py — Audit all GTM containers for the fixed TikTok pixel.

Compares the live "TikTok - Pixel - Base" tag HTML against the canonical version
in setup_tags.py. Reports: fixed, outdated, or missing.

Usage:
  python check_tiktok_pixel.py
  python check_tiktok_pixel.py --token-file token_analytics2.json
  python check_tiktok_pixel.py --limit 50   # test run
"""

import argparse
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

# Canonical "fixed" pixel HTML (from setup_tags.py tiktok_pixel_tag)
CANONICAL_HTML = (
    "<script>\n"
    "!function (w, d, t) {\n"
    "  w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];ttq.methods=[\"page\",\"track\",\"identify\",\"instances\",\"debug\",\"on\",\"off\",\"once\",\"ready\",\"alias\",\"group\",\"enableCookie\",\"disableCookie\"],ttq.setAndLog=function(t,e){t.split(\".\").reduce(function(t,e){t[e]=t[e]||{};return t[e];},ttq).log=e};ttq.instance=function(t){for(var e=ttq._i[t]||[],n=0;n<ttq.methods.length;n++)ttq.setAndLog(e,ttq.methods[n]);return e};ttq.load=function(e,n){var i=\"https://analytics.tiktok.com/i18n/pixel/events.js\";ttq._i=ttq._i||{},ttq._i[e]=[],ttq._i[e]._u=i,ttq._t=ttq._t||+new Date,ttq._o=ttq._o||{},ttq._o[e]=n||{};var o=document.createElement(\"script\");o.type=\"text/javascript\",o.async=!0,o.src=i+\"?sdkid=\"+e+\"&lib=\"+t;var a=document.getElementsByTagName(\"script\")[0];a.parentNode.insertBefore(o,a)};\n"
    "  ttq.load('{{C - TikTok Pixel ID}}');\n"
    "  ttq.page();\n"
    "}(window, document, 'ttq');\n"
    "</script>"
)


def fetch_all_locations() -> list[dict]:
    results = []
    offset = 0
    limit = 1000
    while True:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/locations',
            params={
                'gtm_id': 'not.is.null',
                'select': 'id,name,gtm_id,gtm_account_id,gtm_container_id,gtm_lnm_acct',
                'deleted_at': 'is.null',
                'offset': offset,
                'limit': limit,
            },
            headers=SB_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        batch = r.json()
        results.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return results


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


def resolve_container(service, gtm_id, account_id, container_id):
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


def get_tiktok_tag_html(service, acct, ctr, ws):
    resp = _call(lambda: service.accounts().containers().workspaces().tags().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())
    for tag in resp.get('tag', []):
        if tag['name'] == TAG_NAME:
            for p in tag.get('parameter', []):
                if p['key'] == 'html':
                    return p['value']
            return ''  # tag exists but no html param
    return None  # tag not found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--token-file', default=None)
    parser.add_argument('--limit', type=int, default=None, help='Max containers to check')
    args = parser.parse_args()

    TOKEN_MAP = {
        'analytics@leadsnearme.com':  os.path.join(SCRIPT_DIR, 'token_analytics.json'),
        'analytics2@leadsnearme.com': os.path.join(SCRIPT_DIR, 'token_analytics2.json'),
        'reports@leadsnearme.com':    os.path.join(SCRIPT_DIR, 'token_reports.json'),
        'ga4@leadsnearme.com':        os.path.join(SCRIPT_DIR, 'token_ga4.json'),
    }
    default_token = args.token_file or os.path.join(SCRIPT_DIR, 'token_analytics.json')

    print('Fetching locations from Supabase…')
    locs = fetch_all_locations()
    print(f'  {len(locs)} location(s) with GTM\n')

    # Deduplicate by container
    seen: dict[str, dict] = {}
    for loc in locs:
        gtm_id = loc.get('gtm_id')
        if gtm_id and gtm_id not in seen:
            seen[gtm_id] = loc
    ordered = list(seen.values())
    if args.limit:
        ordered = ordered[:args.limit]

    print(f'  {len(ordered)} unique container(s) to check\n')

    fixed = []
    outdated = []
    missing = []
    errors = []

    for i, loc in enumerate(ordered, 1):
        gtm_id = loc['gtm_id']
        name = loc.get('name', '?')
        lnm_acct = loc.get('gtm_lnm_acct') or ''
        token_file = TOKEN_MAP.get(lnm_acct, default_token)

        print(f'[{i}/{len(ordered)}] {gtm_id}  {name}', end='  ', flush=True)

        try:
            service = get_gtm_service(token_file)
            acct_id, ctr_id = resolve_container(
                service, gtm_id,
                loc.get('gtm_account_id'), loc.get('gtm_container_id')
            )
            ws_id = get_workspace_id(service, acct_id, ctr_id)
            html = get_tiktok_tag_html(service, acct_id, ctr_id, ws_id)
        except Exception as e:
            print(f'ERROR: {e}')
            errors.append((gtm_id, name, str(e)))
            continue

        if html is None:
            print('MISSING')
            missing.append((gtm_id, name))
        elif html == CANONICAL_HTML:
            print('✓ fixed')
            fixed.append((gtm_id, name))
        else:
            print('✗ outdated')
            outdated.append((gtm_id, name, html))

        time.sleep(0.15)

    print(f'\n{"="*60}')
    print(f'FIXED    : {len(fixed)}')
    print(f'OUTDATED : {len(outdated)}')
    print(f'MISSING  : {len(missing)}')
    print(f'ERRORS   : {len(errors)}')

    if outdated:
        print(f'\n--- OUTDATED ({len(outdated)}) ---')
        for gtm_id, name, html in outdated:
            print(f'  {gtm_id}  {name}')
            # Show first line that differs
            c_lines = CANONICAL_HTML.split('\n')
            h_lines = html.split('\n')
            for j, (cl, hl) in enumerate(zip(c_lines, h_lines)):
                if cl != hl:
                    print(f'    line {j+1} expected: {repr(cl[:120])}')
                    print(f'    line {j+1} actual:   {repr(hl[:120])}')
                    break
            else:
                if len(c_lines) != len(h_lines):
                    print(f'    line count: expected {len(c_lines)}, got {len(h_lines)}')

    if missing:
        print(f'\n--- MISSING TikTok pixel ({len(missing)}) ---')
        for gtm_id, name in missing:
            print(f'  {gtm_id}  {name}')

    if errors:
        print(f'\n--- ERRORS ({len(errors)}) ---')
        for gtm_id, name, err in errors:
            print(f'  {gtm_id}  {name}: {err}')


if __name__ == '__main__':
    main()
