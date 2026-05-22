"""
push_callrail_dni.py — Bulk-add CallRail DNI tag to all LNM GTM containers.

For each location that has gtm_id + gtm_account_id + callrail_company_id:
  1. Fetch the CallRail swap.js URL via CallRail API
  2. Ensure 'C - CallRail Account ID' variable exists in the GTM workspace
  3. Ensure 'CallRail - DNI - Swap Script' custom HTML tag exists on All Pages
  4. Skip locations where the tag already exists (idempotent)

Results saved to push_callrail_dni_results.json (resumable).

Usage:
  python push_callrail_dni.py               # run all eligible
  python push_callrail_dni.py --dry-run     # preview only
  python push_callrail_dni.py --limit 10    # process first N
  python push_callrail_dni.py --reset       # clear results and re-run all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).resolve().parent

# ── Config ────────────────────────────────────────────────────────────────────

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
SB_HEADERS   = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
}

CALLRAIL_API_KEY = os.environ.get('CALLRAIL_API_KEY', '36497188d7030dbe692425202acf5a63')

GTM_TOKEN_MAP = {
    'analytics@leadsnearme.com':  SCRIPT_DIR / 'token_analytics.json',
    'analytics2@leadsnearme.com': SCRIPT_DIR / 'token_analytics2.json',
    'reports@leadsnearme.com':    SCRIPT_DIR / 'token_reports.json',
}
GTM_TOKEN_DEFAULT = SCRIPT_DIR / 'token_analytics.json'

RESULTS_FILE = SCRIPT_DIR / 'push_callrail_dni_results.json'

DNI_TAG_NAME = 'CallRail - DNI - Swap Script'
CR_VAR_NAME  = 'C - CallRail Account ID'

# ── Supabase ──────────────────────────────────────────────────────────────────

def fetch_eligible_locations() -> list[dict]:
    """All locations with GTM IDs and CallRail company ID."""
    params = {
        'select':               'id,name,gtm_id,gtm_account_id,gtm_container_id,gtm_lnm_acct,callrail_account_id,callrail_company_id',
        'gtm_id':               'not.is.null',
        'gtm_account_id':       'not.is.null',
        'gtm_container_id':     'not.is.null',
        'callrail_company_id':  'not.is.null',
        'limit':                '1000',
    }
    r = requests.get(f'{SUPABASE_URL}/rest/v1/locations', params=params, headers=SB_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


# ── CallRail ──────────────────────────────────────────────────────────────────

import re

def fetch_callrail_script_url(account_id: str, company_id: str) -> str | None:
    r = requests.get(
        f'https://api.callrail.com/v3/a/{account_id}/companies/{company_id}.json',
        headers={'Authorization': f'Token token={CALLRAIL_API_KEY}'},
        timeout=10,
    )
    r.raise_for_status()
    url = r.json().get('script_url', '')
    if not url:
        return None
    return ('https:' + url) if url.startswith('//') else url


# ── GTM helpers (mirrors setup_tags.py) ──────────────────────────────────────

def get_gtm_service(token_file: Path):
    import sys as _sys
    _sys.path.insert(0, str(SCRIPT_DIR))
    from setup_tags import get_gtm_service as _get
    return _get(str(token_file))


def _call(fn, max_retries=6, base_delay=5.0):
    from googleapiclient.errors import HttpError
    for attempt in range(max_retries):
        try:
            return fn()
        except HttpError as e:
            if e.resp.status == 429:
                delay = base_delay * (2 ** attempt)
                print(f'    [429] rate limit — sleeping {delay:.0f}s')
                time.sleep(delay)
            else:
                raise
    raise RuntimeError('Max retries exceeded (429)')


def create_and_publish_version(service, acct: str, ctr: str, ws: str, name: str) -> str:
    version_resp = _call(lambda: service.accounts().containers().workspaces().create_version(
        path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}',
        body={'name': name, 'notes': 'Automated via LNM GTM scripts'},
    ).execute())
    version_id = version_resp['containerVersion']['containerVersionId']
    _call(lambda: service.accounts().containers().versions().publish(
        path=f'accounts/{acct}/containers/{ctr}/versions/{version_id}',
    ).execute())
    return version_id


def get_workspace(service, acct: str, ctr: str) -> str:
    resp = _call(lambda: service.accounts().containers().workspaces().list(
        parent=f'accounts/{acct}/containers/{ctr}'
    ).execute())
    ws = resp.get('workspace', [])
    return ws[0]['workspaceId'] if ws else '1'


def list_tags(service, acct: str, ctr: str, ws: str) -> dict[str, str]:
    resp = _call(lambda: service.accounts().containers().workspaces().tags().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())
    return {t['name']: t['tagId'] for t in resp.get('tag', [])}


def list_variables(service, acct: str, ctr: str, ws: str) -> dict[str, str]:
    resp = _call(lambda: service.accounts().containers().workspaces().variables().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())
    return {v['name']: v['variableId'] for v in resp.get('variable', [])}


def list_triggers(service, acct: str, ctr: str, ws: str) -> dict[str, str]:
    resp = _call(lambda: service.accounts().containers().workspaces().triggers().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())
    return {t['name']: t['triggerId'] for t in resp.get('trigger', [])}


def ensure_variable(service, acct, ctr, ws, body, existing):
    name   = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    if name in existing:
        return existing[name], 'existed'
    result = _call(lambda: service.accounts().containers().workspaces().variables().create(
        parent=parent,
        body={k: v for k, v in body.items() if k not in ('accountId', 'containerId', 'variableId')}
    ).execute())
    return result['variableId'], 'new'


def ensure_tag(service, acct, ctr, ws, body, existing):
    name   = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    if name in existing:
        return existing[name], 'existed'
    result = _call(lambda: service.accounts().containers().workspaces().tags().create(
        parent=parent,
        body={k: v for k, v in body.items() if k not in ('accountId', 'containerId', 'tagId')}
    ).execute())
    return result['tagId'], 'new'


def get_all_pages_trigger_id(triggers: dict[str, str], service, acct, ctr, ws) -> str:
    if 'All Pages' in triggers:
        return triggers['All Pages']
    # Create it if somehow missing
    result = _call(lambda: service.accounts().containers().workspaces().triggers().create(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}',
        body={'name': 'All Pages', 'type': 'PAGEVIEW'},
    ).execute())
    return result['triggerId']


# ── Tag / variable bodies ─────────────────────────────────────────────────────

def callrail_variable_body(company_id: str) -> dict:
    return {
        'name': CR_VAR_NAME,
        'type': 'c',
        'parameter': [{'type': 'TEMPLATE', 'key': 'value', 'value': company_id}],
    }


def callrail_dni_tag_body(script_url: str, trigger_id: str) -> dict:
    html = f'<script type="text/javascript" async src="{script_url}"></script>\n'
    return {
        'name': DNI_TAG_NAME,
        'type': 'html',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'html',                 'value': html},
            {'type': 'BOOLEAN',  'key': 'supportDocumentWrite', 'value': 'false'},
        ],
        'firingTriggerId': [trigger_id],
        'tagFiringOption': 'oncePerLoad',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run',  action='store_true')
    parser.add_argument('--limit',    type=int, default=0, help='Process at most N locations')
    parser.add_argument('--reset',    action='store_true', help='Clear results file before running')
    args = parser.parse_args()

    # Load resume state
    results: dict[str, dict] = {}
    if RESULTS_FILE.exists() and not args.reset:
        results = json.loads(RESULTS_FILE.read_text())
        print(f'Resuming — {len(results)} already processed')
    elif RESULTS_FILE.exists() and args.reset:
        RESULTS_FILE.unlink()
        print('Results file cleared.')

    print('Fetching eligible locations from Supabase...')
    locations = fetch_eligible_locations()
    print(f'  {len(locations)} locations eligible')

    if args.limit:
        locations = locations[:args.limit]
        print(f'  Limiting to {args.limit}')

    # Group by token so we auth once per account group
    by_token: dict[str, list[dict]] = {}
    for loc in locations:
        acct_email = (loc.get('gtm_lnm_acct') or '').lower().strip()
        token_file = GTM_TOKEN_MAP.get(acct_email, GTM_TOKEN_DEFAULT)
        key = str(token_file)
        by_token.setdefault(key, []).append(loc)

    done = skipped = failed = 0

    for token_path_str, locs in by_token.items():
        token_path = Path(token_path_str)
        if not token_path.exists():
            print(f'\n[warn] Token file missing: {token_path} — skipping {len(locs)} locations')
            for loc in locs:
                results[loc['id']] = {'status': 'error', 'error': f'token missing: {token_path}', 'name': loc['name']}
            failed += len(locs)
            continue

        print(f'\n── Token: {token_path.name} ({len(locs)} locations) ──────────────')
        service = get_gtm_service(token_path)

        for i, loc in enumerate(locs, 1):
            loc_id   = loc['id']
            name     = loc['name']
            gtm_id   = loc['gtm_id']
            acct_id  = loc['gtm_account_id']
            ctr_id   = loc['gtm_container_id']
            cr_acct  = loc['callrail_account_id']
            cr_comp  = loc['callrail_company_id']

            # Already done?
            prev = results.get(loc_id, {})
            if prev.get('status') in ('done', 'existed'):
                skipped += 1
                continue

            print(f'\n[{i}/{len(locs)}] {name} ({gtm_id})')

            if args.dry_run:
                print(f'  [DRY RUN] would add CallRail DNI to {gtm_id}')
                results[loc_id] = {'status': 'dry_run', 'name': name, 'gtm_id': gtm_id}
                done += 1
                continue

            try:
                # 1. Get CallRail swap.js URL
                print(f'  Fetching CallRail script URL...')
                script_url = fetch_callrail_script_url(cr_acct, cr_comp)
                if not script_url:
                    raise ValueError('Could not parse swap.js URL from CallRail API')
                print(f'  swap.js: {script_url}')

                # 2. GTM workspace
                ws_id = get_workspace(service, acct_id, ctr_id)

                # 3. Check existing tags
                existing_tags = list_tags(service, acct_id, ctr_id, ws_id)
                if DNI_TAG_NAME in existing_tags:
                    print(f'  · tag already exists — skipping')
                    results[loc_id] = {'status': 'existed', 'name': name, 'gtm_id': gtm_id}
                    skipped += 1
                    RESULTS_FILE.write_text(json.dumps(results, indent=2))
                    continue

                # 4. Ensure All Pages trigger
                existing_triggers = list_triggers(service, acct_id, ctr_id, ws_id)
                ap_tid = get_all_pages_trigger_id(existing_triggers, service, acct_id, ctr_id, ws_id)

                # 5. Add variable
                existing_vars = list_variables(service, acct_id, ctr_id, ws_id)
                _, var_st = ensure_variable(service, acct_id, ctr_id, ws_id,
                                            callrail_variable_body(cr_comp), existing_vars)
                print(f'  {"✓" if var_st == "new" else "·"} Variable: {CR_VAR_NAME} ({var_st})')

                # 6. Add DNI tag
                _, tag_st = ensure_tag(service, acct_id, ctr_id, ws_id,
                                       callrail_dni_tag_body(script_url, ap_tid), existing_tags)
                print(f'  ✓ Tag: {DNI_TAG_NAME} ({tag_st})')

                # 7. Publish if anything new was created
                if var_st == 'new' or tag_st == 'new':
                    try:
                        ver = create_and_publish_version(service, acct_id, ctr_id, ws_id, f'LNM - CallRail DNI - {name}')
                        print(f'  ✓ Published version {ver}')
                    except Exception as pub_e:
                        print(f'  [warn] publish failed: {pub_e}')

                results[loc_id] = {'status': 'done', 'name': name, 'gtm_id': gtm_id, 'script_url': script_url}
                done += 1

            except Exception as e:
                print(f'  [error] {e}')
                results[loc_id] = {'status': 'error', 'name': name, 'gtm_id': gtm_id, 'error': str(e)}
                failed += 1

            # Persist after every location
            RESULTS_FILE.write_text(json.dumps(results, indent=2))
            time.sleep(0.3)

    print(f'\n══ Done ══')
    print(f'  Added/confirmed : {done}')
    print(f'  Already existed : {skipped}')
    print(f'  Errors          : {failed}')
    print(f'  Results file    : {RESULTS_FILE}')


if __name__ == '__main__':
    main()
