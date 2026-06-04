"""
fix_aw_cid_tags.py — Bulk-fix AW Config tagId and awct conversionId in every
GTM container to match the correct gads_cid from Supabase.

Usage:
  python fix_aw_cid_tags.py              # live run
  python fix_aw_cid_tags.py --dry-run   # preview only
  python fix_aw_cid_tags.py --limit 10  # only first 10 containers
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


# ── Supabase ──────────────────────────────────────────────────────────────────

def fetch_conversion_id_map() -> dict:
    """Returns {location_id: conversion_id} from gads_conversions.
    This is the real GAds Conversion ID (e.g. 10838160041) used in GTM awct tags,
    distinct from the Customer ID stored in locations.gads_cid.
    """
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


def fetch_locations() -> list[dict]:
    results, offset = [], 0
    while True:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/locations',
            params={
                'select': 'id,name,gads_cid,gtm_id,gtm_account_id,gtm_container_id,gtm_lnm_acct',
                'deleted_at': 'is.null',
                'gads_cid': 'not.is.null',
                'gtm_id': 'not.is.null',
                'offset': offset,
                'limit': 1000,
            },
            headers=SB_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        batch = r.json()
        results.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000
    return results


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


def patch_tag(service, acct, ctr, ws, tag: dict):
    path = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}/tags/{tag["tagId"]}'
    _call(lambda: service.accounts().containers().workspaces().tags().update(
        path=path, body=tag
    ).execute())


def publish_version(service, acct, ctr, ws, note: str) -> str:
    ver = _call(lambda: service.accounts().containers().workspaces().create_version(
        path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}',
        body={'name': f'LNM AW CID Fix - {time.strftime("%Y-%m-%d %H:%M")}', 'notes': note},
    ).execute())
    if ver.get('compilerError'):
        raise RuntimeError('GTM compiler error')
    vid = ver['containerVersion']['containerVersionId']
    vpath = ver['containerVersion']['path']
    _call(lambda: service.accounts().containers().versions().publish(path=vpath).execute())
    return vid


# ── Tag patching logic ────────────────────────────────────────────────────────

def get_live_aw_cid(service, acct, ctr):
    """Return the current live version's AW Config CID, or None if not found."""
    try:
        live = _call(lambda: service.accounts().containers().versions().live(
            parent=f'accounts/{acct}/containers/{ctr}'
        ).execute())
        for tag in live.get('tag', []):
            if tag.get('type') == 'googtag':
                for p in tag.get('parameter', []):
                    if p['key'] == 'tagId' and p['value'].startswith('AW-'):
                        return p['value'].replace('AW-', '')
    except Exception:
        pass
    return None


def fix_tags_for_container(service, acct, ctr, correct_cid: str, dry_run: bool) -> dict:
    """Returns {'patched': N, 'published': bool, 'already_correct': bool}"""
    ws = get_workspace(service, acct, ctr)
    tags = list_workspace_tags(service, acct, ctr, ws)

    tags_to_patch = []

    for tag in tags:
        tag_type = tag.get('type')
        changed = False
        new_params = []

        for p in tag.get('parameter', []):
            if tag_type == 'googtag' and p['key'] == 'tagId':
                if p['value'].startswith('AW-') and p['value'] != f'AW-{correct_cid}':
                    new_params.append({**p, 'value': f'AW-{correct_cid}'})
                    changed = True
                    continue
            elif tag_type == 'awct' and p['key'] == 'conversionId':
                if str(p['value']) != str(correct_cid):
                    new_params.append({**p, 'type': 'template', 'value': str(correct_cid)})
                    changed = True
                    continue
            new_params.append(p)

        if changed:
            tags_to_patch.append({**tag, 'parameter': new_params})

    # Check live version — if already correct AND workspace is clean, skip entirely
    live_cid = get_live_aw_cid(service, acct, ctr)
    if not tags_to_patch and live_cid == correct_cid:
        return {'patched': 0, 'published': False, 'already_correct': True}

    if dry_run:
        if tags_to_patch:
            for t in tags_to_patch:
                cid_param = next((p for p in t['parameter'] if p['key'] in ('tagId', 'conversionId')), None)
                print(f'    [dry-run] Would patch: {t["name"]} → {cid_param["value"] if cid_param else "?"}')
        else:
            print(f'    [dry-run] Workspace correct but live={live_cid} → would publish')
        return {'patched': len(tags_to_patch), 'published': False, 'already_correct': False}

    for t in tags_to_patch:
        patch_tag(service, acct, ctr, ws, t)
        time.sleep(0.3)

    vid = publish_version(
        service, acct, ctr, ws,
        f'Corrected AW Config + conversion tags to CID {correct_cid}'
    )
    return {'patched': len(tags_to_patch), 'vid': vid, 'published': True, 'already_correct': False}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--cid-file', help='CSV file with CIDs in first column (header row skipped)')
    args = parser.parse_args()

    allowed_cids: set[str] | None = None
    if args.cid_file:
        import csv
        with open(args.cid_file) as f:
            rows = list(csv.reader(f))
        allowed_cids = {str(r[0]).replace('-', '').strip() for r in rows[1:] if r and r[0].strip()}
        print(f'CID filter: {len(allowed_cids)} account(s) from {args.cid_file}')

    print('Fetching locations from Supabase…')
    locs = fetch_locations()
    if allowed_cids:
        locs = [l for l in locs if str(l.get('gads_cid', '')).replace('-', '') in allowed_cids]
    print(f'  {len(locs)} location(s) with gads_cid + gtm_id')

    print('Fetching correct Conversion IDs from gads_conversions…')
    conv_id_map = fetch_conversion_id_map()
    print(f'  {len(conv_id_map)} location(s) with Conversion ID in gads_conversions\n')

    # Deduplicate by (gtm_account_id, gtm_container_id), resolve correct CID
    # If multiple locations share a container, verify consistent CID
    seen: dict[tuple, dict] = {}
    conflicts: list[str] = []

    for loc in locs:
        acct = loc.get('gtm_account_id', '')
        ctr  = loc.get('gtm_container_id', '')
        if not acct or not ctr or '@' in str(acct):
            continue  # skip email-style or missing account IDs
        key = (str(acct), str(ctr))
        # Use real Conversion ID from gads_conversions; fall back to gads_cid stripped
        cid = conv_id_map.get(loc['id']) or str(loc['gads_cid']).replace('-', '')

        if key not in seen:
            seen[key] = {**loc, '_cid': cid}
        elif seen[key]['_cid'] != cid:
            conflicts.append(f'{loc["gtm_id"]}: {seen[key]["_cid"]} vs {cid}')

    containers = list(seen.values())
    print(f'  {len(containers)} unique container(s) to process')
    if conflicts:
        print(f'  {len(conflicts)} CID conflict(s) (shared containers with different CIDs — skipped):')
        for c in conflicts[:5]:
            print(f'    {c}')
        # Remove conflicted containers — use same cid formula as dedup loop
        conflict_keys = set()
        for loc in locs:
            acct = loc.get('gtm_account_id', '')
            ctr  = loc.get('gtm_container_id', '')
            if not acct or not ctr or '@' in str(acct):
                continue
            key = (str(acct), str(ctr))
            cid = conv_id_map.get(loc['id']) or str(loc['gads_cid']).replace('-', '')
            if seen.get(key, {}).get('_cid') != cid:
                conflict_keys.add(key)
        containers = [c for c in containers if (str(c['gtm_account_id']), str(c['gtm_container_id'])) not in conflict_keys]
        print(f'  {len(containers)} container(s) after removing conflicts\n')

    if args.limit:
        containers = containers[:args.limit]
        print(f'  Limited to first {args.limit}\n')

    fixed = skipped = already_correct = 0
    errors = []

    for i, loc in enumerate(containers, 1):
        gtm_id   = loc.get('gtm_id', '?')
        name     = loc.get('name', '?')
        acct     = str(loc['gtm_account_id'])
        ctr      = str(loc['gtm_container_id'])
        cid        = loc['_cid']
        lnm_acct   = loc.get('gtm_lnm_acct') or ''
        token_file = TOKEN_MAP.get(lnm_acct, DEFAULT_TOKEN)

        print(f'[{i}/{len(containers)}] {gtm_id}  {name}  →  CID {cid}')

        try:
            service = get_gtm_service(token_file)
            result  = fix_tags_for_container(service, acct, ctr, cid, args.dry_run)

            if result.get('already_correct'):
                print(f'  ✓ Already correct (live + workspace)')
                already_correct += 1
            else:
                vid_info = f'  →  version {result.get("vid","?")}' if not args.dry_run else ''
                patch_info = f'{result["patched"]} tag(s) patched + ' if result['patched'] else 'workspace correct → '
                print(f'  ✓ {patch_info}published{vid_info}')
                fixed += 1

        except Exception as e:
            print(f'  [error] {e}')
            errors.append(f'{gtm_id}: {e}')
            skipped += 1

        time.sleep(0.5)

    print(f'\n=== Done ===')
    print(f'  Fixed: {fixed}  |  Already correct: {already_correct}  |  Errors: {skipped}')
    if errors:
        print(f'\nErrors:')
        for e in errors[:20]:
            print(f'  {e}')


if __name__ == '__main__':
    main()
