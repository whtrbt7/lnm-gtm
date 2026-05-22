"""
batch_p1_setup.py — Pattern 1 batch GTM container creation + tag setup.

For each account in Supabase with a GAds CID, no GTM ID, a website URL,
and conversion labels set, this script:
  1. Creates a GTM Account + Web container via API
  2. Writes gtm_id / gtm_account_id / gtm_container_id back to Supabase
  3. Calls setup_tags.py --gads-cid to push LNM standard tags

Usage:
    python batch_p1_setup.py [--dry-run] [--limit N] [--cid CID] [--token-file FILE]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

import requests
from dotenv import load_dotenv
from googleapiclient.errors import HttpError

load_dotenv()

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
DB_HEADERS   = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
}


def clean_url(url):
    return re.sub(r'^https?://', '', str(url or '')).rstrip('/')


def get_gtm_service(token_file):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    path = os.path.join(SCRIPT_DIR, token_file)
    with open(path) as f:
        data = json.load(f)
    creds = Credentials(**{k: v for k, v in data.items()
                           if k in ['token', 'refresh_token', 'token_uri',
                                    'client_id', 'client_secret', 'scopes']})
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        data['token'] = creds.token
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    from googleapiclient.discovery import build
    return build('tagmanager', 'v2', credentials=creds)


def _api(call, retries=8, base_delay=3.0):
    delay = base_delay
    for i in range(retries):
        try:
            return call()
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and i < retries - 1:
                print(f'    [retry] HTTP {e.resp.status}, waiting {delay:.1f}s')
                time.sleep(delay)
                delay = min(delay * 2, 60)
            else:
                raise


def fetch_candidates(cid_filter=None):
    params = {
        'select': 'gads_cid,name,url,gtm_id,gads_conversion_id,gads_appt_label,gads_phone_label,scheduler_type,churned,no_gads',
        'gads_cid': 'not.is.null',
        'gtm_id':   'is.null',
        'url':      'not.is.null',
    }
    if cid_filter:
        params['gads_cid'] = f'eq.{cid_filter}'

    r = requests.get(f'{SUPABASE_URL}/rest/v1/locations',
                     params=params, headers=DB_HEADERS, timeout=15)
    r.raise_for_status()
    rows = r.json()

    seen_cids = set()
    out = []
    for d in rows:
        if d.get('churned') or d.get('no_gads'):
            continue
        conv = str(d.get('gads_conversion_id') or '')
        if not conv:
            continue
        if not (d.get('gads_appt_label') and d.get('gads_phone_label')):
            continue
        cid = d['gads_cid']
        if cid in seen_cids:
            continue
        seen_cids.add(cid)
        out.append(d)
    return out


def update_supabase_gtm(gads_cid, gtm_id, account_id, container_id):
    r = requests.patch(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={'gads_cid': f'eq.{gads_cid}'},
        headers={**DB_HEADERS, 'Prefer': 'return=minimal'},
        json={
            'gtm_id':            gtm_id,
            'gtm_account_id':    str(account_id),
            'gtm_container_id':  str(container_id),
            'gtm_container_status': 'has_container',
        },
        timeout=10,
    )
    r.raise_for_status()


def create_container(service, name, url):
    account_name   = name
    container_name = clean_url(url) or name

    account = _api(lambda an=account_name:
        service.accounts().create(body={'name': an}).execute())
    account_id = account['accountId']

    container = _api(lambda aid=account_id, cn=container_name:
        service.accounts().containers().create(
            parent=f'accounts/{aid}',
            body={'name': cn, 'usageContext': ['WEB']},
        ).execute())

    gtm_id       = container['publicId']
    container_id = container['containerId']
    return gtm_id, account_id, container_id


def run_setup_tags(gads_cid, token_file, dry_run=False):
    cmd = [
        sys.executable,
        os.path.join(SCRIPT_DIR, 'setup_tags.py'),
        '--gads-cid', str(gads_cid),
        '--token-file', os.path.join(SCRIPT_DIR, token_file),
    ]
    if dry_run:
        print(f'    [dry-run] would run: {" ".join(cmd)}')
        return True

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f'    [setup_tags ERROR]\n{result.stdout[-800:]}\n{result.stderr[-400:]}')
        return False
    print(result.stdout[-600:])
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run',    action='store_true')
    parser.add_argument('--limit',      type=int, default=0)
    parser.add_argument('--cid',        help='Process only this GAds CID')
    parser.add_argument('--token-file', default='token_analytics.json')
    parser.add_argument('--skip-tags',  action='store_true', help='Only create containers, skip setup_tags')
    args = parser.parse_args()

    candidates = fetch_candidates(cid_filter=args.cid)
    if args.limit:
        candidates = candidates[:args.limit]

    print(f'Pattern 1 batch: {len(candidates)} accounts to process '
          f'(dry_run={args.dry_run})\n')

    if args.dry_run:
        for d in candidates:
            print(f'  {d["gads_cid"]:15s} {d["name"]}  url={d["url"]}  sched={d["scheduler_type"]}')
        return

    service = get_gtm_service(args.token_file)

    ok = fail = skip = 0
    for d in candidates:
        cid  = d['gads_cid']
        name = d['name']
        url  = d['url']
        print(f'\n[{cid}] {name}')

        # Step 1: create GTM container
        try:
            gtm_id, acct_id, ctr_id = create_container(service, name, url)
            print(f'  container: {gtm_id} (acct={acct_id} ctr={ctr_id})')
            update_supabase_gtm(cid, gtm_id, acct_id, ctr_id)
            time.sleep(1.5)
        except Exception as e:
            print(f'  [ERROR] container creation: {e}')
            fail += 1
            continue

        if args.skip_tags:
            ok += 1
            continue

        # Step 2: setup_tags
        print(f'  running setup_tags...')
        success = run_setup_tags(cid, args.token_file)
        if success:
            ok += 1
        else:
            fail += 1

    print(f'\n=== Done: ok={ok} fail={fail} skip={skip} ===')


if __name__ == '__main__':
    main()
