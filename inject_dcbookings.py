"""
inject_dcbookings.py — Inject DCBookings iframe + script into a WP site footer via WPCode.

Reads existing header/body/footer from the WPCode settings page before writing,
so existing GTM code is preserved. Updates scheduler_type in Supabase on success.

Usage:
  python inject_dcbookings.py --gads-cid 6342215944
  python inject_dcbookings.py --gads-cid 6342215944 --dry-run
"""

import argparse
import os
import re
import html
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

from wp_auth import wp_login, fetch_rest_nonce, WPAuthError

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
SB_HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
    'Prefer': 'return=representation',
}


def fetch_location(gads_cid):
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={'gads_cid': f'eq.{gads_cid}', 'select': 'id,name,url,scheduler_type'},
        headers=SB_HEADERS, timeout=10,
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise SystemExit(f'No location for GAds CID {gads_cid}')
    return rows[0]


def fetch_wpcode_page(session, domain):
    """GET WPCode headers/footers page, return (nonce, header_text, body_text, footer_text)."""
    resp = session.get(
        f'https://{domain}/wp-admin/admin.php',
        params={'page': 'wpcode-headers-footers'},
        timeout=30,
    )
    resp.raise_for_status()
    page = resp.text

    nonce_match = re.search(r'name="insert-headers-and-footers_nonce"[^>]*value="([^"]+)"', page)
    if not nonce_match:
        raise SystemExit('Could not extract WPCode nonce — is WPCode active?')
    nonce = nonce_match.group(1)

    def extract_textarea(name):
        m = re.search(rf'name="{re.escape(name)}"[^>]*>(.*?)</textarea>', page, re.DOTALL)
        return html.unescape(m.group(1)) if m else ''

    header = extract_textarea('ihaf_insert_header')
    body   = extract_textarea('ihaf_insert_body')
    footer = extract_textarea('ihaf_insert_footer')
    return nonce, header, body, footer


DC_IFRAME = (
    '<iframe class="dc-bookings" id="dc-bookings" '
    'src="https://bookings.d14e.io?domain=lanier&shopId=66843b3597c22ed870010841" '
    'data-overflow="" style="border: 0px; position: fixed; z-index: 2147483647; '
    'width: 100vw; height: 100%; inset: 0px; transition: opacity 0.38s ease 0s; '
    'opacity: 0; visibility: hidden;"></iframe>'
)
DC_SCRIPT = '<script src="https://bookings.d14e.io/dcPortal.js"></script>'
DC_BLOCK  = f'<!-- DCBookings -->\n{DC_IFRAME}\n{DC_SCRIPT}'


def post_wpcode(session, domain, nonce, header, body, footer):
    payload = {
        'insert-headers-and-footers_nonce': nonce,
        '_wp_http_referer': '/wp-admin/admin.php?page=wpcode-headers-footers',
        'ihaf_insert_header': header,
        'ihaf_insert_body':   body,
        'ihaf_insert_footer': footer,
    }
    resp = session.post(
        f'https://{domain}/wp-admin/admin.php',
        params={'page': 'wpcode-headers-footers'},
        data=payload,
        allow_redirects=True,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise SystemExit(f'WPCode POST failed: {resp.status_code}')


def update_supabase(gads_cid):
    r = requests.patch(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={'gads_cid': f'eq.{gads_cid}'},
        headers=SB_HEADERS,
        json={'scheduler_type': 'dcbookings'},
        timeout=10,
    )
    r.raise_for_status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--gads-cid', required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    username = os.getenv('WP_USERNAME')
    password = os.getenv('WP_PASSWORD')
    if not username or not password:
        raise SystemExit('WP_USERNAME / WP_PASSWORD not set in .env')

    loc = fetch_location(args.gads_cid)
    domain = loc['url'].lstrip('https://').lstrip('http://').rstrip('/')
    print(f'Client : {loc["name"]}')
    print(f'Domain : {domain}')
    print(f'Sched  : {loc.get("scheduler_type")} → dcbookings')

    if not domain:
        raise SystemExit('No URL in Supabase')

    print(f'\nLogging into {domain}...')
    session = wp_login(domain, username, password)

    print('Fetching current WPCode content...')
    nonce, header, body, footer = fetch_wpcode_page(session, domain)
    print(f'  header: {len(header)} chars')
    print(f'  body:   {len(body)} chars')
    print(f'  footer: {len(footer)} chars')

    if 'bookings.d14e.io' in footer:
        print('DCBookings already in footer — nothing to do.')
        return

    new_footer = (footer.rstrip() + '\n\n' + DC_BLOCK).lstrip('\n') if footer.strip() else DC_BLOCK

    print('\nNew footer to write:')
    print(new_footer)

    if args.dry_run:
        print('\n[DRY RUN] No changes made.')
        return

    print('\nPosting to WPCode...')
    post_wpcode(session, domain, nonce, header, body, new_footer)
    print('  Injected.')

    print('Updating Supabase scheduler_type → dcbookings...')
    update_supabase(args.gads_cid)
    print('  Done.')

    print(f'\nDCBookings live on {domain}')


if __name__ == '__main__':
    main()
