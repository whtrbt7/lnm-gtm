"""
inject_wordpress.py — Install GTM snippet on an LNM WordPress site.

Reads domain and GTM ID from Supabase by GAds CID. Logs into WordPress,
ensures the WPCode/Insert Headers and Footers plugin is active, then
injects the GTM head + body scripts. Updates Supabase gtm_injected_at on success.

Usage:
  python inject_wordpress.py --gads-cid 6322162456
  python inject_wordpress.py --gads-cid 6322162456 --dry-run

WordPress credentials are read from .env (WP_USERNAME, WP_PASSWORD).
"""

import argparse
import os
import re
import requests
from datetime import datetime, timezone
from html import unescape

from dotenv import load_dotenv

from wp_auth import wp_login, fetch_rest_nonce, WPAuthError
from wp_installer import ensure_plugin_active, PluginInstallError
from wp_injector import inject_gtm, InjectionError

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']

SUPABASE_HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
}


# ── Supabase ──────────────────────────────────────────────────────────────────

def fetch_location(gads_cid, location_id=None):
    if location_id:
        params = {'id': f'eq.{location_id}', 'select': 'id,name,url,gtm_id,gtm_injected_at'}
    else:
        params = {'gads_cid': f'eq.{gads_cid}', 'select': 'id,name,url,gtm_id,gtm_injected_at'}
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/locations',
        params=params,
        headers=SUPABASE_HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise SystemExit(f'No location found for {"ID " + location_id if location_id else "GAds CID " + gads_cid}')
    return rows[0]


def mark_injected(location_id):
    now = datetime.now(timezone.utc).isoformat()
    r = requests.patch(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={'id': f'eq.{location_id}'},
        headers={**SUPABASE_HEADERS, 'Prefer': 'return=representation'},
        json={'gtm_injected_at': now, 'gtm_connected': True, 'gtm_container_status': 'script_injected'},
        timeout=10,
    )
    r.raise_for_status()
    return now


# ── WP Rocket ─────────────────────────────────────────────────────────────────

def fix_wp_rocket_exclusion(session: requests.Session, domain: str) -> str:
    """
    Add googletagmanager to WP Rocket delay_js_exclusions if not already present.
    Returns one of: 'not_installed', 'already_excluded', 'fixed', 'failed'.
    """
    try:
        resp = session.get(
            f'https://{domain}/wp-admin/admin.php',
            params={'page': 'wprocket'},
            timeout=20,
        )
    except Exception:
        return 'failed'

    if 'delay_js_exclusions' not in resp.text:
        return 'not_installed'

    ta_match = re.search(
        r'<textarea[^>]+name="wp_rocket_settings\[delay_js_exclusions\]"[^>]*>(.*?)</textarea>',
        resp.text, re.DOTALL,
    )
    current = unescape(ta_match.group(1)) if ta_match else ''

    if 'googletagmanager' in current:
        return 'already_excluded'

    # Build form data from all <input> fields, then override textarea
    form_data = {}
    for m in re.finditer(r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"', resp.text):
        form_data[m.group(1)] = m.group(2)
    for m in re.finditer(r'<input[^>]+value="([^"]*)"[^>]+name="([^"]+)"', resp.text):
        form_data[m.group(2)] = m.group(1)
    form_data['wp_rocket_settings[delay_js_exclusions]'] = current.strip() + '\ngoogletagmanager'

    try:
        r2 = session.post(
            f'https://{domain}/wp-admin/admin.php',
            params={'page': 'wprocket'},
            data=form_data,
            timeout=30,
            allow_redirects=True,
        )
        return 'fixed' if r2.status_code in (200, 302) else 'failed'
    except Exception:
        return 'failed'


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Inject GTM into a WordPress site via Supabase CID.')
    parser.add_argument('--gads-cid', required=True, help='Google Ads CID, e.g. 6322162456')
    parser.add_argument('--location-id', default=None, help='Supabase location UUID (disambiguates shared CIDs)')
    parser.add_argument('--dry-run', action='store_true', help='Preview without making changes')
    args = parser.parse_args()

    username = os.getenv('WP_USERNAME')
    password = os.getenv('WP_PASSWORD')
    if not username or not password:
        raise SystemExit('WP_USERNAME and WP_PASSWORD must be set in .env')

    print(f'Fetching location for CID {args.gads_cid}...')
    loc = fetch_location(args.gads_cid, location_id=args.location_id)

    name   = loc['name']
    domain = re.sub(r'^https?://', '', loc.get('url') or '').split('/')[0]
    gtm_id = loc.get('gtm_id')

    if not domain:
        raise SystemExit('No URL in Supabase. Add url to the location record first.')
    if not gtm_id:
        raise SystemExit('No gtm_id in Supabase. Run create_container.py first.')

    print(f'  Client : {name}')
    print(f'  Domain : {domain}')
    print(f'  GTM ID : {gtm_id}')

    if loc.get('gtm_injected_at'):
        print(f'  WARNING: Already injected at {loc["gtm_injected_at"]}. Continuing anyway.')

    if args.dry_run:
        print('\n[DRY RUN] Would inject GTM on WordPress site. No changes made.')
        return

    print(f'\nLogging into {domain}...')
    try:
        session = wp_login(domain, username, password)
    except WPAuthError as e:
        raise SystemExit(f'WP login failed: {e}')

    print('  Fetching REST nonce...')
    try:
        rest_nonce = fetch_rest_nonce(session, domain)
    except WPAuthError as e:
        raise SystemExit(f'Could not get REST nonce: {e}')

    print('  Ensuring plugin active...')
    try:
        ensure_plugin_active(session, domain, rest_nonce)
    except PluginInstallError as e:
        raise SystemExit(f'Plugin install failed: {e}')

    print('  Injecting GTM...')
    try:
        method = inject_gtm(session, domain, gtm_id, rest_nonce)
    except InjectionError as e:
        raise SystemExit(f'Injection failed: {e}')

    print(f'  Injected via {method}')

    print('  Checking WP Rocket...')
    rocket_result = fix_wp_rocket_exclusion(session, domain)
    rocket_msg = {
        'not_installed': 'not installed',
        'already_excluded': 'googletagmanager already excluded',
        'fixed': 'added googletagmanager exclusion',
        'failed': 'could not reach WP Rocket settings (Cloudflare?)',
    }.get(rocket_result, rocket_result)
    print(f'  WP Rocket: {rocket_msg}')

    ts = mark_injected(loc['id'])
    print(f'  Supabase updated: gtm_injected_at = {ts}, gtm_connected = true')

    print(f'\nDone. GTM {gtm_id} is live on {domain}')


if __name__ == '__main__':
    main()
