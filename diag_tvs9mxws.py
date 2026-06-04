"""Diagnose GTM-TVS9MXWS containerVersion KeyError and fix GTM-NMTMVJB6 stale tag."""
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
        params={'select': 'gtm_account_id,gtm_container_id,gtm_lnm_acct,name',
                'gtm_id': f'eq.{gtm_id}', 'deleted_at': 'is.null',
                'gtm_account_id': 'not.is.null', 'limit': '1'},
        headers=SB_H, timeout=15)
    return r.json()[0]


# ── TVS9MXWS: diagnose containerVersion KeyError ─────────────────────────────
print('=== GTM-TVS9MXWS ===')
loc = get_loc('GTM-TVS9MXWS')
acct, ctr = loc['gtm_account_id'], loc['gtm_container_id']
tf = TOKEN_MAP.get(loc.get('gtm_lnm_acct') or '', DEFAULT_TOKEN)
svc = get_svc(tf)

ws_list = _call(lambda: svc.accounts().containers().workspaces().list(
    parent=f'accounts/{acct}/containers/{ctr}').execute())
ws = ws_list['workspace'][0]['workspaceId']
print(f'workspace: {ws}')

# Check workspace status for sync issues
status = _call(lambda: svc.accounts().containers().workspaces().getStatus(
    path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}').execute())
changes = status.get('workspaceChange', [])
conflicts = status.get('mergeConflict', [])
print(f'changes: {len(changes)}, conflicts: {len(conflicts)}')
for c in conflicts[:3]:
    print(f'  conflict: {json.dumps(c)[:200]}')

# Try create_version and show full response keys
ver = _call(lambda: svc.accounts().containers().workspaces().create_version(
    path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}',
    body={'name': 'LNM AW CID Fix', 'notes': 'diag'},
).execute())
print(f'create_version keys: {list(ver.keys())}')
print(f'compilerError: {ver.get("compilerError")}')
if 'syncStatus' in ver:
    print(f'syncStatus: {json.dumps(ver["syncStatus"])[:300]}')
if 'containerVersion' in ver:
    vid  = ver['containerVersion']['containerVersionId']
    vpath = ver['containerVersion']['path']
    print(f'containerVersionId: {vid} — publishing…')
    _call(lambda: svc.accounts().containers().versions().publish(path=vpath).execute())
    print(f'✓ published version {vid}')
else:
    print('no containerVersion in response — workspace sync required')
    # Try syncing workspace
    try:
        sync_r = _call(lambda: svc.accounts().containers().workspaces().resolve_conflict(
            path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}',
            body={'changeStatus': 'applied'}
        ).execute())
        print(f'sync response: {json.dumps(sync_r)[:200]}')
    except Exception as e:
        print(f'resolve_conflict failed: {e}')

print()

# ── NMTMVJB6: fix stale tag by refreshing workspace listing ──────────────────
print('=== GTM-NMTMVJB6 ===')
loc2 = get_loc('GTM-NMTMVJB6')
acct2, ctr2 = loc2['gtm_account_id'], loc2['gtm_container_id']
tf2 = TOKEN_MAP.get(loc2.get('gtm_lnm_acct') or '', DEFAULT_TOKEN)
svc2 = get_svc(tf2)

ws_list2 = _call(lambda: svc2.accounts().containers().workspaces().list(
    parent=f'accounts/{acct2}/containers/{ctr2}').execute())
ws2 = ws_list2['workspace'][0]['workspaceId']
print(f'workspace: {ws2}')

# List current tags fresh
tags_resp = _call(lambda: svc2.accounts().containers().workspaces().tags().list(
    parent=f'accounts/{acct2}/containers/{ctr2}/workspaces/{ws2}').execute())
tags = tags_resp.get('tag', [])
print(f'tags in workspace: {len(tags)}')
for t in tags:
    params = {p["key"]: p.get("value","") for p in t.get("parameter",[])}
    if t.get("type") in ("googtag", "awct"):
        print(f'  [{t["tagId"]}] {t["name"]} ({t["type"]}): {params.get("tagId", params.get("conversionId", "?"))}')

# Check conv_id for this location
r_conv = requests.get(f'{SB_URL}/rest/v1/gads_conversions',
    params={'select': 'conversion_id', 'location_id': f'eq.{loc2.get("id", "")}',
            'conversion_id': 'not.is.null', 'limit': '1'},
    headers=SB_H, timeout=15)
print(f'gads_conversions lookup: {r_conv.text[:200]}')
