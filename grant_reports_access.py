"""
Adds reports@leadsnearme.com as Administrator to all GTM accounts
under achiu@leadsnearme.com that aren't already visible to reports@.

Prerequisites:
    1. Run get_alex_token.py first to generate token_alex.json
    2. Have token.json (reports@ credentials) for the reports account list

Usage:
    python grant_reports_access.py [--dry-run]
"""

import json
import os
import sys
import time
import argparse

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
TOKEN_REPORTS = os.path.join(SCRIPT_DIR, 'token.json')
TOKEN_ALEX    = os.path.join(SCRIPT_DIR, 'token_alex.json')
REPORTS_EMAIL = 'reports@leadsnearme.com'


def get_service(token_path):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    with open(token_path) as f:
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
        print(f"  [auth] Refreshing token from {os.path.basename(token_path)}...")
        creds.refresh(Request())
        data['token'] = creds.token
        data['expiry'] = creds.expiry.isoformat() if creds.expiry else None
        with open(token_path, 'w') as f:
            json.dump(data, f, indent=2)

    return build('tagmanager', 'v2', credentials=creds)


def api_call(call, max_retries=6, base_delay=3.0):
    from googleapiclient.errors import HttpError
    delay = base_delay
    for attempt in range(max_retries):
        try:
            return call()
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < max_retries - 1:
                print(f"  [retry] HTTP {e.resp.status}, waiting {delay:.0f}s...")
                time.sleep(delay)
                delay = min(delay * 2, 60)
            else:
                raise


def run(dry_run=False):
    if not os.path.exists(TOKEN_ALEX):
        print(f"ERROR: {TOKEN_ALEX} not found.")
        print("Run this first:")
        print("  python get_alex_token.py")
        sys.exit(1)

    print("Loading services...")
    svc_alex    = get_service(TOKEN_ALEX)
    svc_reports = get_service(TOKEN_REPORTS)

    # Get accounts visible to reports@ (to know which ones to skip)
    print("Fetching accounts visible to reports@...")
    reports_accts = api_call(lambda: svc_reports.accounts().list().execute())
    reports_ids   = {a['accountId'] for a in reports_accts.get('account', [])}
    print(f"  reports@ sees {len(reports_ids)} accounts")

    # Get ALL accounts visible to achiu@
    print("Fetching accounts visible to achiu@ (token_alex)...")
    alex_accts = api_call(lambda: svc_alex.accounts().list().execute())
    all_alex   = alex_accts.get('account', [])
    print(f"  achiu@ sees {len(all_alex)} accounts")

    # Find accounts achiu@ has that reports@ cannot see
    missing = [a for a in all_alex if a['accountId'] not in reports_ids]
    print(f"\n{len(missing)} accounts need reports@ access granted")

    if not missing:
        print("Nothing to do — reports@ already has access to all achiu@ accounts.")
        return

    if dry_run:
        print("\n[DRY RUN] Would add reports@ as Admin to:")
        for a in missing:
            print(f"  {a['accountId']}: {a['name']}")
        return

    granted = 0
    already  = 0
    errors   = 0

    for a in missing:
        acct_id   = a['accountId']
        acct_name = a['name']
        parent    = f"accounts/{acct_id}"

        # Check if reports@ already has a permission entry
        try:
            existing = api_call(
                lambda p=parent: svc_alex.accounts().user_permissions().list(parent=p).execute()
            )
            existing_emails = {
                u.get('emailAddress', '').lower()
                for u in existing.get('userPermission', [])
            }
            if REPORTS_EMAIL.lower() in existing_emails:
                print(f"  · {acct_name}: already has access")
                already += 1
                time.sleep(0.3)
                continue
        except Exception as e:
            print(f"  ? {acct_name}: could not list permissions ({e}), trying to grant anyway")

        # Grant admin access
        body = {
            'emailAddress': REPORTS_EMAIL,
            'accountAccess': {'permission': 'admin'},
        }
        try:
            api_call(
                lambda p=parent, b=body:
                    svc_alex.accounts().user_permissions().create(parent=p, body=b).execute()
            )
            print(f"  ✓ {acct_name}")
            granted += 1
        except Exception as e:
            print(f"  ✗ {acct_name}: {e}")
            errors += 1

        time.sleep(0.5)

    print(f"\n=== Done: {granted} granted, {already} already had access, {errors} errors ===")
    if errors == 0 and granted > 0:
        print("\nNext steps:")
        print("  1. Wait ~30s for Google to propagate the permissions")
        print("  2. Rebuild reports@ index and push:")
        print("     python push_gtm_setup.py --tier 3 --rebuild-index")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview which accounts would be granted access')
    args = parser.parse_args()
    run(dry_run=args.dry_run)
