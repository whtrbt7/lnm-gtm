"""
Audit and fix GTM/GA4/WP Rocket conversion tracking for LNM locations.
Processes one location at a time with rate-limit handling.
"""

import json
import os
import sys
import time
import re
import requests
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv('/Users/alexchiu/llmprojects/lnm-gads/.env')

SUPABASE_URL = os.getenv('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
TOKEN_FILES = [
    '/Users/alexchiu/llmprojects/lnm-gtm/token_analytics.json',
    '/Users/alexchiu/llmprojects/lnm-gtm/token_reports.json',
    '/Users/alexchiu/llmprojects/lnm-gtm/token_analytics2.json',
]
WP_USER      = 'lnm-dev'
WP_PASS      = '1£qv+4c15Zx;FV}O'

PLACEHOLDER_GA4 = {'G-BREADCRUMBS', 'G-PRELOADER', 'G-PLACEHOLDER', 'G-XXXXXXXX'}


def gtm_service(token_file=None):
    f = token_file or TOKEN_FILES[0]
    creds = Credentials.from_authorized_user_file(f)
    if creds.expired:
        creds.refresh(Request())
    return build('tagmanager', 'v2', credentials=creds)


def gtm_call(fn, max_tries=12):
    for i in range(max_tries):
        try:
            return fn()
        except HttpError as e:
            if e.resp.status == 429:
                wait = 60
                print(f'    [rate limit] waiting {wait}s (attempt {i+1})...')
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            if 'Connection reset' in str(e) or 'ConnectionReset' in str(e):
                print(f'    [conn reset] waiting 10s (attempt {i+1})...')
                time.sleep(10)
            else:
                raise
    raise RuntimeError('Max retries exceeded')


def get_tags(service, acct, ctr):
    workspaces = gtm_call(lambda: service.accounts().containers().workspaces().list(
        parent=f'accounts/{acct}/containers/{ctr}'
    ).execute()).get('workspace', [])
    if not workspaces:
        return None, []
    ws_id = workspaces[0]['workspaceId']
    tags = gtm_call(lambda: service.accounts().containers().workspaces().tags().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws_id}'
    ).execute()).get('tag', [])
    return ws_id, tags


def parse_tags(tags):
    result = {'ga4_tag': None, 'aw_conv_id': None, 'phone_label': None, 'appt_label': None}
    for t in tags:
        params = {p['key']: p.get('value', '') for p in t.get('parameter', [])}
        if t['type'] == 'googtag':
            tag_id = params.get('tagId', '')
            if tag_id.startswith('G-'):
                result['ga4_tag'] = tag_id
            elif tag_id.startswith('AW-'):
                result['aw_conv_id'] = tag_id.replace('AW-', '')
        elif t['type'] == 'awct':
            label = params.get('conversionLabel', '')
            name_lower = t['name'].lower()
            if 'phone' in name_lower:
                result['phone_label'] = label
            elif any(w in name_lower for w in ['appt', 'book', 'appointment']):
                result['appt_label'] = label
    return result


def update_gtm_ga4_tag(service, acct, ctr, ws_id, tags, new_ga4_id):
    ga4_tag = next((t for t in tags if t['type'] == 'googtag' and
                    t.get('parameter', [{}])[0].get('value', '').startswith('G-')), None)
    if not ga4_tag:
        return False, 'No GA4 googtag found'
    tag_id = ga4_tag['tagId']
    path = f'accounts/{acct}/containers/{ctr}/workspaces/{ws_id}/tags/{tag_id}'
    updated = dict(ga4_tag)
    updated['parameter'] = [p for p in ga4_tag.get('parameter', []) if p['key'] != 'tagId']
    updated['parameter'].append({'type': 'template', 'key': 'tagId', 'value': new_ga4_id})
    gtm_call(lambda: service.accounts().containers().workspaces().tags().update(
        path=path, body=updated
    ).execute())
    return True, f'GA4 tag updated to {new_ga4_id}'


def publish_gtm(service, acct, ctr, ws_id, note):
    ver = gtm_call(lambda: service.accounts().containers().workspaces().create_version(
        path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws_id}',
        body={'name': note[:100]}
    ).execute())
    ver_path = ver.get('containerVersion', {}).get('path')
    if not ver_path:
        return False, 'No version path'
    gtm_call(lambda: service.accounts().containers().versions().publish(path=ver_path).execute())
    return True, ver.get('containerVersion', {}).get('containerVersionId')


def supabase_update(location_id, fields):
    resp = requests.patch(
        f'{SUPABASE_URL}/rest/v1/locations?id=eq.{location_id}',
        headers={
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json',
            'Prefer': 'return=minimal',
        },
        json=fields
    )
    return resp.status_code in (200, 204)


def check_wp_rocket(domain):
    """Returns (has_delay, has_gtm_exclusion, session_or_None)"""
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; LNMAudit/1.0)'})
    try:
        # Login
        url = f'https://{domain}/wp-login.php'
        session.cookies.set('wordpress_test_cookie', 'WP Cookie check', domain=domain)
        resp = session.post(url, data={
            'log': WP_USER, 'pwd': WP_PASS,
            'wp-submit': 'Log In', 'redirect_to': '/wp-admin/', 'testcookie': '1'
        }, timeout=20, allow_redirects=True)
        if '/wp-admin/' not in resp.url:
            return None, None, None  # login failed

        # Get WP Rocket settings
        resp = session.get(f'https://{domain}/wp-admin/admin.php?page=wprocket', timeout=20)
        if 'delay_js_exclusions' not in resp.text:
            return False, None, None  # WP Rocket not present

        match = re.search(r'<textarea[^>]+name="wp_rocket_settings\[delay_js_exclusions\]"[^>]*>(.*?)</textarea>',
                          resp.text, re.DOTALL)
        if not match:
            return True, None, None
        exclusions = match.group(1)
        has_gtm = 'googletagmanager' in exclusions
        return True, has_gtm, session
    except Exception as e:
        return None, None, None  # can't reach site


def fix_wp_rocket(session, domain):
    """Add googletagmanager to delay_js_exclusions."""
    try:
        resp = session.get(f'https://{domain}/wp-admin/admin.php?page=wprocket', timeout=20)
        # Extract all form fields
        form_data = {}
        for m in re.finditer(r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"', resp.text):
            form_data[m.group(1)] = m.group(2)
        for m in re.finditer(r'<input[^>]+value="([^"]*)"[^>]+name="([^"]+)"', resp.text):
            form_data[m.group(2)] = m.group(1)
        # Update exclusions
        key = 'wp_rocket_settings[delay_js_exclusions]'
        ta_match = re.search(r'<textarea[^>]+name="wp_rocket_settings\[delay_js_exclusions\]"[^>]*>(.*?)</textarea>',
                             resp.text, re.DOTALL)
        current = ta_match.group(1) if ta_match else ''
        form_data[key] = current.strip() + '\ngoogletagmanager'
        # Submit
        resp2 = session.post(
            f'https://{domain}/wp-admin/admin.php?page=wprocket',
            data=form_data, timeout=30, allow_redirects=True
        )
        return resp2.status_code in (200, 302)
    except Exception:
        return False


def process_location(loc, service, correct_ga4=None):
    name = loc['name']
    url = loc.get('url')
    acct = loc.get('gtm_account_id')
    ctr = loc.get('gtm_container_id')
    loc_id = loc['id']

    print(f'\n{"="*60}')
    print(f'  {name}')
    print(f'  {url or "NO URL"}  GTM: {loc.get("gtm_id","none")}')
    print(f'{"="*60}')

    if not url or not acct or not ctr:
        print('  SKIP: no URL or GTM')
        return {'status': 'skipped', 'reason': 'no url/gtm'}

    fixes = []
    crm_updates = {}

    # --- GTM audit ---
    print('  Fetching GTM tags...')
    active_service = service
    try:
        ws_id, tags = get_tags(active_service, acct, ctr)
    except HttpError as e:
        if e.resp.status == 404:
            for token_file in TOKEN_FILES[1:]:
                print(f'  [404] trying {os.path.basename(token_file)}...')
                try:
                    active_service = gtm_service(token_file)
                    ws_id, tags = get_tags(active_service, acct, ctr)
                    break
                except HttpError as e2:
                    if e2.resp.status == 404:
                        continue
                    print(f'  GTM ERROR: {e2}')
                    return {'status': 'error', 'reason': str(e2)}
                except Exception as e2:
                    print(f'  GTM ERROR: {e2}')
                    return {'status': 'error', 'reason': str(e2)}
            else:
                print(f'  GTM ERROR: not found in any token')
                return {'status': 'error', 'reason': 'not found in any token'}
        else:
            print(f'  GTM ERROR: {e}')
            return {'status': 'error', 'reason': str(e)}
    except Exception as e:
        print(f'  GTM ERROR: {e}')
        return {'status': 'error', 'reason': str(e)}

    parsed = parse_tags(tags)
    print(f'  GTM GA4 tag:   {parsed["ga4_tag"]}')
    print(f'  GTM AW conv:   {parsed["aw_conv_id"]}')
    print(f'  CRM GA4:       {loc.get("ga4_measurement_id")}')
    print(f'  CRM conv:      {loc.get("gads_conversion_id")}')

    gtm_changed = False

    # Fix GA4 tag in GTM if placeholder/wrong
    gtm_ga4 = parsed['ga4_tag']
    crm_ga4 = loc.get('ga4_measurement_id')
    if correct_ga4 and gtm_ga4 != correct_ga4:
        print(f'  Fixing GTM GA4: {gtm_ga4} -> {correct_ga4}')
        ok, msg = update_gtm_ga4_tag(active_service, acct, ctr, ws_id, tags, correct_ga4)
        if ok:
            fixes.append(f'GTM GA4: {gtm_ga4} -> {correct_ga4}')
            gtm_changed = True
        else:
            print(f'  GA4 fix failed: {msg}')
    elif gtm_ga4 and gtm_ga4 not in PLACEHOLDER_GA4 and crm_ga4 != gtm_ga4:
        # GTM has real GA4 ID, CRM doesn't — just update CRM
        crm_updates['ga4_measurement_id'] = gtm_ga4
        fixes.append(f'CRM GA4: {crm_ga4} -> {gtm_ga4}')
    elif not gtm_ga4 or gtm_ga4 in PLACEHOLDER_GA4:
        print(f'  GA4 NEEDS MANUAL FIX: GTM has placeholder/none ({gtm_ga4})')

    # Fix conversion ID in CRM if mismatch
    gtm_conv = parsed['aw_conv_id']
    crm_conv = loc.get('gads_conversion_id')
    if gtm_conv and gtm_conv != crm_conv:
        crm_updates['gads_conversion_id'] = gtm_conv
        fixes.append(f'CRM conv: {crm_conv} -> {gtm_conv}')

    # Publish GTM if changed
    if gtm_changed:
        print('  Publishing GTM...')
        try:
            ok, ver_id = publish_gtm(active_service, acct, ctr, ws_id, 'Fix GA4 measurement ID')
            if ok:
                fixes.append(f'GTM published (v{ver_id})')
            else:
                print(f'  Publish failed: {ver_id}')
        except Exception as e:
            print(f'  Publish error: {e}')

    # Update CRM
    if crm_updates:
        if correct_ga4 and 'ga4_measurement_id' not in crm_updates:
            crm_updates['ga4_measurement_id'] = correct_ga4
        print(f'  Updating CRM: {crm_updates}')
        supabase_update(loc_id, crm_updates)

    # --- WP Rocket ---
    domain = url.replace('https://', '').replace('http://', '').strip('/')
    print(f'  Checking WP Rocket on {domain}...')
    has_rocket, has_exclusion, session = check_wp_rocket(domain)
    if has_rocket is None:
        print('  WP Rocket: could not reach site (Cloudflare block?)')
    elif not has_rocket:
        print('  WP Rocket: not installed')
    elif has_exclusion:
        print('  WP Rocket: googletagmanager already excluded ✓')
    else:
        print('  WP Rocket: fixing exclusion...')
        ok = fix_wp_rocket(session, domain)
        if ok:
            fixes.append('WP Rocket: added googletagmanager exclusion')
        else:
            print('  WP Rocket fix failed')

    if fixes:
        print(f'  FIXED: {"; ".join(fixes)}')
    else:
        print('  No fixes needed')

    return {'status': 'done', 'fixes': fixes}


def main():
    # Load location list from JSON arg or use built-in Victory list
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            locations = json.load(f)
    else:
        print('Usage: python audit_locations.py <locations.json> [correct_ga4_id]')
        sys.exit(1)

    correct_ga4 = sys.argv[2] if len(sys.argv) > 2 else None
    service = gtm_service()
    results = []

    for i, loc in enumerate(locations):
        print(f'\n[{i+1}/{len(locations)}]')
        result = process_location(loc, service, correct_ga4)
        results.append({'name': loc['name'], **result})
        # Small gap between locations to stay under rate limits
        if i < len(locations) - 1:
            time.sleep(5)

    print('\n\n=== SUMMARY ===')
    for r in results:
        status = r.get('status', '?')
        fixes = r.get('fixes', [])
        print(f'  [{status}] {r["name"]}')
        for f in fixes:
            print(f'    - {f}')


if __name__ == '__main__':
    main()
