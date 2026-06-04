"""
fix_compiler_errors.py — Diagnose and fix GTM compiler errors.

For each compiler-error container:
1. List all workspace tags
2. Find tags with missing/invalid required params
3. Delete invalid tags (or revert them) so publish succeeds
4. Re-publish

Usage:
  python fix_compiler_errors.py              # live fix
  python fix_compiler_errors.py --dry-run    # diagnose only
"""

import argparse
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
    'GTM-TLWKBMQ3',
    'GTM-5R78LZ6N',
    'GTM-NHDV7XL8',
    'GTM-P433K3X3',
    'GTM-T9NLZ68R',
    'GTM-PCKSRZXZ',
    'GTM-KFR8WQ7P',
    'GTM-TB3WDMNN',
    'GTM-MMJ89CL6',
    'GTM-WJNVLL2B',
]


# ── Supabase ──────────────────────────────────────────────────────────────────

def fetch_locations_for_gtm_ids(gtm_ids: list[str]) -> list[dict]:
    ids_param = '(' + ','.join(gtm_ids) + ')'
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={
            'select': 'id,name,gads_cid,gtm_id,gtm_account_id,gtm_container_id,gtm_lnm_acct',
            'gtm_id': f'in.{ids_param}',
            'deleted_at': 'is.null',
            'gtm_account_id': 'not.is.null',
        },
        headers=SB_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def fetch_conversion_id_map() -> dict:
    mapping, offset = {}, 0
    while True:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/gads_conversions',
            params={'select': 'location_id,conversion_id', 'conversion_id': 'not.is.null',
                    'offset': offset, 'limit': 1000},
            headers=SB_HEADERS, timeout=15,
        )
        r.raise_for_status()
        batch = r.json()
        for row in batch:
            loc_id = row.get('location_id')
            conv_id = row.get('conversion_id')
            if loc_id and conv_id and loc_id not in mapping:
                mapping[loc_id] = str(conv_id)
        if len(batch) < 1000:
            break
        offset += 1000
    return mapping


# ── GTM Auth ──────────────────────────────────────────────────────────────────

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
        with open(token_file, 'w') as f:
            json.dump(data, f, indent=2)
    svc = build('tagmanager', 'v2', credentials=creds)
    _service_cache[token_file] = svc
    return svc


# ── GTM helpers ───────────────────────────────────────────────────────────────

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


def get_workspace(service, acct, ctr) -> str:
    ws = _call(lambda: service.accounts().containers().workspaces().list(
        parent=f'accounts/{acct}/containers/{ctr}'
    ).execute()).get('workspace', [])
    if not ws:
        raise RuntimeError('No workspace found')
    return ws[0]['workspaceId']


def list_workspace_tags(service, acct, ctr, ws) -> list[dict]:
    resp = _call(lambda: service.accounts().containers().workspaces().tags().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())
    return resp.get('tag', [])


def get_workspace_status(service, acct, ctr, ws) -> dict:
    return _call(lambda: service.accounts().containers().workspaces().getStatus(
        path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())


def delete_tag(service, acct, ctr, ws, tag_id: str):
    path = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}/tags/{tag_id}'
    _call(lambda: service.accounts().containers().workspaces().tags().delete(path=path).execute())


def revert_tag(service, acct, ctr, ws, tag_id: str):
    path = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}/tags/{tag_id}'
    _call(lambda: service.accounts().containers().workspaces().tags().revert(path=path).execute())


def patch_tag(service, acct, ctr, ws, tag: dict):
    path = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}/tags/{tag["tagId"]}'
    _call(lambda: service.accounts().containers().workspaces().tags().update(
        path=path, body=tag
    ).execute())


def try_create_version(service, acct, ctr, ws, note: str) -> dict:
    """Returns full create_version response including compilerError details."""
    return _call(lambda: service.accounts().containers().workspaces().create_version(
        path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}',
        body={'name': f'LNM AW CID Fix - {time.strftime("%Y-%m-%d %H:%M")}', 'notes': note},
    ).execute())


def publish_version(service, vpath: str):
    _call(lambda: service.accounts().containers().versions().publish(path=vpath).execute())


# ── Tag validation ────────────────────────────────────────────────────────────

REQUIRED_PARAMS = {
    'googtag': {'tagId'},
    'awct': {'conversionId', 'conversionLabel'},
}

def tag_issues(tag: dict) -> list[str]:
    """Returns list of issue descriptions for a tag."""
    issues = []
    tag_type = tag.get('type', '')
    params = {p['key']: p for p in tag.get('parameter', [])}

    required = REQUIRED_PARAMS.get(tag_type, set())
    for key in required:
        if key not in params:
            issues.append(f'missing required param: {key}')
        elif not params[key].get('value', '').strip():
            issues.append(f'empty required param: {key}')

    if tag_type == 'googtag':
        tag_id_val = params.get('tagId', {}).get('value', '')
        if tag_id_val and not tag_id_val.startswith('AW-') and not tag_id_val.startswith('G-'):
            issues.append(f'tagId malformed: {tag_id_val!r}')

    if tag_type == 'awct':
        conv_id = params.get('conversionId', {}).get('value', '')
        if conv_id and not conv_id.isdigit():
            issues.append(f'conversionId not numeric: {conv_id!r}')

    # Pausing status issue — paused tags with no firing triggers can fail compile
    if not tag.get('firingTriggerId') and not tag.get('firingRuleId'):
        if tag.get('paused') is not True:
            issues.append('no firing trigger and not paused')

    return issues


# ── Main ──────────────────────────────────────────────────────────────────────

def process_container(service, acct, ctr, correct_cid: str, dry_run: bool, loc_name: str):
    ws = get_workspace(service, acct, ctr)
    tags = list_workspace_tags(service, acct, ctr, ws)

    print(f'  Workspace {ws}: {len(tags)} tags')

    # Show workspace status (what's been modified)
    try:
        status = get_workspace_status(service, acct, ctr, ws)
        changes = status.get('workspaceChange', [])
        if changes:
            print(f'  {len(changes)} workspace change(s):')
            for c in changes[:5]:
                entity = c.get('tag') or c.get('trigger') or c.get('variable') or {}
                etype = 'tag' if 'tag' in c else 'trigger' if 'trigger' in c else 'variable'
                print(f'    [{c.get("changeStatus","?")}] {etype}: {entity.get("name","?")}')
    except Exception as e:
        print(f'  [status error] {e}')

    # Check all tags for issues
    problematic = []
    for tag in tags:
        issues = tag_issues(tag)
        if issues:
            print(f'  [ISSUE] {tag["name"]} ({tag.get("type","?")}): {"; ".join(issues)}')
            problematic.append((tag, issues))
        elif tag.get('type') in ('googtag', 'awct'):
            params = {p['key']: p['value'] for p in tag.get('parameter', [])}
            cid_val = params.get('tagId', params.get('conversionId', '?'))
            print(f'  [ok] {tag["name"]} ({tag.get("type","?")}): {cid_val}')

    # Attempt create_version to capture compiler error details
    print(f'  Attempting create_version to inspect error…')
    try:
        ver = try_create_version(service, acct, ctr, ws, f'Diagnose: {loc_name}')
        if ver.get('compilerError'):
            comp_status = ver.get('workspaceStatus', {})
            print(f'  [compiler error] compileStatus: {json.dumps(comp_status, indent=2)[:500]}')
            # Check for compilation issues in the response
            for key in ('compilerError', 'newWorkspaceStatus', 'syncStatus'):
                if key in ver:
                    print(f'  [{key}]: {json.dumps(ver[key])[:300]}')
        else:
            # Published successfully
            vid = ver.get('containerVersion', {}).get('containerVersionId', '?')
            vpath = ver.get('containerVersion', {}).get('path', '')
            if not dry_run and vpath:
                publish_version(service, vpath)
                print(f'  ✓ Fixed and published → version {vid}')
            else:
                print(f'  ✓ Would publish version {vid} (dry-run)')
            return True
    except Exception as e:
        print(f'  [create_version error] {e}')

    if dry_run:
        return False

    # Strategy: revert workspace-modified tags that have issues, then retry
    if problematic:
        print(f'  Reverting {len(problematic)} problematic tag(s)…')
        for tag, issues in problematic:
            try:
                revert_tag(service, acct, ctr, ws, tag['tagId'])
                print(f'    reverted: {tag["name"]}')
            except Exception as e:
                print(f'    revert failed for {tag["name"]}: {e}')
                try:
                    delete_tag(service, acct, ctr, ws, tag['tagId'])
                    print(f'    deleted: {tag["name"]}')
                except Exception as e2:
                    print(f'    delete also failed: {e2}')

        # Retry publish after revert
        try:
            ver2 = try_create_version(service, acct, ctr, ws, f'Fix after revert: {loc_name}')
            if not ver2.get('compilerError'):
                vid = ver2.get('containerVersion', {}).get('containerVersionId', '?')
                vpath = ver2.get('containerVersion', {}).get('path', '')
                publish_version(service, vpath)
                print(f'  ✓ Fixed after revert → version {vid}')
                return True
            else:
                print(f'  [still failing after revert]')
        except Exception as e:
            print(f'  [retry error] {e}')

    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print('Fetching locations…')
    locs = fetch_locations_for_gtm_ids(ERROR_GTM_IDS)
    conv_id_map = fetch_conversion_id_map()

    # Deduplicate by container
    seen = {}
    for loc in locs:
        acct = loc.get('gtm_account_id', '')
        ctr  = loc.get('gtm_container_id', '')
        if not acct or not ctr:
            continue
        key = (str(acct), str(ctr))
        if key not in seen:
            cid = conv_id_map.get(loc['id']) or str(loc['gads_cid']).replace('-', '')
            seen[key] = {**loc, '_cid': cid}

    print(f'{len(seen)} unique container(s)\n')

    fixed = failed = 0
    for loc in seen.values():
        gtm_id = loc.get('gtm_id', '?')
        name   = loc.get('name', '?')
        acct   = str(loc['gtm_account_id'])
        ctr    = str(loc['gtm_container_id'])
        cid    = loc['_cid']
        lnm_acct   = loc.get('gtm_lnm_acct') or ''
        token_file = TOKEN_MAP.get(lnm_acct, DEFAULT_TOKEN)

        print(f'{gtm_id}  {name}  (CID {cid})')
        try:
            svc = get_gtm_service(token_file)
            ok = process_container(svc, acct, ctr, cid, args.dry_run, name)
            if ok:
                fixed += 1
            else:
                failed += 1
        except Exception as e:
            print(f'  [fatal] {e}')
            failed += 1
        print()
        time.sleep(1)

    print(f'=== Done ===')
    print(f'  Fixed: {fixed}  |  Failed: {failed}')


if __name__ == '__main__':
    main()
