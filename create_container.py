"""
create_container.py — Create GTM account + container for an LNM client.

Looks up client name/URL from Supabase by GAds CID, creates the GTM account
and Web container via Playwright (Chrome CDP), then writes the GTM container
ID back to Supabase.

Requirements:
  - Chrome running: /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
      --remote-debugging-port=9222 --user-data-dir=/tmp/chrome_gtm \
      --no-first-run https://tagmanager.google.com/
  - Logged in to the correct Google account in that Chrome window.

Usage:
  python create_container.py --gads-cid 6322162456
  python create_container.py --gads-cid 6322162456 --name "Override Name" --url "override.com"
  python create_container.py --gads-cid 6322162456 --dry-run
"""

import re
import time
import json
import argparse
import os
import requests
from dotenv import load_dotenv

load_dotenv()

CDP_URL      = 'http://localhost:9222'
GTM_URL      = 'https://tagmanager.google.com/'
CACHE_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gtm_id_cache.json')

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']

HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
}


# ── Supabase ──────────────────────────────────────────────────────────────────

def fetch_location(gads_cid):
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={'gads_cid': f'eq.{gads_cid}', 'select': 'id,name,url,gtm_id'},
        headers=HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise SystemExit(f'No location found for GAds CID {gads_cid}')
    return rows[0]


def update_supabase_gtm(gads_cid, gtm_id, account_id, container_id):
    r = requests.patch(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={'gads_cid': f'eq.{gads_cid}'},
        headers={**HEADERS, 'Prefer': 'return=representation'},
        json={
            'gtm_id': gtm_id,
            'gtm_account_id': account_id,
            'gtm_container_id': container_id,
            'gtm_container_status': 'has_container',
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


# ── Cache ─────────────────────────────────────────────────────────────────────

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)


# ── Playwright ────────────────────────────────────────────────────────────────

def create_gtm_container(context, account_name, container_name):
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    page = context.new_page()
    try:
        print(f'  Navigating to GTM...')
        page.goto(f'{GTM_URL}#/home', wait_until='domcontentloaded', timeout=60000)
        time.sleep(2)

        page.get_by_role('button', name=re.compile('Create Account', re.I)).first.click(timeout=10000)
        page.wait_for_url(re.compile(r'admin/accounts/create'), timeout=10000)
        time.sleep(1)

        page.locator('input[name="form.account.properties.displayName"]').wait_for(timeout=10000)
        page.locator('input[name="form.account.properties.displayName"]').fill(account_name)
        page.locator('input[name="form.container.properties.displayName"]').fill(container_name)
        page.locator('div.context-picker__row[title="Web"]').click(timeout=10000)
        time.sleep(1)

        pre_workspace_urls = {
            p.url for p in context.pages
            if re.search(r'tagmanager\.google\.com.*workspaces', p.url)
        }

        page.get_by_role('button', name=re.compile(r'^Create$')).click(timeout=10000)

        try:
            tos = page.get_by_role('button', name=re.compile('Yes|I agree|Accept', re.I))
            tos.wait_for(timeout=8000)
            tos.click()
            print('  Accepted TOS.')
        except PlaywrightTimeoutError:
            pass

        workspace_page = None
        for _ in range(25):
            time.sleep(1)
            for p in context.pages:
                if re.search(r'tagmanager\.google\.com.*workspaces', p.url) and p.url not in pre_workspace_urls:
                    workspace_page = p
                    break
            if workspace_page:
                break

        if not workspace_page:
            try:
                page.wait_for_url(re.compile(r'tagmanager\.google\.com.*workspaces'), timeout=10000)
                if page.url not in pre_workspace_urls:
                    workspace_page = page
            except PlaywrightTimeoutError:
                pass

        if not workspace_page:
            raise RuntimeError('Could not find new workspace page after container creation.')

        time.sleep(2)
        workspace_url = workspace_page.url
        print(f'  Workspace URL: {workspace_url}')

        url_match = re.search(r'accounts/(\d+)/containers/(\d+)', workspace_url)
        account_id   = url_match.group(1) if url_match else None
        container_id = url_match.group(2) if url_match else None

        gtm_id = None
        try:
            workspace_page.wait_for_load_state('networkidle', timeout=15000)
            gtm_id = workspace_page.evaluate(
                "() => { const m = document.body.innerText.match(/GTM-[A-Z0-9]{4,10}/); return m ? m[0] : null; }"
            )
            if not gtm_id:
                m = re.search(r'GTM-[A-Z0-9]{4,10}', workspace_page.content())
                gtm_id = m.group(0) if m else None
        except Exception as e:
            print(f'  Page extract warning: {e}')

        if not gtm_id and account_id and container_id:
            gtm_id = _lookup_gtm_id_via_api(account_id, container_id)

        try:
            workspace_page.close()
        except Exception:
            pass

        return gtm_id, account_id, container_id

    finally:
        try:
            page.close()
        except Exception:
            pass


def _lookup_gtm_id_via_api(account_id, container_id):
    from auth import get_gtm_service
    svc = get_gtm_service()
    container = svc.accounts().containers().get(
        path=f'accounts/{account_id}/containers/{container_id}'
    ).execute()
    return container.get('publicId')


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Create GTM account + container for an LNM client.')
    parser.add_argument('--gads-cid', required=True, help='Google Ads Customer ID, e.g. 6322162456')
    parser.add_argument('--name',  default=None, help='Override client name (default: from Supabase)')
    parser.add_argument('--url',   default=None, help='Override container URL (default: from Supabase)')
    parser.add_argument('--dry-run', action='store_true', help='Preview without making changes')
    args = parser.parse_args()

    print(f'Looking up GAds CID {args.gads_cid} in Supabase...')
    loc = fetch_location(args.gads_cid)
    print(f'  Found: {loc["name"]} | {loc["url"]}')

    if loc.get('gtm_id'):
        print(f'  WARNING: gtm_id already set to {loc["gtm_id"]}. Continuing anyway.')

    client_name    = args.name or loc['name']
    container_name = re.sub(r'^https?://', '', args.url or loc['url'] or '').rstrip('/')

    if not container_name:
        raise SystemExit('No URL found. Pass --url or set url in Supabase.')

    print(f'\nAccount name  : {client_name}')
    print(f'Container name: {container_name}')

    if args.dry_run:
        print('\n[DRY RUN] Would create GTM account + container. No changes made.')
        return

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]

        check = context.new_page()
        check.goto(GTM_URL, wait_until='domcontentloaded', timeout=60000)
        if 'accounts.google.com' in check.url:
            raise SystemExit('Not logged in to Google. Log in manually in the Chrome window.')
        check.close()

        print('\nCreating GTM account + container...')
        gtm_id, account_id, container_id = create_gtm_container(context, client_name, container_name)

    if not gtm_id:
        raise SystemExit('Failed to capture GTM container ID.')

    print(f'\n  GTM ID     : {gtm_id}')
    print(f'  Account ID : {account_id}')
    print(f'  Container ID: {container_id}')

    cache = load_cache()
    cache[gtm_id] = {'account_id': account_id, 'container_id': container_id}
    save_cache(cache)
    print(f'  Cached to {CACHE_FILE}')

    update_supabase_gtm(args.gads_cid, gtm_id, account_id, container_id)
    print(f'  Supabase updated: gtm_id={gtm_id}, account_id={account_id}, container_id={container_id}, status=has_container')

    print(f'\nDone. Next step: python setup_tags.py --gads-cid {args.gads_cid}')


if __name__ == '__main__':
    main()
