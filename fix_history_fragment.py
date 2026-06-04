"""
fix_history_fragment.py — Fix GTM compiler error caused by trigger referencing
{{History New URL Fragment}} which doesn't exist; replace with {{New History Fragment}}.

Affects 10 containers that have a pending HC - Text Fragment trigger added by setup_tags.py.
"""

import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://supabase.alexanderchiu.com')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
SB_HEADERS   = {
    'apikey':        SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
}
TOKEN_MAP = {
    'analytics@leadsnearme.com':  os.path.join(SCRIPT_DIR, 'token_analytics.json'),
    'analytics2@leadsnearme.com': os.path.join(SCRIPT_DIR, 'token_analytics2.json'),
    'reports@leadsnearme.com':    os.path.join(SCRIPT_DIR, 'token_reports.json'),
}
DEFAULT_TOKEN = os.path.join(SCRIPT_DIR, 'token_developer.json')

ERROR_GTM_IDS = [
    'GTM-TLWKBMQ3', 'GTM-5R78LZ6N', 'GTM-NHDV7XL8', 'GTM-P433K3X3',
    'GTM-T9NLZ68R',  'GTM-PCKSRZXZ', 'GTM-KFR8WQ7P', 'GTM-TB3WDMNN',
    'GTM-MMJ89CL6',  'GTM-WJNVLL2B',
]

OLD_VAR = '{{History New URL Fragment}}'
NEW_VAR = '{{New History Fragment}}'


# ── auth / helpers (same pattern as fix_aw_cid_tags.py) ──────────────────────

_service_cache: dict = {}

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
                delay = min(delay * 2, 120)
            else:
                raise


def _replace_in_params(params: list, old: str, new: str) -> tuple[list, int]:
    """Recursively replace variable references in a parameter list."""
    replaced = 0
    result = []
    for p in params:
        p = dict(p)
        if p.get('value') == old:
            p['value'] = new
            replaced += 1
        if 'list' in p:
            p['list'], n = _replace_in_params(p['list'], old, new)
            replaced += n
        if 'map' in p:
            p['map'], n = _replace_in_params(p['map'], old, new)
            replaced += n
        result.append(p)
    return result, replaced


def _fix_trigger(trig: dict) -> tuple[dict, int]:
    """Return updated trigger and number of replacements made."""
    total = 0
    trig = dict(trig)

    for field in ('filter', 'autoEventFilter', 'customEventFilter'):
        if field not in trig:
            continue
        new_conditions = []
        for cond in trig[field]:
            new_params, n = _replace_in_params(cond.get('parameter', []), OLD_VAR, NEW_VAR)
            new_conditions.append({**cond, 'parameter': new_params})
            total += n
        trig[field] = new_conditions

    return trig, total


def process_container(svc, acct: str, ctr: str, name: str) -> bool:
    ws_list = _call(lambda: svc.accounts().containers().workspaces().list(
        parent=f'accounts/{acct}/containers/{ctr}'
    ).execute())
    if not ws_list.get('workspace'):
        raise RuntimeError('No workspace found')
    ws = ws_list['workspace'][0]['workspaceId']

    trig_resp = _call(lambda: svc.accounts().containers().workspaces().triggers().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())
    triggers = trig_resp.get('trigger', [])

    patched = 0
    for trig in triggers:
        updated, n = _fix_trigger(trig)
        if n:
            tpath = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}/triggers/{trig["triggerId"]}'
            _call(lambda: svc.accounts().containers().workspaces().triggers().update(
                path=tpath, body=updated
            ).execute())
            print(f'    patched trigger "{trig["name"]}" ({n} replacement(s))')
            patched += 1
            time.sleep(0.3)

    if patched == 0:
        print(f'    no {{{{History New URL Fragment}}}} found in triggers')

    ver = _call(lambda: svc.accounts().containers().workspaces().create_version(
        path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}',
        body={'name': 'LNM AW CID Fix', 'notes': 'Fix {{History New URL Fragment}} → {{New History Fragment}}'},
    ).execute())

    if ver.get('compilerError'):
        print(f'    [still compiler error after trigger patch]')
        return False

    vid  = ver['containerVersion']['containerVersionId']
    vpath = ver['containerVersion']['path']
    _call(lambda: svc.accounts().containers().versions().publish(path=vpath).execute())
    print(f'    ✓ published version {vid}')
    return True


def main():
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={
            'select': 'gtm_id,gtm_account_id,gtm_container_id,gtm_lnm_acct,name',
            'gtm_id': f'in.({",".join(ERROR_GTM_IDS)})',
            'deleted_at': 'is.null',
            'gtm_account_id': 'not.is.null',
        },
        headers=SB_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    locs = r.json()

    seen: dict[tuple, dict] = {}
    for loc in locs:
        key = (loc['gtm_account_id'], loc['gtm_container_id'])
        if key not in seen:
            seen[key] = loc

    print(f'{len(seen)} unique container(s)\n')

    fixed = failed = 0
    for (acct, ctr), loc in seen.items():
        gtm_id = loc['gtm_id']
        name   = loc['name']
        lnm    = loc.get('gtm_lnm_acct') or ''
        tf     = TOKEN_MAP.get(lnm, DEFAULT_TOKEN)
        print(f'{gtm_id}  {name}')
        try:
            svc = get_gtm_service(tf)
            ok  = process_container(svc, acct, ctr, name)
            if ok:
                fixed += 1
            else:
                failed += 1
        except Exception as e:
            print(f'    [error] {e}')
            failed += 1
        time.sleep(0.8)

    print(f'\n=== Done ===')
    print(f'  Fixed: {fixed}  |  Failed: {failed}')


if __name__ == '__main__':
    main()
