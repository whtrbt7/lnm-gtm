"""
fix_merge_conflicts.py — Resolve workspace merge conflicts then publish.

When a live container is published while a workspace has pending changes,
create_version returns {syncStatus: {mergeConflict: true}} with no containerVersion.
Resolution: keep the workspace version of each conflicted entity, then publish.
"""
import json, os, requests, time
from dotenv import load_dotenv
load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_MAP = {
    'analytics@leadsnearme.com':  os.path.join(SCRIPT_DIR, 'token_analytics.json'),
    'analytics2@leadsnearme.com': os.path.join(SCRIPT_DIR, 'token_analytics2.json'),
    'reports@leadsnearme.com':    os.path.join(SCRIPT_DIR, 'token_reports.json'),
}
DEFAULT_TOKEN = os.path.join(SCRIPT_DIR, 'token_developer.json')
SB_URL = os.environ.get('SUPABASE_URL', 'https://supabase.alexanderchiu.com')
SB_KEY = os.environ['SUPABASE_SERVICE_KEY']
SB_H   = {'apikey': SB_KEY, 'Authorization': f'Bearer {SB_KEY}'}


def get_svc(token_file):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    with open(token_file) as f:
        data = json.load(f)
    creds = Credentials(token=data.get('token'), refresh_token=data.get('refresh_token'),
        token_uri=data.get('token_uri', 'https://oauth2.googleapis.com/token'),
        client_id=data.get('client_id'), client_secret=data.get('client_secret'),
        scopes=data.get('scopes'))
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        data['token'] = creds.token
        with open(token_file, 'w') as f:
            json.dump(data, f, indent=2)
    return build('tagmanager', 'v2', credentials=creds)


def _call(fn, max_retries=8, base_delay=3.0):
    from googleapiclient.errors import HttpError
    delay = base_delay
    for attempt in range(max_retries):
        try:
            return fn()
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < max_retries - 1:
                print(f'  [retry] {e.resp.status}, {delay:.0f}s')
                time.sleep(delay)
                delay = min(delay * 2, 120)
            else:
                raise


def get_loc(gtm_id):
    r = requests.get(f'{SB_URL}/rest/v1/locations',
        params={'select': 'id,gtm_account_id,gtm_container_id,gtm_lnm_acct,name',
                'gtm_id': f'eq.{gtm_id}', 'deleted_at': 'is.null',
                'gtm_account_id': 'not.is.null', 'limit': '1'},
        headers=SB_H, timeout=15)
    return r.json()[0]


def get_conv_id(loc_id, gads_cid):
    r = requests.get(f'{SB_URL}/rest/v1/gads_conversions',
        params={'select': 'conversion_id', 'location_id': f'eq.{loc_id}',
                'conversion_id': 'not.is.null', 'limit': '1'},
        headers=SB_H, timeout=15)
    rows = r.json()
    if rows:
        return str(rows[0]['conversion_id'])
    return str(gads_cid).replace('-', '')


def resolve_and_publish(svc, acct, ctr, ws, note):
    """Resolve all merge conflicts (keep workspace version), then create+publish."""
    status = _call(lambda: svc.accounts().containers().workspaces().getStatus(
        path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}').execute())

    conflicts = status.get('mergeConflict', [])
    print(f'  {len(conflicts)} merge conflict(s)')

    for conflict in conflicts:
        entity_in_ws = conflict.get('entityInWorkspace', {})
        # Determine entity type and change status
        for etype in ('tag', 'trigger', 'variable', 'folder'):
            if etype in entity_in_ws:
                entity_obj = entity_in_ws[etype]
                change_status = entity_in_ws.get('changeStatus', 'modified')
                name = entity_obj.get('name', '?')
                print(f'  resolving conflict: {etype} "{name}" (keep {change_status})')
                body = {'entity': {etype: entity_obj, 'changeStatus': change_status}}
                try:
                    _call(lambda: svc.accounts().containers().workspaces().resolve_conflict(
                        path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}',
                        body=body,
                    ).execute())
                    print(f'    ✓ resolved')
                except Exception as e:
                    print(f'    [resolve error] {e}')
                break
        time.sleep(0.3)

    # Now try create_version again
    ver = _call(lambda: svc.accounts().containers().workspaces().create_version(
        path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}',
        body={'name': 'LNM AW CID Fix', 'notes': note},
    ).execute())

    if ver.get('compilerError'):
        raise RuntimeError('GTM compiler error after conflict resolution')
    if 'syncStatus' in ver and not ver.get('containerVersion'):
        raise RuntimeError(f'Still sync conflict after resolution: {ver.get("syncStatus")}')

    vid   = ver['containerVersion']['containerVersionId']
    vpath = ver['containerVersion']['path']
    _call(lambda: svc.accounts().containers().versions().publish(path=vpath).execute())
    return vid


def fix_container_tags(svc, acct, ctr, ws, correct_cid):
    """Patch AW Config + awct tags to correct_cid."""
    tags = _call(lambda: svc.accounts().containers().workspaces().tags().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}').execute()).get('tag', [])

    patched = 0
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
            updated = {**tag, 'parameter': new_params}
            path = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}/tags/{tag["tagId"]}'
            _call(lambda: svc.accounts().containers().workspaces().tags().update(
                path=path, body=updated).execute())
            print(f'  patched: {tag["name"]}')
            patched += 1
            time.sleep(0.3)
    return patched


def main():
    targets = ['GTM-TVS9MXWS']

    for gtm_id in targets:
        print(f'\n{gtm_id}')
        loc = get_loc(gtm_id)
        acct = loc['gtm_account_id']
        ctr  = loc['gtm_container_id']
        tf   = TOKEN_MAP.get(loc.get('gtm_lnm_acct') or '', DEFAULT_TOKEN)
        correct_cid = get_conv_id(loc['id'], loc.get('gads_cid', ''))
        print(f'  acct={acct} ctr={ctr} cid={correct_cid}')

        try:
            svc = get_svc(tf)
            ws_list = _call(lambda: svc.accounts().containers().workspaces().list(
                parent=f'accounts/{acct}/containers/{ctr}').execute())
            ws = ws_list['workspace'][0]['workspaceId']

            # Patch tags first
            n = fix_container_tags(svc, acct, ctr, ws, correct_cid)
            print(f'  {n} tag(s) patched')

            # Resolve conflicts and publish
            vid = resolve_and_publish(svc, acct, ctr, ws, f'Fix AW CID + resolve conflicts')
            print(f'  ✓ published version {vid}')
        except Exception as e:
            print(f'  [error] {e}')

    print('\n=== Done ===')


if __name__ == '__main__':
    main()
