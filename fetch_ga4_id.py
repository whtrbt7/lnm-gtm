"""
fetch_ga4_id.py — Look up GA4 measurement ID and scheduler type for a location.

Strategies (in order):
  GA4 ID:
    1. Scrape live website HTML for G-XXXXXXXXXX
    2. Read GA4 Configuration tag from GTM container via API
  Scheduler:
    1. Scrape live website HTML for booking system fingerprints
       (autoops.com, shopgenie.com, oktorocket.com)

Writes ga4_measurement_id and scheduler_type to Supabase on success.

Usage:
  python fetch_ga4_id.py --gads-cid 2182691535
  python fetch_ga4_id.py --gads-cid 2182691535 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
SB_HEADERS   = {
    'apikey':        SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type':  'application/json',
}

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE  = os.path.join(SCRIPT_DIR, 'token.json')
CACHE_FILE  = os.path.join(SCRIPT_DIR, 'gtm_id_cache.json')
INDEX_CACHE = os.path.join(SCRIPT_DIR, 'container_index_cache.json')

GA4_RE = re.compile(r'G-[A-Z0-9]{6,12}')

_last_gtm_call = 0.0
GTM_CALL_INTERVAL = 7.5   # GTM API quota: 10 QPM


# ── Supabase ──────────────────────────────────────────────────────────────────

def fetch_location(gads_cid: str) -> dict:
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={'gads_cid': f'eq.{gads_cid}',
                'select': 'id,name,url,gtm_id,gtm_account_id,gtm_container_id,ga4_measurement_id,scheduler_type'},
        headers=SB_HEADERS, timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        raise SystemExit(f'No location found for gads_cid={gads_cid}')
    return data[0]


def write_location_fields(gads_cid: str, fields: dict) -> bool:
    r = requests.patch(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={'gads_cid': f'eq.{gads_cid}'},
        headers={**SB_HEADERS, 'Prefer': 'return=minimal'},
        json=fields,
        timeout=10,
    )
    return r.status_code in (200, 201, 204)


# ── Strategy 1: URL scraping ──────────────────────────────────────────────────

# Scheduler fingerprints: ordered by specificity.
# Each entry: (scheduler_type, [regex patterns to search in HTML])
_SCHEDULER_PATTERNS: list[tuple[str, list[str]]] = [
    ('autoops', [
        r'autoops\.com',
        r'ao-appointment-booked',
        r'autoops',
    ]),
    ('shopgenie', [
        r'shopgenie\.com',
        r'shop-genie\.com',
        r'getshopgenie\.com',
        r'shopgenie',
    ]),
    ('oktorocket', [
        r'oktorocket\.com',
        r'oktorocket',
        r'dc-service-booked',
        r'dcbooking',
    ]),
]


def detect_scheduler_from_html(html: str) -> str | None:
    """Return scheduler_type string if a booking system is detected in page HTML."""
    for scheduler, patterns in _SCHEDULER_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, html, re.IGNORECASE):
                return scheduler
    return None


def fetch_html(url: str) -> str | None:
    if not url:
        return None
    if not url.startswith('http'):
        url = 'https://' + url
    try:
        resp = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; LNM-GA4-Lookup/1.0)',
        }, allow_redirects=True)
        return resp.text
    except Exception as e:
        print(f'  [warn] HTTP fetch failed for {url}: {e}')
    return None


def scrape_ga4_from_html(html: str) -> str | None:
    for pattern in [
        r'googletagmanager\.com/gtag/js\?id=(G-[A-Z0-9]{6,12})',
        r"gtag\(['\"]config['\"],\s*['\"]([^'\"]+)['\"]",
        r'"measurementId"\s*:\s*"(G-[A-Z0-9]{6,12})"',
        r"'measurementId'\s*:\s*'(G-[A-Z0-9]{6,12})'",
    ]:
        m = re.search(pattern, html)
        if m:
            val = m.group(1)
            if val.startswith('G-'):
                return val
    ids = GA4_RE.findall(html)
    return ids[0] if ids else None


# ── Strategy 2: GTM tag API lookup ────────────────────────────────────────────

def _throttled(fn):
    global _last_gtm_call
    elapsed = time.time() - _last_gtm_call
    if elapsed < GTM_CALL_INTERVAL:
        time.sleep(GTM_CALL_INTERVAL - elapsed)
    result = fn()
    _last_gtm_call = time.time()
    return result


def _get_gtm_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    with open(TOKEN_FILE) as f:
        data = json.load(f)

    creds = Credentials(
        token=data.get('token'),
        refresh_token=data.get('refresh_token'),
        token_uri=data.get('token_uri', 'https://oauth2.googleapis.com/token'),
        client_id=data.get('client_id'),
        client_secret=data.get('client_secret'),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        data['token'] = creds.token
        data['expiry'] = creds.expiry.isoformat() if creds.expiry else None
        with open(TOKEN_FILE, 'w') as f:
            json.dump(data, f, indent=2)

    return build('tagmanager', 'v2', credentials=creds)


def _load_gtm_id_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def _load_url_index() -> dict:
    if os.path.exists(INDEX_CACHE):
        with open(INDEX_CACHE) as f:
            data = json.load(f)
        return data.get('url_index', {}) if isinstance(data, dict) else {}
    return {}


def _normalize_domain(url: str) -> str:
    d = re.sub(r'^https?://', '', str(url or '')).rstrip('/')
    d = re.sub(r'^www\.', '', d)
    return d.lower().split('/')[0]


def _find_container(service, gtm_public_id: str) -> tuple[str, str] | tuple[None, None]:
    """Resolve GTM-XXXXX → (account_id, container_id). Cache-first, then full scan."""
    cache = _load_gtm_id_cache()
    if gtm_public_id in cache:
        c = cache[gtm_public_id]
        return str(c['account_id']), str(c['container_id'])

    print(f'  Container {gtm_public_id} not in cache — scanning GTM accounts…')
    try:
        accounts = _throttled(lambda: service.accounts().list().execute()).get('account', [])
        for acct in accounts:
            containers = _throttled(
                lambda a=acct: service.accounts().containers()
                               .list(parent=a['path']).execute()
            ).get('container', [])
            for c in containers:
                if c.get('publicId', '').upper() == gtm_public_id.upper():
                    acct_id = acct['accountId']
                    ctr_id  = c['containerId']
                    # Seed cache
                    cache[gtm_public_id] = {'account_id': acct_id, 'container_id': ctr_id}
                    with open(CACHE_FILE, 'w') as f:
                        json.dump(cache, f, indent=2)
                    print(f'  Found: account={acct_id} container={ctr_id} (cached)')
                    return acct_id, ctr_id
    except Exception as e:
        print(f'  [warn] GTM account scan failed: {e}')
    return None, None


def lookup_ga4_from_gtm(gtm_id: str, gtm_account_id: str | None,
                        gtm_container_id: str | None) -> str | None:
    try:
        service = _get_gtm_service()
    except Exception as e:
        print(f'  [warn] GTM auth failed: {e}')
        return None

    # Resolve account/container IDs
    acct_id = gtm_account_id
    ctr_id  = gtm_container_id
    if not acct_id or not ctr_id:
        acct_id, ctr_id = _find_container(service, gtm_id)
    if not acct_id or not ctr_id:
        print(f'  [warn] Could not resolve container for {gtm_id}')
        return None

    try:
        workspaces = _throttled(
            lambda: service.accounts().containers().workspaces()
                    .list(parent=f'accounts/{acct_id}/containers/{ctr_id}').execute()
        ).get('workspace', [])
        if not workspaces:
            print('  [warn] No workspace found in container')
            return None

        ws_id = workspaces[0]['workspaceId']
        tags  = _throttled(
            lambda: service.accounts().containers().workspaces().tags()
                    .list(parent=f'accounts/{acct_id}/containers/{ctr_id}/workspaces/{ws_id}')
                    .execute()
        ).get('tag', [])

        for tag in tags:
            if tag.get('type') != 'gaawc':
                continue
            for param in tag.get('parameter', []):
                if param.get('key') == 'measurementId':
                    return param.get('value')

        print('  No GA4 Configuration tag (gaawc) found in container')
    except Exception as e:
        print(f'  [warn] GTM tag lookup failed: {e}')
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def run(gads_cid: str, dry_run: bool = False) -> int:
    loc = fetch_location(gads_cid)
    name             = loc.get('name', '')
    url              = loc.get('url', '')
    gtm_id           = loc.get('gtm_id', '')
    gtm_account_id   = loc.get('gtm_account_id')
    gtm_container_id = loc.get('gtm_container_id')
    existing_ga4     = loc.get('ga4_measurement_id')
    existing_sched   = loc.get('scheduler_type')

    print(f'Location  : {name}')
    print(f'URL       : {url}')
    print(f'GTM ID    : {gtm_id or "(none)"}')
    print(f'GA4 now   : {existing_ga4 or "(none)"}')
    print(f'Sched now : {existing_sched or "(none)"}')
    print()

    measurement_id: str | None = None
    scheduler: str | None = None
    html: str | None = None

    # ── Fetch HTML once, use for both GA4 + scheduler detection ──────────────
    print('Fetching website HTML…')
    html = fetch_html(url)
    if html:
        print(f'  {len(html):,} bytes')

        print('\nGA4 — Strategy 1: scraping HTML…')
        measurement_id = scrape_ga4_from_html(html)
        if measurement_id:
            print(f'  Found: {measurement_id}')
        else:
            print('  Not found (GA4 likely loaded via GTM)')

        print('\nScheduler — detecting from HTML…')
        scheduler = detect_scheduler_from_html(html)
        if scheduler:
            print(f'  Detected: {scheduler}')
        else:
            print('  Not detected')
    else:
        print('  Could not fetch page')

    # ── GA4 fallback: GTM tag API ─────────────────────────────────────────────
    if not measurement_id:
        if not gtm_id:
            print('\nGA4 — Strategy 2: Skipped (no gtm_id on location)')
        else:
            print(f'\nGA4 — Strategy 2: Reading from GTM container {gtm_id}…')
            measurement_id = lookup_ga4_from_gtm(gtm_id, gtm_account_id, gtm_container_id)
            if measurement_id:
                print(f'  Found: {measurement_id}')
            else:
                print('  Not found in GTM container')

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f'\n── Results ──')
    print(f'GA4 ID    : {measurement_id or "(not found)"}')
    print(f'Scheduler : {scheduler or "(not detected)"}')

    if not measurement_id and not scheduler:
        print('\n[error] Nothing to write.')
        return 1

    if dry_run:
        print('\n[dry-run] No writes.')
        return 0

    updates: dict = {}
    if measurement_id:
        updates['ga4_measurement_id'] = measurement_id
    if scheduler and not existing_sched:
        updates['scheduler_type'] = scheduler
    elif scheduler and existing_sched:
        print(f'  scheduler_type already set to "{existing_sched}" — not overwriting')

    if updates:
        ok = write_location_fields(gads_cid, updates)
        print(f'Supabase update {list(updates.keys())}: {"ok" if ok else "FAILED"}')
        return 0 if ok else 1

    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--gads-cid', required=True)
    parser.add_argument('--dry-run',  action='store_true')
    args = parser.parse_args()
    sys.exit(run(args.gads_cid, dry_run=args.dry_run))
