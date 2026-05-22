"""
Audit GTM container health: unpublished workspace changes and tags blocking publish.

Usage:
  python audit_gtm_health.py --gtm-id GTM-XXXXXXXX
  python audit_gtm_health.py --gtm-id GTM-XXXXXXXX --token-file token_analytics.json
  python audit_gtm_health.py --gtm-id GTM-XXXXXXXX --location-id UUID   # writes to DB
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CACHE_FILE  = SCRIPT_DIR / 'gtm_id_cache.json'
TOKEN_FILE  = SCRIPT_DIR / 'token_analytics.json'

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')


def _build_service(token_file: str):
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
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            data['token'] = creds.token
            data['expiry'] = creds.expiry.isoformat() if creds.expiry else None
            with open(token_file, 'w') as f:
                json.dump(data, f, indent=2)
        else:
            raise RuntimeError('Token invalid — re-run get_analytics_token.py')
    return build('tagmanager', 'v2', credentials=creds, cache_discovery=False)


def _resolve_container(gtm_id: str) -> tuple[str, str] | None:
    """Return (account_id, container_id) from cache for a GTM public ID."""
    gtm_id = gtm_id.upper()
    if not CACHE_FILE.exists():
        return None
    cache = json.loads(CACHE_FILE.read_text())
    entry = cache.get(gtm_id)
    if entry:
        return entry['account_id'], entry['container_id']
    return None


def audit_container(service, account_id: str, container_id: str) -> dict:
    """
    Check all workspaces for unpublished changes and merge conflicts.
    Returns {workspaces: [{id, name, has_changes, merge_conflicts, change_count}], issues: [str]}
    """
    parent = f'accounts/{account_id}/containers/{container_id}'
    issues = []
    workspace_results = []

    try:
        ws_resp = service.accounts().containers().workspaces().list(parent=parent).execute()
        workspaces = ws_resp.get('workspace', [])
    except Exception as e:
        return {'workspaces': [], 'issues': [f'Could not list workspaces: {e}']}

    for ws in workspaces:
        ws_id   = ws.get('workspaceId', '')
        ws_name = ws.get('name', ws_id)
        ws_path = ws.get('path', f'{parent}/workspaces/{ws_id}')

        try:
            status = service.accounts().containers().workspaces().getStatus(path=ws_path).execute()
        except Exception as e:
            workspace_results.append({'id': ws_id, 'name': ws_name, 'error': str(e)})
            issues.append(f'Workspace "{ws_name}": could not get status — {e}')
            continue

        changes       = status.get('workspaceChange', [])
        conflicts     = status.get('mergeConflict', [])
        change_count  = len(changes)
        has_conflicts = bool(conflicts)

        entry = {
            'id':              ws_id,
            'name':            ws_name,
            'change_count':    change_count,
            'has_changes':     change_count > 0,
            'merge_conflicts': has_conflicts,
        }

        if has_conflicts:
            conflict_tags = [c.get('entityInWorkspace', {}).get('tag', {}).get('name', '?')
                             for c in conflicts]
            entry['conflict_tags'] = conflict_tags
            issues.append(f'Workspace "{ws_name}": {len(conflicts)} merge conflict(s) blocking publish — tags: {", ".join(conflict_tags)}')
        elif change_count > 0:
            issues.append(f'Workspace "{ws_name}": {change_count} unpublished change(s)')

        workspace_results.append(entry)

    return {'workspaces': workspace_results, 'issues': issues}


def _write_db(location_id: str, output: str) -> None:
    if not SUPABASE_KEY:
        return
    try:
        from supabase import create_client
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        sb.table('locations').update({
            'automation_status': 'done',
            'automation_output': output,
        }).eq('id', location_id).execute()
    except Exception as e:
        print(f'[db] write failed: {e}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--gtm-id',      required=True, help='GTM public ID, e.g. GTM-ABCD1234')
    parser.add_argument('--location-id', default=None,  help='Supabase location UUID (writes result to DB)')
    parser.add_argument('--token-file',  default=str(TOKEN_FILE), help='Path to OAuth token JSON')
    args = parser.parse_args()

    resolved = _resolve_container(args.gtm_id)
    if not resolved:
        print(f'[error] {args.gtm_id} not found in gtm_id_cache.json — run build_gtm_cache.py first')
        sys.exit(1)

    account_id, container_id = resolved
    print(f'Container: {args.gtm_id} (account={account_id}, container={container_id})')

    try:
        service = _build_service(args.token_file)
    except Exception as e:
        print(f'[error] Auth failed: {e}')
        sys.exit(1)

    result = audit_container(service, account_id, container_id)
    lines  = []

    if not result['workspaces']:
        lines.append('No workspaces found.')
    else:
        for ws in result['workspaces']:
            if ws.get('error'):
                lines.append(f'  ⚠ Workspace {ws["name"]}: {ws["error"]}')
            elif ws['merge_conflicts']:
                tags = ', '.join(ws.get('conflict_tags', []))
                lines.append(f'  ✗ Workspace "{ws["name"]}": merge conflicts (blocking publish) — {tags}')
            elif ws['has_changes']:
                lines.append(f'  ⚠ Workspace "{ws["name"]}": {ws["change_count"]} unpublished change(s)')
            else:
                lines.append(f'  ✓ Workspace "{ws["name"]}": clean')

    if result['issues']:
        lines.append('\nIssues:')
        for iss in result['issues']:
            lines.append(f'  • {iss}')
    else:
        lines.append('\n✓ No issues found.')

    output = '\n'.join(lines)
    print(output)

    if args.location_id:
        _write_db(args.location_id, output)


if __name__ == '__main__':
    main()
