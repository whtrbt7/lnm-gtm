"""
setup_tags.py — Push LNM standard triggers + tags into a GTM container.

Reads all required values from Supabase (gtm_id, ga4_id, gads_conversion_id,
gads_dc_label, gads_phone_label, scheduler_type, phone_number). Uses a local
cache (gtm_id_cache.json) to skip the 400-account scan where possible.

Creates:
  Triggers (3): CE - {Scheduler} - Appointment Booked
                CL - Phone Click - {number}
                All Pages
  Tags     (5): GA4 - Configuration
                GA4 - Event - {appt_event}
                GA4 - Event - phone_click
                GAds - {store} - Booked_Appointment
                GAds - {store} - Phone_Click - {number}

Scheduler mapping:
  autoops    → ao-appointment-booked  / AutoOps
  shopgenie  → appointment_booked     / Shop Genie
  oktorocket → dc-service-booked      / OktoRocket  (default)

Usage:
  python setup_tags.py --gads-cid 6322162456
  python setup_tags.py --gads-cid 6322162456 --dry-run
  python setup_tags.py --gads-cid 6322162456 --force-recreate
"""

import re
import os
import json
import time
import argparse
import requests
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE   = os.path.join(SCRIPT_DIR, 'token_developer.json')  # overridden by --token-file
CACHE_FILE   = os.path.join(SCRIPT_DIR, 'gtm_id_cache.json')

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://supabase.alexanderchiu.com')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']

SUPABASE_HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
}

CALLRAIL_API_KEY = os.environ.get('CALLRAIL_API_KEY', '36497188d7030dbe692425202acf5a63')


# ── Supabase ──────────────────────────────────────────────────────────────────

def fetch_conversion_id_from_table(location_id):
    """Get correct Conversion ID from gads_conversions table.
    This is the account-level ID (e.g. 10838160041) used in GTM awct tags
    and the AW- base tag — distinct from the Customer ID (gads_cid).
    """
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/gads_conversions',
        params={'location_id': f'eq.{location_id}', 'select': 'conversion_id',
                'conversion_id': 'not.is.null', 'limit': 1},
        headers=SUPABASE_HEADERS, timeout=10,
    )
    r.raise_for_status()
    rows = r.json()
    if rows and rows[0].get('conversion_id'):
        return str(rows[0]['conversion_id'])
    return None


def fetch_location(gads_cid, location_id=None):
    select = 'id,name,url,gtm_id,gtm_account_id,gtm_container_id,ga4_measurement_id,ga4_id,gads_conversion_id,gads_appt_label,gads_dc_label,gads_phone_label,scheduler_type,phone_number,callrail_account_id,callrail_company_id,dashboard_type,brand_id'
    if location_id:
        params = {'id': f'eq.{location_id}', 'select': select}
    else:
        params = {'gads_cid': f'eq.{gads_cid}', 'select': select}
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/locations',
        params=params,
        headers=SUPABASE_HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise SystemExit(f'No location found for {"ID " + location_id if location_id else "GAds CID " + gads_cid}')
    if not location_id and len(rows) > 1:
        rows_with_gtm = [r for r in rows if r.get('gtm_id') or r.get('gtm_account_id')]
        if len(rows_with_gtm) == 1:
            print(f'  [warn] CID {gads_cid} matches {len(rows)} rows; using the one with GTM data: {rows_with_gtm[0].get("name")} ({rows_with_gtm[0]["id"]})')
            return rows_with_gtm[0]
        if len(rows_with_gtm) > 1:
            print(f'\nERROR: CID {gads_cid} matches {len(rows_with_gtm)} rows that each have GTM data. Specify --location-id:')
            for row in rows_with_gtm:
                print(f'  --location-id {row["id"]}  ({row.get("name", "?")}  gtm={row.get("gtm_id", "?")})')
            raise SystemExit('Ambiguous CID — rerun with --location-id')
        # No rows have GTM data — warn so user knows which row was picked
        print(f'  [warn] CID {gads_cid} matches {len(rows)} rows, none have GTM data. Picking first: {rows[0].get("name")} ({rows[0]["id"]})')
        print(f'  [warn] Use --location-id to target a specific row, or fill in GTM data on the correct row first.')
    return rows[0]


def fetch_brand_locations(brand_id, gads_cid=None):
    """Fetch all locations for a given brand to collect multiple phone numbers.
    Filters to only locations sharing the same gads_cid to avoid cross-client contamination."""
    if not brand_id:
        return []
    select = 'name,phone_number,gads_phone_label,gads_cid'
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={'brand_id': f'eq.{brand_id}', 'select': select},
        headers=SUPABASE_HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    locs = r.json()
    if gads_cid and any(str(loc.get('gads_cid', '')) == str(gads_cid) for loc in locs):
        same_cid = [loc for loc in locs if str(loc.get('gads_cid', '')) == str(gads_cid)]
        if len(same_cid) < len(locs):
            print(f'  [brand] Filtered from {len(locs)} to {len(same_cid)} locations matching gads_cid {gads_cid}')
        return same_cid
    return locs


def update_supabase_status(gads_cid, location_id=None, account_id=None, container_id=None):
    payload = {'gtm_container_status': 'has_container'}
    if account_id:
        payload['gtm_account_id'] = str(account_id)
    if container_id:
        payload['gtm_container_id'] = str(container_id)
    params = {'id': f'eq.{location_id}'} if location_id else {'gads_cid': f'eq.{gads_cid}'}
    r = requests.patch(
        f'{SUPABASE_URL}/rest/v1/locations',
        params=params,
        headers={**SUPABASE_HEADERS, 'Prefer': 'return=representation'},
        json=payload,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


# ── Auth ──────────────────────────────────────────────────────────────────────

def get_gtm_service(token_file=None):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    with open(token_file or TOKEN_FILE) as f:
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
            with open(token_file or TOKEN_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        else:
            raise RuntimeError('Token invalid. Re-run token auth script.')
    return build('tagmanager', 'v2', credentials=creds)


# ── Container lookup ──────────────────────────────────────────────────────────

INDEX_CACHE_FILE = os.path.join(SCRIPT_DIR, 'container_index_cache.json')

def _load_index_cache():
    if not os.path.exists(INDEX_CACHE_FILE):
        return {}
    with open(INDEX_CACHE_FILE) as f:
        return json.load(f).get('gtm_index', {})

CONTAINER_INDEX = _load_index_cache()


def _seed_cache(gtm_id, account_id, container_id):
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            cache = json.load(f)
    cache[gtm_id] = {'account_id': account_id, 'container_id': container_id}
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)


def _cache_and_return(cache, gtm_id, account_id, container_id):
    cache[gtm_id] = {'account_id': account_id, 'container_id': container_id}
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)
    return account_id, container_id


def find_container(service, gtm_id):
    """Return (account_id, container_id).
    1. gtm_id_cache.json (fastest)
    2. container_index_cache.json — has container_id, scans accounts to find owner
    3. Full account scan fallback
    Exceptions are logged instead of silently swallowed."""
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            cache = json.load(f)

    if gtm_id in cache:
        c = cache[gtm_id]
        print(f'  Found in cache: account={c["account_id"]}, container={c["container_id"]}')
        return c['account_id'], c['container_id']

    # container_index_cache has numeric container_id but not GTM account_id.
    # Scan accounts matching by container_id — much faster than matching by publicId.
    if os.path.exists(INDEX_CACHE_FILE):
        with open(INDEX_CACHE_FILE) as f:
            idx_cache = json.load(f)
        entry = idx_cache.get('gtm_index', {}).get(gtm_id.upper())
        if entry:
            known_ctr_id = str(entry[1])
            print(f'  Found container_id {known_ctr_id} in index cache. Scanning for account owner...')
            accounts = service.accounts().list().execute().get('account', [])
            for acct in accounts:
                try:
                    containers = service.accounts().containers().list(
                        parent=acct['path']
                    ).execute().get('container', [])
                    for c in containers:
                        if str(c.get('containerId')) == known_ctr_id:
                            account_id = acct['accountId']
                            print(f'  Found via index: account={account_id}, container={known_ctr_id}')
                            return _cache_and_return(cache, gtm_id, account_id, known_ctr_id)
                except Exception as e:
                    print(f'  [warn] account {acct.get("accountId")}: {e}')
                time.sleep(0.3)

    print(f'  Not in any cache. Full account scan...')
    accounts = service.accounts().list().execute().get('account', [])
    print(f'  {len(accounts)} accounts to scan.')

    from googleapiclient.errors import HttpError as _HttpError
    for idx, acct in enumerate(accounts, 1):
        if idx % 50 == 0:
            print(f'  Scanning {idx}/{len(accounts)}...')
        for attempt in range(4):
            try:
                containers = service.accounts().containers().list(
                    parent=acct['path']
                ).execute().get('container', [])
                for c in containers:
                    if c.get('publicId', '').upper() == gtm_id.upper():
                        account_id   = acct['accountId']
                        container_id = c['containerId']
                        print(f'  Found: account={account_id}, container={container_id}')
                        return _cache_and_return(cache, gtm_id, account_id, container_id)
                break  # success, no retry needed
            except _HttpError as e:
                if e.resp.status == 429:
                    wait = 15 * (2 ** attempt)
                    print(f'  [rate limit] 429 on account {acct.get("accountId")} — waiting {wait}s...')
                    time.sleep(wait)
                else:
                    print(f'  [warn] account {acct.get("accountId")}: {e}')
                    break
            except Exception as e:
                print(f'  [warn] account {acct.get("accountId")}: {e}')
                break
        time.sleep(0.8)

    raise RuntimeError(f'Container {gtm_id} not found in any accessible GTM account.')


# ── API helpers ───────────────────────────────────────────────────────────────

def _call(fn, max_retries=8, base_delay=3.0):
    from googleapiclient.errors import HttpError
    delay = base_delay
    for attempt in range(max_retries):
        try:
            return fn()
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < max_retries - 1:
                print(f'  [retry] HTTP {e.resp.status}, waiting {delay:.0f}s...')
                time.sleep(delay)
                delay = min(delay * 2, 60)
            else:
                raise


def get_workspace(service, acct, ctr):
    ws = _call(lambda: service.accounts().containers().workspaces().list(
        parent=f'accounts/{acct}/containers/{ctr}'
    ).execute()).get('workspace', [])
    if not ws:
        raise RuntimeError('No workspace found.')
    return ws[0]['workspaceId']


def create_and_publish_version(service, acct: str, ctr: str, ws: str, name: str = 'LNM Auto Setup') -> str:
    """Create a GTM version from the workspace and publish it. Returns version ID."""
    version_resp = _call(lambda: service.accounts().containers().workspaces().create_version(
        path=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}',
        body={'name': name, 'notes': 'Automated via LNM GTM scripts'},
    ).execute())
    if version_resp.get('compilerError'):
        import json as _json
        # Print top-level keys and non-tag fields for debugging
        debug = {k: v for k, v in version_resp.items() if k not in ('containerVersion',)}
        cv_debug = {k: v for k, v in version_resp.get('containerVersion', {}).items() if k not in ('tag', 'trigger', 'variable')}
        print(f'  [debug] version_resp keys: {list(version_resp.keys())}')
        print(f'  [debug] containerVersion (non-list): {_json.dumps(cv_debug, indent=2)[:2000]}')
        raise RuntimeError('GTM compiler error in workspace — check tags for missing required fields')
    version_id = version_resp['containerVersion']['containerVersionId']
    _call(lambda: service.accounts().containers().versions().publish(
        path=f'accounts/{acct}/containers/{ctr}/versions/{version_id}',
    ).execute())
    return version_id


LNM_SERVICE_ACCOUNTS = [
    'reports@leadsnearme.com',
    'analytics@leadsnearme.com',
    'analytics2@leadsnearme.com',
]

def grant_lnm_access(service, acct: str):
    """Ensure all 3 LNM service accounts have admin+publish on every container in acct."""
    containers = _call(lambda: service.accounts().containers().list(
        parent=f'accounts/{acct}'
    ).execute()).get('container', [])

    existing_perms = _call(lambda: service.accounts().user_permissions().list(
        parent=f'accounts/{acct}'
    ).execute()).get('userPermission', [])

    perm_map = {p.get('emailAddress', '').lower(): p for p in existing_perms}

    for email in LNM_SERVICE_ACCOUNTS:
        desired = {
            'emailAddress': email,
            'accountAccess': {'permission': 'admin'},
            'containerAccess': [
                {'containerId': c['containerId'], 'permission': 'publish'}
                for c in containers
            ],
        }
        existing = perm_map.get(email.lower())
        try:
            if existing:
                desired['path'] = existing['path']
                _call(lambda: service.accounts().user_permissions().update(
                    path=existing['path'], body=desired,
                ).execute())
            else:
                _call(lambda: service.accounts().user_permissions().create(
                    parent=f'accounts/{acct}', body=desired,
                ).execute())
            print(f'  ✓ Granted admin+publish → {email}')
        except Exception as e:
            print(f'  [warn] Permission grant failed for {email}: {e}')


def list_triggers(service, acct, ctr, ws):
    resp = _call(lambda: service.accounts().containers().workspaces().triggers().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())
    return {t['name']: t['triggerId'] for t in resp.get('trigger', [])}


def list_tags(service, acct, ctr, ws):
    resp = _call(lambda: service.accounts().containers().workspaces().tags().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())
    return {t['name']: t['tagId'] for t in resp.get('tag', [])}


def find_googtag_by_id(service, acct, ctr, tag_id_value):
    """Return tag name if a googtag already exists for tag_id_value in the live container."""
    try:
        live = _call(lambda: service.accounts().containers().versions().live(
            parent=f'accounts/{acct}/containers/{ctr}'
        ).execute())
        for t in live.get('tag', []):
            if t.get('type') == 'googtag':
                for p in t.get('parameter', []):
                    if p.get('key') == 'tagId' and p.get('value') == tag_id_value:
                        return t['name']
    except Exception:
        pass
    return None


def lookup_ga4_id(service, acct, ctr, ws):
    """Scan tags for a GA4 Config (gaawc) to find the measurement ID."""
    tags = _call(lambda: service.accounts().containers().workspaces().tags().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute()).get('tag', [])
    for t in tags:
        if t.get('type') == 'gaawc':
            for p in t.get('parameter', []):
                if p.get('key') == 'measurementId' and str(p.get('value')).startswith('G-'):
                    return str(p['value'])
    return None


def ensure_trigger(service, acct, ctr, ws, body, existing, force_recreate):
    name   = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    if name in existing:
        if not force_recreate:
            return existing[name], 'existed'
        result = _call(lambda: service.accounts().containers().workspaces().triggers().update(
            path=f'{parent}/triggers/{existing[name]}',
            body={k: v for k, v in body.items() if k not in ('accountId','containerId','triggerId')}
        ).execute())
        return result['triggerId'], 'updated'
    result = _call(lambda: service.accounts().containers().workspaces().triggers().create(
        parent=parent, body={k: v for k, v in body.items() if k not in ('accountId','containerId','triggerId')}
    ).execute())
    return result['triggerId'], 'new'


def ensure_tag(service, acct, ctr, ws, body, existing, force_recreate):
    name   = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    if name in existing:
        if not force_recreate:
            return existing[name], 'existed'
        result = _call(lambda: service.accounts().containers().workspaces().tags().update(
            path=f'{parent}/tags/{existing[name]}',
            body={k: v for k, v in body.items() if k not in ('accountId','containerId','tagId')}
        ).execute())
        return result['tagId'], 'updated'
    result = _call(lambda: service.accounts().containers().workspaces().tags().create(
        parent=parent, body={k: v for k, v in body.items() if k not in ('accountId','containerId','tagId')}
    ).execute())
    return result['tagId'], 'new'


def list_variables(service, acct, ctr, ws):
    resp = _call(lambda: service.accounts().containers().workspaces().variables().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())
    return {v['name']: v['variableId'] for v in resp.get('variable', [])}


def ensure_variable(service, acct, ctr, ws, body, existing, force_recreate):
    name   = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    if name in existing:
        if not force_recreate:
            return existing[name], 'existed'
        result = _call(lambda: service.accounts().containers().workspaces().variables().update(
            path=f'{parent}/variables/{existing[name]}',
            body={k: v for k, v in body.items() if k not in ('accountId', 'containerId', 'variableId')}
        ).execute())
        return result['variableId'], 'updated'
    result = _call(lambda: service.accounts().containers().workspaces().variables().create(
        parent=parent,
        body={k: v for k, v in body.items() if k not in ('accountId', 'containerId', 'variableId')}
    ).execute())
    return result['variableId'], 'new'


def enable_builtin_variable(service, acct, ctr, ws, var_type):
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    resp = _call(lambda: service.accounts().containers().workspaces().built_in_variables().list(
        parent=parent
    ).execute())
    enabled = {v['type'] for v in resp.get('builtInVariable', [])}
    if var_type in enabled:
        return 'existed'
    _call(lambda: service.accounts().containers().workspaces().built_in_variables().create(
        parent=parent, type=[var_type]
    ).execute())
    return 'new'


# ── Trigger / Tag bodies ──────────────────────────────────────────────────────

def appt_trigger(sched_label, appt_event):
    return {
        'name': f'CE - {sched_label} - Appointment Booked',
        'type': 'CUSTOM_EVENT',
        'customEventFilter': [{'type': 'EQUALS', 'parameter': [
            {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{_event}}'},
            {'type': 'TEMPLATE', 'key': 'arg1', 'value': appt_event},
        ]}],
    }


_TEKMETRIC_LISTENER_JS = """\
<script>
(function() {
  window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'bookingTool:closeModal') {
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event: 'tekmetric-booking-closed' });
    }
  });
})();
</script>"""


def tekmetric_listener_tag(all_pages_id):
    return {
        'name': 'TekMetric - Booking - postMessage Listener',
        'type': 'html',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'html',                 'value': _TEKMETRIC_LISTENER_JS},
            {'type': 'BOOLEAN',  'key': 'supportDocumentWrite', 'value': 'false'},
        ],
        'firingTriggerId': [all_pages_id],
        'tagFiringOption': 'ONCE_PER_LOAD',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


def shopmonkey_action_variable():
    return {
        'name': 'DLV - Shopmonkey Action',
        'type': 'v',
        'parameter': [
            {'type': 'INTEGER',  'key': 'dataLayerVersion', 'value': '2'},
            {'type': 'BOOLEAN',  'key': 'setDefaultValue',  'value': 'false'},
            {'type': 'TEMPLATE', 'key': 'name',             'value': 'action'},
        ],
    }


def shopmonkey_appt_trigger():
    return {
        'name': 'CE - Shopmonkey - Appointment Booked',
        'type': 'CUSTOM_EVENT',
        'customEventFilter': [{'type': 'EQUALS', 'parameter': [
            {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{_event}}'},
            {'type': 'TEMPLATE', 'key': 'arg1', 'value': 'sm_work_request_form_event'},
        ]}],
        'filter': [{'type': 'EQUALS', 'parameter': [
            {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{DLV - Shopmonkey Action}}'},
            {'type': 'TEMPLATE', 'key': 'arg1', 'value': 'work_request_form_submitted'},
        ]}],
    }


def autoops_all_events_trigger():
    return {
        'name': 'CE - AutoOps - All Events',
        'type': 'CUSTOM_EVENT',
        'customEventFilter': [{'type': 'MATCH_REGEX', 'parameter': [
            {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{_event}}'},
            {'type': 'TEMPLATE', 'key': 'arg1', 'value': '^ao-'},
        ]}],
    }


def ga4_autoops_all_events_tag(ga4_id, trigger_id):
    return {
        'name': 'GA4 - Event - AutoOps Events',
        'type': 'gaawe',
        'parameter': [
            {'type': 'TAG_REFERENCE', 'key': 'gaSettings',            'value': 'GA4 - Configuration'},
            {'type': 'TEMPLATE',      'key': 'measurementIdOverride', 'value': ga4_id},
            {'type': 'TEMPLATE',      'key': 'eventName',             'value': '{{_event}}'},
        ],
        'firingTriggerId': [trigger_id],
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


def phone_trigger(phone):
    return {
        'name': f'CL - Phone Click - {phone}',
        'type': 'LINK_CLICK',
        'filter': [{'type': 'CONTAINS', 'parameter': [
            {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{Click URL}}'},
            {'type': 'TEMPLATE', 'key': 'arg1', 'value': phone},
        ]}],
        'parameter': [
            {'type': 'BOOLEAN',  'key': 'waitForTags',        'value': 'true'},
            {'type': 'BOOLEAN',  'key': 'checkValidation',    'value': 'true'},
            {'type': 'TEMPLATE', 'key': 'waitForTagsTimeout', 'value': '2000'},
        ],
    }


def all_pages_trigger():
    return {'name': 'All Pages', 'type': 'PAGEVIEW'}


def ga4_config_tag(ga4_id, all_pages_id):
    return {
        'name': 'GA4 - Configuration',
        'type': 'gaawc',
        'parameter': [{'type': 'TEMPLATE', 'key': 'measurementId', 'value': ga4_id}],
        'firingTriggerId': [all_pages_id],
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


def ga4_event_tag(ga4_id, event_name, trigger_ids):
    return {
        'name': f'GA4 - Event - {event_name}',
        'type': 'gaawe',
        'parameter': [
            {'type': 'TAG_REFERENCE', 'key': 'gaSettings',            'value': 'GA4 - Configuration'},
            {'type': 'TEMPLATE',      'key': 'eventName',             'value': event_name},
            {'type': 'TEMPLATE',      'key': 'measurementIdOverride', 'value': ga4_id},
        ],
        'firingTriggerId': trigger_ids if isinstance(trigger_ids, list) else [trigger_ids],
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


def gads_appt_tag(store, gads_id, appt_label, appt_trigger_id):
    return {
        'name': f'GAds - {store} - Booked_Appointment',
        'type': 'awct',
        'parameter': [
            {'type': 'INTEGER',  'key': 'conversionId',    'value': str(gads_id)},
            {'type': 'TEMPLATE', 'key': 'conversionLabel', 'value': appt_label},
            {'type': 'TEMPLATE', 'key': 'conversionValue', 'value': '65'},
            {'type': 'TEMPLATE', 'key': 'currencyCode',    'value': 'USD'},
            {'type': 'BOOLEAN',  'key': 'remarketingOnly', 'value': 'false'},
            {'type': 'BOOLEAN',  'key': 'enabledMd',       'value': 'true'},
        ],
        'firingTriggerId': [appt_trigger_id],
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


def gads_phone_tag(store, gads_id, phone, phone_label, cl_trigger_id):
    return {
        'name': f'GAds - {store} - Phone_Click - {phone}',
        'type': 'awct',
        'parameter': [
            {'type': 'INTEGER',  'key': 'conversionId',    'value': str(gads_id)},
            {'type': 'TEMPLATE', 'key': 'conversionLabel', 'value': phone_label},
            {'type': 'TEMPLATE', 'key': 'conversionValue', 'value': '10'},
            {'type': 'TEMPLATE', 'key': 'currencyCode',    'value': 'USD'},
            {'type': 'BOOLEAN',  'key': 'remarketingOnly', 'value': 'false'},
            {'type': 'BOOLEAN',  'key': 'enabledMd',       'value': 'false'},
        ],
        'firingTriggerId': [cl_trigger_id],
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


def conversion_linker_tag(all_pages_id):
    return {
        'name': 'Conversion Linker',
        'type': 'gclidw',
        'parameter': [
            {'type': 'BOOLEAN', 'key': 'enableCrossDomainLinking', 'value': 'false'},
            {'type': 'BOOLEAN', 'key': 'enableUrlPassthrough',     'value': 'false'},
            {'type': 'BOOLEAN', 'key': 'decorateFormsWithData',    'value': 'false'},
        ],
        'firingTriggerId': [all_pages_id],
        'tagFiringOption': 'ONCE_PER_LOAD',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


def google_base_tag(gads_id, all_pages_id):
    return {
        'name': 'Google Tag - AW Config',
        'type': 'googtag',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'tagId', 'value': f'AW-{gads_id}'},
        ],
        'firingTriggerId': [all_pages_id],
        'tagFiringOption': 'ONCE_PER_LOAD',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


_AI_REFERRER_JS = """function() {
  var r = document.referrer || '';
  var s = ['perplexity.ai','chatgpt.com','chat.openai.com','gemini.google.com',
           'copilot.microsoft.com','claude.ai','you.com','phind.com'];
  for (var i = 0; i < s.length; i++) { if (r.indexOf(s[i]) !== -1) return s[i]; }
  return '';
}"""


def ai_referrer_variable():
    return {
        'name': 'JS - AI Referrer',
        'type': 'jsm',
        'parameter': [{'type': 'TEMPLATE', 'key': 'javascript', 'value': _AI_REFERRER_JS}],
    }


def text_fragment_trigger():
    return {
        'name': 'HC - Text Fragment',
        'type': 'HISTORY_CHANGE',
        'filter': [{'type': 'CONTAINS', 'parameter': [
            {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{New History Fragment}}'},
            {'type': 'TEMPLATE', 'key': 'arg1', 'value': ':~:text='},
        ]}],
    }


def ai_referral_trigger():
    return {
        'name': 'PV - AI Referral',
        'type': 'PAGEVIEW',
        'filter': [{'type': 'MATCH_REGEX', 'parameter': [
            {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{JS - AI Referrer}}'},
            {'type': 'TEMPLATE', 'key': 'arg1', 'value': '.+'},
        ]}],
    }


def ga4_ai_overview_tag(ga4_id, trigger_id):
    return {
        'name': 'GA4 - Event - ai_overview_click',
        'type': 'gaawe',
        'parameter': [
            {'type': 'TAG_REFERENCE', 'key': 'gaSettings',            'value': 'GA4 - Configuration'},
            {'type': 'TEMPLATE',      'key': 'measurementIdOverride', 'value': ga4_id},
            {'type': 'TEMPLATE',      'key': 'eventName',             'value': 'ai_overview_click'},
        ],
        'firingTriggerId': [trigger_id],
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


def ga4_ai_referral_tag(ga4_id, trigger_id):
    return {
        'name': 'GA4 - Event - ai_referral',
        'type': 'gaawe',
        'parameter': [
            {'type': 'TAG_REFERENCE', 'key': 'gaSettings',            'value': 'GA4 - Configuration'},
            {'type': 'TEMPLATE',      'key': 'measurementIdOverride', 'value': ga4_id},
            {'type': 'TEMPLATE',      'key': 'eventName',             'value': 'ai_referral'},
            {'type': 'LIST',          'key': 'eventSettingsTable', 'list': [
                {'type': 'MAP', 'map': [
                    {'type': 'TEMPLATE', 'key': 'parameter',      'value': 'ai_source'},
                    {'type': 'TEMPLATE', 'key': 'parameterValue', 'value': '{{JS - AI Referrer}}'},
                ]},
            ]},
        ],
        'firingTriggerId': [trigger_id],
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


# ── Google Ads ────────────────────────────────────────────────────────────────

def fetch_gads_labels(cid):
    """Fetch conversion labels from Google Ads API.
    Returns {
        'conversion_id': str,
        'appt': str|None,             # best appointment label
        'phones': {phone10: label},   # specific per-number labels
        'phone_generic': str|None,    # fallback label for any phone click
    }
    Returns None if credentials unavailable or API fails.
    """
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError:
        return None

    cfg = {
        'developer_token':   os.getenv('GOOGLE_ADS_DEVELOPER_TOKEN'),
        'client_id':         os.getenv('GOOGLE_ADS_CLIENT_ID'),
        'client_secret':     os.getenv('GOOGLE_ADS_CLIENT_SECRET'),
        'refresh_token':     os.getenv('GOOGLE_ADS_REFRESH_TOKEN'),
        'login_customer_id': os.getenv('MANAGER_CID'),
        'use_proto_plus':    True,
    }
    if not all([cfg['developer_token'], cfg['client_id'], cfg['client_secret'], cfg['refresh_token']]):
        return None

    try:
        client = GoogleAdsClient.load_from_dict(cfg)
        svc = client.get_service('GoogleAdsService')
        rows = svc.search(
            customer_id=re.sub(r'\D', '', str(cid)),
            query="""
                SELECT conversion_action.name, conversion_action.tag_snippets
                FROM conversion_action
                WHERE conversion_action.status = 'ENABLED'
            """,
        )
        out = {'conversion_id': None, 'appt': None, 'phones': {}, 'phone_generic': None}
        seen_labels = set()
        for row in rows:
            ca = row.conversion_action
            for snippet in ca.tag_snippets:
                m = re.search(r"'send_to':\s*'AW-(\d+)/([^']+)'", snippet.event_snippet)
                if not m:
                    continue
                conv_id, label = m.group(1), m.group(2)
                if label in seen_labels:
                    continue
                seen_labels.add(label)
                if not out['conversion_id']:
                    out['conversion_id'] = conv_id
                name_lower = ca.name.lower()
                # Phone with explicit number in name (e.g. "Phone - 9414014471")
                digits = re.sub(r'\D', '', ca.name)
                if len(digits) == 10:
                    out['phones'][digits] = label
                elif any(k in name_lower for k in ('phone', 'call click', 'phone click')):
                    # Generic phone conversion — use as fallback
                    if not out['phone_generic']:
                        out['phone_generic'] = label
                elif any(k in name_lower for k in ('appointment', 'booked', 'appt', 'booking', 'dc-service')):
                    if not out['appt']:
                        out['appt'] = label
        return out if (out['appt'] or out['phones'] or out['phone_generic'] or out['conversion_id']) else None
    except Exception as e:
        print(f'  [warn] Google Ads API error: {e}')
        return None


# ── CallRail ──────────────────────────────────────────────────────────────────

def fetch_callrail_script_url(account_id, company_id):
    """Fetch the CallRail swap.js URL for a company via the CallRail API."""
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


def callrail_variable(company_id):
    return {
        'name': 'C - CallRail Account ID',
        'type': 'c',
        'parameter': [{'type': 'TEMPLATE', 'key': 'value', 'value': str(company_id)}],
    }


def callrail_dni_tag(script_url, trigger_id):
    html = f'<script type="text/javascript" async src="{script_url}"></script>\n'
    return {
        'name': 'CallRail - DNI - Swap Script',
        'type': 'html',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'html',                 'value': html},
            {'type': 'BOOLEAN',  'key': 'supportDocumentWrite', 'value': 'false'},
        ],
        'firingTriggerId': [trigger_id],
        'tagFiringOption': 'ONCE_PER_LOAD',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


# ── Lead Form Attribution ─────────────────────────────────────────────────────

_ATTRIBUTION_FIELDS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'gclid', 'msclkid']

_ATTRIBUTION_STORE_HTML = (
    '<script>\n'
    '(function() {\n'
    "  if (document.cookie.indexOf('lnm_attribution=') !== -1) return;\n"
    '  var p = new URLSearchParams(window.location.search);\n'
    '  var a = {};\n'
    "  ['utm_source','utm_medium','utm_campaign','utm_term','utm_content','gclid','msclkid'].forEach(function(k) {\n"
    '    if (p.get(k)) a[k] = p.get(k);\n'
    '  });\n'
    '  if (Object.keys(a).length) {\n'
    "    document.cookie = 'lnm_attribution=' + encodeURIComponent(JSON.stringify(a)) + ';path=/;max-age=2592000;SameSite=Lax';\n"
    '  }\n'
    '})();\n'
    '</script>'
)


def attribution_store_tag(all_pages_id: str) -> dict:
    return {
        'name': 'LNM - Attribution - Store',
        'type': 'html',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'html',                 'value': _ATTRIBUTION_STORE_HTML},
            {'type': 'BOOLEAN',  'key': 'supportDocumentWrite', 'value': 'false'},
        ],
        'firingTriggerId': [all_pages_id],
        'tagFiringOption': 'ONCE_PER_LOAD',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


def attribution_variable(field: str) -> dict:
    js = (
        'function() {\n'
        '  try {\n'
        "    var m = document.cookie.match(/lnm_attribution=([^;]+)/);\n"
        "    if (!m) return '';\n"
        "    return JSON.parse(decodeURIComponent(m[1]))['" + field + "'] || '';\n"
        "  } catch(e) { return ''; }\n"
        '}'
    )
    return {
        'name': f'JS - Attribution - {field}',
        'type': 'jsm',
        'parameter': [{'type': 'TEMPLATE', 'key': 'javascript', 'value': js}],
    }


def cf7_form_trigger() -> dict:
    return {
        'name': 'CE - CF7 - Form Submitted',
        'type': 'CUSTOM_EVENT',
        'customEventFilter': [{'type': 'EQUALS', 'parameter': [
            {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{_event}}'},
            {'type': 'TEMPLATE', 'key': 'arg1', 'value': 'wpcf7mailsent'},
        ]}],
    }


def wpforms_form_trigger() -> dict:
    return {
        'name': 'CE - WPForms - Form Submitted',
        'type': 'CUSTOM_EVENT',
        'customEventFilter': [{'type': 'EQUALS', 'parameter': [
            {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{_event}}'},
            {'type': 'TEMPLATE', 'key': 'arg1', 'value': 'wpforms_successful_submit'},
        ]}],
    }


def generic_form_trigger() -> dict:
    return {
        'name': 'FS - Generic Form Submit',
        'type': 'FORM_SUBMISSION',
        'parameter': [
            {'type': 'BOOLEAN',  'key': 'waitForTags',        'value': 'true'},
            {'type': 'BOOLEAN',  'key': 'checkValidation',    'value': 'false'},
            {'type': 'TEMPLATE', 'key': 'waitForTagsTimeout', 'value': '2000'},
        ],
    }


def ga4_lead_tag(ga4_id: str, trigger_ids: list) -> dict:
    return {
        'name': 'GA4 - Event - generate_lead',
        'type': 'gaawe',
        'parameter': [
            {'type': 'TAG_REFERENCE', 'key': 'gaSettings',            'value': 'GA4 - Configuration'},
            {'type': 'TEMPLATE',      'key': 'measurementIdOverride', 'value': ga4_id},
            {'type': 'TEMPLATE',      'key': 'eventName',             'value': 'generate_lead'},
            {'type': 'LIST', 'key': 'eventSettingsTable', 'list': [
                {'type': 'MAP', 'map': [
                    {'type': 'TEMPLATE', 'key': 'parameter',      'value': f},
                    {'type': 'TEMPLATE', 'key': 'parameterValue', 'value': '{{JS - Attribution - %s}}' % f},
                ]}
                for f in _ATTRIBUTION_FIELDS
            ]},
        ],
        'firingTriggerId': trigger_ids,
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


# ── Social & Advertising Pixels ───────────────────────────────────────────────

def constant_variable(name, value=''):
    return {
        'name': f'C - {name}',
        'type': 'c',
        'parameter': [{'type': 'TEMPLATE', 'key': 'value', 'value': str(value)}],
    }

def meta_pixel_tag(all_pages_id):
    html = (
        "<script>\n"
        "!function(f,b,e,v,n,t,s)\n"
        "{if(f.fbq)return;n=f.fbq=function(){n.callMethod?\n"
        "n.callMethod.apply(n,arguments):n.queue.push(arguments)};\n"
        "if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';\n"
        "n.queue=[];t=b.createElement(e);t.async=!0;\n"
        "t.src=v;s=b.getElementsByTagName(e)[0];\n"
        "s.parentNode.insertBefore(t,s)}(window, document,'script',\n"
        "'https://connect.facebook.net/en_US/fbevents.js');\n"
        "fbq('init', '{{C - Meta Pixel ID}}');\n"
        "fbq('track', 'PageView');\n"
        "</script>"
    )
    return {
        'name': 'Meta - Pixel - Base',
        'type': 'html',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'html',                 'value': html},
            {'type': 'BOOLEAN',  'key': 'supportDocumentWrite', 'value': 'false'},
        ],
        'firingTriggerId': [all_pages_id],
        'tagFiringOption': 'ONCE_PER_LOAD',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }

def tiktok_pixel_tag(all_pages_id):
    html = (
        "<script>\n"
        "!function (w, d, t) {\n"
        "  w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];ttq.methods=[\"page\",\"track\",\"identify\",\"instances\",\"debug\",\"on\",\"off\",\"once\",\"ready\",\"alias\",\"group\",\"enableCookie\",\"disableCookie\"],ttq.setAndLog=function(t,e){t.split(\".\").reduce(function(t,e){t[e]=t[e]||{};return t[e];},ttq).log=e};ttq.instance=function(t){for(var e=ttq._i[t]||[],n=0;n<ttq.methods.length;n++)ttq.setAndLog(e,ttq.methods[n]);return e};ttq.load=function(e,n){var i=\"https://analytics.tiktok.com/i18n/pixel/events.js\";ttq._i=ttq._i||{},ttq._i[e]=[],ttq._i[e]._u=i,ttq._t=ttq._t||+new Date,ttq._o=ttq._o||{},ttq._o[e]=n||{};var o=document.createElement(\"script\");o.type=\"text/javascript\",o.async=!0,o.src=i+\"?sdkid=\"+e+\"&lib=\"+t;var a=document.getElementsByTagName(\"script\")[0];a.parentNode.insertBefore(o,a)};\n"
        "  ttq.load('{{C - TikTok Pixel ID}}');\n"
        "  ttq.page();\n"
        "}(window, document, 'ttq');\n"
        "</script>"
    )
    return {
        'name': 'TikTok - Pixel - Base',
        'type': 'html',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'html',                 'value': html},
            {'type': 'BOOLEAN',  'key': 'supportDocumentWrite', 'value': 'false'},
        ],
        'firingTriggerId': [all_pages_id],
        'tagFiringOption': 'ONCE_PER_LOAD',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }

def linkedin_insight_tag(all_pages_id):
    html = (
        "<script type=\"text/javascript\">\n"
        "_linkedin_partner_id = \"{{C - LinkedIn Partner ID}}\";\n"
        "window._linkedin_data_res_util = window._linkedin_data_res_util || [];\n"
        "window._linkedin_data_res_util.push({\n"
        "  partner_id: _linkedin_partner_id\n"
        "});\n"
        "</script>\n"
        "<script type=\"text/javascript\">\n"
        "(function(l) {\n"
        "  if (!l){window.lintrk = function(a,b){window.lintrk.q.push([a,b])};\n"
        "  window.lintrk.q=[]}\n"
        "  var s = document.getElementsByTagName(\"script\")[0];\n"
        "  var b = document.createElement(\"script\");\n"
        "  b.type = \"text/javascript\";b.async = true;\n"
        "  b.src = \"https://snap.licdn.com/li.lms-analytics/insight.min.js\";\n"
        "  s.parentNode.insertBefore(b, s);\n"
        "})(window.lintrk);\n"
        "</script>"
    )
    return {
        'name': 'LinkedIn - Insight Tag - Base',
        'type': 'html',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'html',                 'value': html},
            {'type': 'BOOLEAN',  'key': 'supportDocumentWrite', 'value': 'false'},
        ],
        'firingTriggerId': [all_pages_id],
        'tagFiringOption': 'ONCE_PER_LOAD',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }

def microsoft_uet_tag(all_pages_id):
    html = (
        "<script>(function(w,d,t,r,u){var f,n,i;w[u]=w[u]||[],f=function(){var o={ti:\"{{C - Microsoft UET ID}}\", enableAutoSpaTracking: true};o.q=w[u],w[u]=new UET(o),w[u].push(\"pageLoad\")},n=d.createElement(t),n.src=r,n.async=1,n.onload=n.onreadystatechange=function(){var s=this.readyState;s&&s!==\"loaded\"&&s!==\"complete\"||(f(),n.onload=n.onreadystatechange=null)},i=d.getElementsByTagName(t)[0],i.parentNode.insertBefore(n,i)})(window,document,\"script\",\"//bat.bing.com/bat.js\",\"uetq\");</script>"
    )
    return {
        'name': 'Microsoft - UET - Base',
        'type': 'html',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'html',                 'value': html},
            {'type': 'BOOLEAN',  'key': 'supportDocumentWrite', 'value': 'false'},
        ],
        'firingTriggerId': [all_pages_id],
        'tagFiringOption': 'ONCE_PER_LOAD',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

SCHEDULER_MAP = {
    'autoops':    ('ao-appointment-booked',      'AutoOps'),
    'steercrm':   ('ao-appointment-booked',      'SteerCRM'),
    'shopgenie':  ('appointment_booked',         'Shop Genie'),
    'oktorocket': ('dc-service-booked',          'OktoRocket'),
    'shopmonkey': ('sm_work_request_form_event', 'Shopmonkey'),
    'tekmetric':  ('tekmetric-booking-closed',   'TekMetric'),
}

def get_scheduler(scheduler_type):
    key = str(scheduler_type or '').lower().replace(' ', '').replace('-', '')
    for k, v in SCHEDULER_MAP.items():
        if k in key:
            return v
    return SCHEDULER_MAP['oktorocket']


def derive_store_name(client_name):
    SKIP = {'auto','automotive','repair','service','center','care','shop',
            'tire','garage','motors','motor','llc','inc','and','&','the','of'}
    name = str(client_name or '').strip()
    if ' - ' in name:
        candidate = name.split(' - ')[-1].strip()
        if candidate:
            return candidate
    words = [w for w in name.split() if w.lower() not in SKIP]
    return ' '.join(words[:2]) if words else name


def clean_phone(raw):
    return re.sub(r'\D', '', str(raw or ''))


def log(icon, kind, name):
    print(f'  {icon} {kind}: {name}')


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Set up LNM GTM tags + triggers from Supabase.')
    parser.add_argument('--gads-cid',          required=True, help='Google Ads CID, e.g. 6322162456')
    parser.add_argument('--dry-run',           action='store_true')
    parser.add_argument('--force-recreate',    action='store_true', help='Delete and replace existing items')
    parser.add_argument('--token-file',        default=None, help='OAuth token JSON (default: token.json)')
    # Override flags — bypass Supabase when record is missing or incomplete
    parser.add_argument('--gtm-id',            default=None, help='GTM container ID, e.g. GTM-XXXXXXXX')
    parser.add_argument('--ga4-id',            default=None, help='GA4 measurement ID, e.g. G-XXXXXXXXXX')
    parser.add_argument('--gads-conversion-id', default=None, help='Google Ads conversion ID (numeric)')
    parser.add_argument('--appt-label',        default=None, help='GAds appointment conversion label')
    parser.add_argument('--phone-label',       default=None, help='GAds phone conversion label (optional)')
    parser.add_argument('--phone',             default=None, help='Phone number digits (optional)')
    parser.add_argument('--scheduler',         default=None, help='Scheduler: autoops | steercrm | shopgenie | oktorocket | shopmonkey | tekmetric | protractor')
    parser.add_argument('--name',              default=None, help='Client name (for store tag derivation)')
    parser.add_argument('--account-id',        default=None, help='GTM account ID — bypasses full account scan, seeds cache')
    parser.add_argument('--location-id',       default=None, help='Supabase location UUID (disambiguates shared CIDs)')
    args = parser.parse_args()

    has_overrides = bool(args.gtm_id or args.ga4_id or args.gads_conversion_id or args.appt_label)

    if has_overrides:
        missing_overrides = [f for f, v in [
            ('--gtm-id', args.gtm_id),
            ('--ga4-id', args.ga4_id),
            ('--gads-conversion-id', args.gads_conversion_id),
            ('--appt-label', args.appt_label),
            ('--name', args.name),
        ] if not v]
        if missing_overrides:
            raise SystemExit(f'When using overrides, these are also required: {", ".join(missing_overrides)}')
        loc = {
            'name':               args.name,
            'gtm_id':             args.gtm_id,
            'ga4_measurement_id':  args.ga4_id,
            'gads_conversion_id':  args.gads_conversion_id,
            'gads_appt_label':     args.appt_label,
            'gads_phone_label':   args.phone_label or '',
            'phone_number':       args.phone or '',
            'scheduler_type':     args.scheduler or 'oktorocket',
        }
        print(f'Using CLI overrides (skipping Supabase lookup).')
    else:
        print(f'Fetching location data for CID {args.gads_cid}...')
        loc = fetch_location(args.gads_cid, location_id=args.location_id)

        # ── Data normalization / Fallbacks ───────────────────────────────────
        
        # 1. GA4 Measurement ID (G-XXXXX)
        m_id = loc.get('ga4_measurement_id')
        if not m_id or not str(m_id).startswith('G-'):
            # Fallback to ga4_id if it looks like a measurement ID
            old_ga4 = loc.get('ga4_id')
            if old_ga4 and str(old_ga4).startswith('G-'):
                m_id = old_ga4
        loc['ga4_measurement_id'] = m_id

        # 2. GAds Appt Label (dc_label fallback)
        if not loc.get('gads_appt_label'):
            loc['gads_appt_label'] = loc.get('gads_dc_label')

        required = ['gtm_id', 'gads_conversion_id']
        missing  = [f for f in required if not loc.get(f)]
        if missing:
            raise SystemExit(f'Missing required fields in Supabase: {", ".join(missing)}\n'
                             f'Pass them as CLI flags (--gtm-id, --ga4-id, --gads-conversion-id,\n'
                             f'--appt-label, --scheduler, --name) to bypass Supabase.')

    gtm_id     = str(loc['gtm_id']).strip()
    ga4_id     = str(loc['ga4_measurement_id'] or '').strip()
    gads_id    = str(int(float(str(loc['gads_conversion_id']).replace('AW-', '').strip())))

    # Override with correct Conversion ID from gads_conversions table.
    # locations.gads_conversion_id may store the CID (wrong); gads_conversions
    # is synced from the GAds API and holds the real tag Conversion ID.
    if not has_overrides:
        table_conv_id = fetch_conversion_id_from_table(loc['id'])
        if table_conv_id and table_conv_id != gads_id:
            print(f'  ✓ Conversion ID from gads_conversions: {table_conv_id} (was {gads_id})')
            gads_id = table_conv_id
    appt_label = str(loc.get('gads_appt_label') or '').strip()
    
    # ── Multi-phone logic ───────────────────────────────────────────────────
    phone_pairs = []
    dashboard_type = loc.get('dashboard_type') or ''
    brand_id = loc.get('brand_id')

    multi_phone_types = ('All Locations One Site', 'New MSO structure', 'Mothership Site with Microsites')
    
    if dashboard_type in multi_phone_types and brand_id and not args.location_id:
        print(f'Detected dashboard_type "{dashboard_type}". Fetching all brand locations for phone numbers...')
        brand_locs = fetch_brand_locations(brand_id, gads_cid=args.gads_cid)
        seen_brand_phones: dict[str, str] = {}
        for bl in brand_locs:
            p = clean_phone(bl.get('phone_number'))
            l = str(bl.get('gads_phone_label') or '').strip()
            if p and l and p not in seen_brand_phones:
                seen_brand_phones[p] = l
        phone_pairs = sorted(seen_brand_phones.items())
        print(f'  Found {len(phone_pairs)} unique phone number(s) for brand ID {brand_id}')
    else:
        p = clean_phone(loc.get('phone_number', ''))
        l = str(loc.get('gads_phone_label') or '').strip()
        if p and l:
            phone_pairs.append((p, l))

    # ── Google Ads label enrichment ─────────────────────────────────────────
    print('Fetching conversion labels from Google Ads API...')
    gads_data = fetch_gads_labels(args.gads_cid)
    if gads_data:
        if gads_data['conversion_id']:
            gads_id = gads_data['conversion_id']
            print(f'  ✓ Conversion ID from GAds: {gads_id}')
        if gads_data['appt'] and not appt_label:
            appt_label = gads_data['appt']
            print(f'  ✓ Appt label from GAds: {appt_label}')
        elif gads_data['appt'] and appt_label != gads_data['appt']:
            print(f'  ✓ Appt label from GAds (overrides Supabase): {gads_data["appt"]}')
            appt_label = gads_data['appt']
        # Fill in/override phone labels from GAds
        # Only use specific 10-digit matches to override Supabase.
        # Generic phone label only fills in when Supabase value is missing.
        generic_phone_label = gads_data.get('phone_generic')
        updated = []
        seen_phones = set()
        for p, l in phone_pairs:
            specific = gads_data['phones'].get(p)
            if specific and specific != l:
                print(f'  ✓ Phone {p} label from GAds (specific match): {specific}')
                updated.append((p, specific))
            elif not l and generic_phone_label:
                print(f'  ✓ Phone {p} label from GAds (generic fallback): {generic_phone_label}')
                updated.append((p, generic_phone_label))
            else:
                updated.append((p, l))
            seen_phones.add(p)
        for phone, label in sorted(gads_data['phones'].items()):
            if phone not in seen_phones:
                print(f'  ✓ Additional phone from GAds: {phone}  label={label}')
                updated.append((phone, label))
        phone_pairs = updated
    else:
        print('  [warn] Google Ads API unavailable — using Supabase labels')

    has_phone = len(phone_pairs) > 0

    scheduler_type = loc.get('scheduler_type') or ''
    has_scheduler  = bool(scheduler_type)
    appt_event = sched_label = None
    if has_scheduler:
        appt_event, sched_label = get_scheduler(scheduler_type)
    store = derive_store_name(loc['name'])

    cr_account_id = str(loc.get('callrail_account_id') or '').strip()
    cr_company_id = str(loc.get('callrail_company_id') or '').strip()
    has_callrail  = bool(cr_account_id and cr_company_id)

    print(f'\n=== LNM GTM Setup: {gtm_id} ===')
    print(f'  Client    : {loc["name"]}')
    print(f'  Store tag : {store}')
    print(f'  GA4       : {ga4_id!r}')  # repr shows invisible chars
    print(f'  GAds ID   : {gads_id}')
    if has_scheduler:
        print(f'  Scheduler : {sched_label} (event={appt_event})')
        print(f'  Appt label: {appt_label}')
    else:
        print(f'  Scheduler : (none — appt tags skipped)')
    if has_phone:
        for p, l in phone_pairs:
            print(f'  Phone     : {p}  label={l}')
    else:
        print(f'  Phone     : (none)')
    if has_callrail:
        print(f'  CallRail  : company={cr_company_id} acct={cr_account_id}')
    else:
        print(f'  CallRail  : (none — DNI tag skipped)')

    if args.dry_run:
        print('\n[DRY RUN] Would create:')
        if has_scheduler:
            print(f'  Trigger: CE - {sched_label} - Appointment Booked')
        if has_phone:
            for p, l in phone_pairs:
                print(f'  Trigger: CL - Phone Click - {p}')
        print(f'  Trigger: All Pages')
        print(f'  Tag: Conversion Linker')
        print(f'  Tag: Google Tag - AW Config')
        print(f'  Tag: GA4 - Configuration')
        if has_scheduler:
            print(f'  Tag: GA4 - Event - {appt_event}')
        _sched_key_dry = str(scheduler_type or '').lower().replace(' ', '').replace('-', '')
        if 'autoops' in _sched_key_dry or 'steercrm' in _sched_key_dry:
            print(f'  Trigger: CE - AutoOps - All Events')
            print(f'  Tag: GA4 - Event - AutoOps Events')
            print(f'  Tag DELETE (if exists): GA4 - Event - ao-appointment-booked')
        if 'shopmonkey' in _sched_key_dry:
            print(f'  Variable: DLV - Shopmonkey Action')
        if 'tekmetric' in _sched_key_dry:
            print(f'  Tag: TekMetric - Booking - postMessage Listener')
        if has_phone:
            print(f'  Tag: GA4 - Event - phone_click (fires on all {len(phone_pairs)} triggers)')
        if has_scheduler:
            print(f'  Tag: GAds - {store} - Booked_Appointment')
        if has_phone:
            for p, l in phone_pairs:
                print(f'  Tag: GAds - {store} - Phone_Click - {p}')
        print(f'  Variable: JS - AI Referrer')
        print(f'  Trigger: HC - Text Fragment')
        print(f'  Trigger: PV - AI Referral')
        print(f'  Tag: GA4 - Event - ai_overview_click')
        print(f'  Tag: GA4 - Event - ai_referral')
        if has_callrail:
            print(f'  Variable: C - CallRail Account ID')
            print(f'  Tag: CallRail - DNI - Swap Script')
        print(f'  Tag: LNM - Attribution - Store')
        for f in _ATTRIBUTION_FIELDS:
            print(f'  Variable: JS - Attribution - {f}')
        print(f'  Trigger: CE - CF7 - Form Submitted')
        print(f'  Trigger: CE - WPForms - Form Submitted')
        print(f'  Trigger: FS - Generic Form Submit')
        print(f'  Tag: GA4 - Event - generate_lead')
        print('\n[DRY RUN] No changes made.')
        return

    service = get_gtm_service(args.token_file)

    # Prefer Supabase-stored IDs → CLI override → cache/scan fallback
    sb_account_id   = str(loc.get('gtm_account_id') or '')
    sb_container_id = str(loc.get('gtm_container_id') or '')

    if args.account_id:
        acct_id = str(args.account_id)
        ctr_id  = sb_container_id or str(CONTAINER_INDEX.get(gtm_id.upper(), [None, None])[1] or '')
        if not ctr_id:
            raise SystemExit(f'--account-id given but no container_id found. Check GTM UI URL.')
        _seed_cache(gtm_id, acct_id, ctr_id)
        print(f'  Using CLI account_id: account={acct_id}, container={ctr_id}')
    elif sb_account_id and sb_container_id:
        acct_id = sb_account_id
        ctr_id  = sb_container_id
        _seed_cache(gtm_id, acct_id, ctr_id)
        print(f'  Using Supabase IDs: account={acct_id}, container={ctr_id}')
    else:
        acct_id, ctr_id = find_container(service, gtm_id)
    try:
        ws_id = get_workspace(service, acct_id, ctr_id)
    except Exception as e:
        from googleapiclient.errors import HttpError
        if isinstance(e, HttpError) and e.resp.status == 404 and sb_account_id and sb_container_id and not args.account_id:
            print(f'  [warn] Stored IDs returned 404 — clearing cache and scanning GTM accounts...')
            acct_id, ctr_id = find_container(service, gtm_id)
            ws_id = get_workspace(service, acct_id, ctr_id)
        else:
            raise
    existing_triggers  = list_triggers(service, acct_id, ctr_id, ws_id)
    existing_tags      = list_tags(service, acct_id, ctr_id, ws_id)
    existing_variables = list_variables(service, acct_id, ctr_id, ws_id)

    # ── Late GA4 ID Recovery ────────────────────────────────────────────────
    if not ga4_id or not ga4_id.startswith('G-'):
        print('  GA4 Measurement ID missing in DB. Scanning GTM container...')
        recovered_id = lookup_ga4_id(service, acct_id, ctr_id, ws_id)
        if recovered_id:
            print(f'  ✓ Recovered GA4 ID: {recovered_id}')
            ga4_id = recovered_id
        else:
            raise SystemExit('Error: Could not find GA4 Measurement ID in Supabase OR GTM container.\n'
                             'Please set ga4_measurement_id in Supabase or pass --ga4-id.')

    print(f'\nWorkspace: {ws_id} | existing triggers: {len(existing_triggers)}, tags: {len(existing_tags)}, variables: {len(existing_variables)}\n')

    fr = args.force_recreate

    # With --force-recreate, clean workspace changeset:
    # - ADDED/MODIFIED items → delete from workspace
    # - DELETED items (live tags previously marked for deletion by buggy runs) → revert
    if fr:
        parent = f'accounts/{acct_id}/containers/{ctr_id}/workspaces/{ws_id}'
        status = _call(lambda: service.accounts().containers().workspaces().getStatus(
            path=parent
        ).execute())
        tags_add, tags_del = [], []
        trigs_add, trigs_del = [], []
        vars_add, vars_del = [], []
        for c in status.get('workspaceChange', []):
            cs = c.get('changeStatus', '')
            if 'tag' in c:
                (tags_add if cs in ('ADDED', 'MODIFIED') else tags_del if cs == 'DELETED' else []).append(c['tag']['tagId'])
            elif 'trigger' in c:
                (trigs_add if cs in ('ADDED', 'MODIFIED') else trigs_del if cs == 'DELETED' else []).append(c['trigger']['triggerId'])
            elif 'variable' in c:
                (vars_add if cs in ('ADDED', 'MODIFIED') else vars_del if cs == 'DELETED' else []).append(c['variable']['variableId'])
        if any([tags_add, tags_del, trigs_add, trigs_del, vars_add, vars_del]):
            print(f'  [force-recreate] Delete {len(tags_add)} tags, revert {len(tags_del)} deleted-marks, '
                  f'delete {len(trigs_add)} triggers, revert {len(trigs_del)}, delete {len(vars_add)} vars, revert {len(vars_del)}...')
            for tid in tags_add:
                try:
                    _call(lambda tid=tid: service.accounts().containers().workspaces().tags().delete(
                        path=f'{parent}/tags/{tid}'
                    ).execute())
                except Exception as e:
                    print(f'    [warn] Could not delete tag {tid}: {e}')
            for tid in tags_del:
                try:
                    _call(lambda tid=tid: service.accounts().containers().workspaces().tags().revert(
                        path=f'{parent}/tags/{tid}'
                    ).execute())
                except Exception as e:
                    print(f'    [warn] Could not revert tag {tid}: {e}')
            for tid in trigs_add:
                try:
                    _call(lambda tid=tid: service.accounts().containers().workspaces().triggers().delete(
                        path=f'{parent}/triggers/{tid}'
                    ).execute())
                except Exception as e:
                    print(f'    [warn] Could not delete trigger {tid}: {e}')
            for tid in trigs_del:
                try:
                    _call(lambda tid=tid: service.accounts().containers().workspaces().triggers().revert(
                        path=f'{parent}/triggers/{tid}'
                    ).execute())
                except Exception as e:
                    print(f'    [warn] Could not revert trigger {tid}: {e}')
            for vid in vars_add:
                try:
                    _call(lambda vid=vid: service.accounts().containers().workspaces().variables().delete(
                        path=f'{parent}/variables/{vid}'
                    ).execute())
                except Exception as e:
                    print(f'    [warn] Could not delete variable {vid}: {e}')
            for vid in vars_del:
                try:
                    _call(lambda vid=vid: service.accounts().containers().workspaces().variables().revert(
                        path=f'{parent}/variables/{vid}'
                    ).execute())
                except Exception as e:
                    print(f'    [warn] Could not revert variable {vid}: {e}')
        # Re-fetch after cleanup — workspace now mirrors live container
        existing_triggers  = list_triggers(service, acct_id, ctr_id, ws_id)
        existing_tags      = list_tags(service, acct_id, ctr_id, ws_id)
        existing_variables = list_variables(service, acct_id, ctr_id, ws_id)
        print(f'  [force-recreate] Post-cleanup: {len(existing_triggers)} triggers, {len(existing_tags)} tags, {len(existing_variables)} variables')

    # Triggers
    appt_tid = None
    sched_key = str(scheduler_type or '').lower().replace(' ', '').replace('-', '')
    if has_scheduler:
        if 'shopmonkey' in sched_key:
            trigger_body = shopmonkey_appt_trigger()
        else:
            trigger_body = appt_trigger(sched_label, appt_event)
        appt_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, trigger_body, existing_triggers, fr)
        log('✓' if st != 'existed' else '·', 'Trigger', f'CE - {sched_label} - Appointment Booked ({st})')

    cl_tid = None
    # 0. Phone Triggers
    phone_to_tid = {}
    if has_phone:
        for p, l in phone_pairs:
            cl_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, phone_trigger(p), existing_triggers, fr)
            log('✓' if st != 'existed' else '·', 'Trigger', f'CL - Phone Click - {p} ({st})')
            phone_to_tid[p] = cl_tid

    ap_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, all_pages_trigger(), existing_triggers, fr)
    log('✓' if st != 'existed' else '·', 'Trigger', f'All Pages ({st})')

    # Tags
    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, conversion_linker_tag(ap_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'Conversion Linker ({st})')

    _aw_existing = find_googtag_by_id(service, acct_id, ctr_id, f'AW-{gads_id}')
    if _aw_existing:
        log('·', 'Tag', f'Google Tag - AW Config (existed as "{_aw_existing}")')
    else:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, google_base_tag(gads_id, ap_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'Google Tag - AW Config ({st})')

    _ga4_existing = find_googtag_by_id(service, acct_id, ctr_id, ga4_id)
    if _ga4_existing:
        log('·', 'Tag', f'GA4 - Configuration (existed as "{_ga4_existing}")')
    else:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_config_tag(ga4_id, ap_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Configuration ({st})')

    if has_scheduler:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_event_tag(ga4_id, appt_event, appt_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - {appt_event} ({st})')

    if 'autoops' in sched_key or 'steercrm' in sched_key:
        ao_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, autoops_all_events_trigger(), existing_triggers, fr)
        log('✓' if st != 'existed' else '·', 'Trigger', f'CE - AutoOps - All Events ({st})')
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_autoops_all_events_tag(ga4_id, ao_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - AutoOps Events ({st})')
        old_tag_name = 'GA4 - Event - ao-appointment-booked'
        if old_tag_name in existing_tags:
            old_tag_id = existing_tags[old_tag_name]
            try:
                _call(lambda: service.accounts().containers().workspaces().tags().delete(
                    path=f'accounts/{acct_id}/containers/{ctr_id}/workspaces/{ws_id}/tags/{old_tag_id}'
                ).execute())
                log('✓', 'Tag deleted', f'{old_tag_name} (superseded by AutoOps Events)')
            except Exception as e:
                log('!', 'Tag delete failed', f'{old_tag_name}: {e}')

    if 'shopmonkey' in sched_key:
        _, st = ensure_variable(service, acct_id, ctr_id, ws_id, shopmonkey_action_variable(), existing_variables, fr)
        log('✓' if st != 'existed' else '·', 'Variable', f'DLV - Shopmonkey Action ({st})')

    if 'tekmetric' in sched_key:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, tekmetric_listener_tag(ap_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'TekMetric - Booking - postMessage Listener ({st})')

    if has_phone:
        cl_tids = list(phone_to_tid.values())
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_event_tag(ga4_id, 'phone_click', cl_tids), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - phone_click ({st})')

    if has_scheduler:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, gads_appt_tag(store, gads_id, appt_label, appt_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GAds - {store} - Booked_Appointment ({st})')

    if has_phone:
        for p, l in phone_pairs:
            cl_tid = phone_to_tid[p]
            _, st = ensure_tag(service, acct_id, ctr_id, ws_id, gads_phone_tag(store, gads_id, p, l, cl_tid), existing_tags, fr)
            log('✓' if st != 'existed' else '·', 'Tag', f'GAds - {store} - Phone_Click - {p} ({st})')

    # ── AI Traffic Tracking ───────────────────────────────────────────────────

    enable_builtin_variable(service, acct_id, ctr_id, ws_id, 'clickUrl')
    enable_builtin_variable(service, acct_id, ctr_id, ws_id, 'clickText')
    log('✓', 'Built-in vars', 'Click URL, Click Text (ensured)')

    st = enable_builtin_variable(service, acct_id, ctr_id, ws_id, 'newHistoryFragment')
    log('✓' if st != 'existed' else '·', 'Built-in var', f'History New URL Fragment ({st})')

    _, st = ensure_variable(service, acct_id, ctr_id, ws_id, ai_referrer_variable(), existing_variables, fr)
    log('✓' if st != 'existed' else '·', 'Variable', f'JS - AI Referrer ({st})')

    tf_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, text_fragment_trigger(), existing_triggers, fr)
    log('✓' if st != 'existed' else '·', 'Trigger', f'HC - Text Fragment ({st})')

    ar_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, ai_referral_trigger(), existing_triggers, fr)
    log('✓' if st != 'existed' else '·', 'Trigger', f'PV - AI Referral ({st})')

    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_ai_overview_tag(ga4_id, tf_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - ai_overview_click ({st})')

    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_ai_referral_tag(ga4_id, ar_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - ai_referral ({st})')

    # ── CallRail DNI ──────────────────────────────────────────────────────────
    if has_callrail:
        print('\nFetching CallRail swap.js URL...')
        cr_script_url = None
        try:
            cr_script_url = fetch_callrail_script_url(cr_account_id, cr_company_id)
        except Exception as e:
            print(f'  [warn] CallRail API error: {e} — DNI tag skipped')
        if cr_script_url:
            print(f'  swap.js: {cr_script_url}')
            _, st = ensure_variable(service, acct_id, ctr_id, ws_id, callrail_variable(cr_company_id), existing_variables, fr)
            log('✓' if st != 'existed' else '·', 'Variable', f'C - CallRail Account ID ({st})')
            _, st = ensure_tag(service, acct_id, ctr_id, ws_id, callrail_dni_tag(cr_script_url, ap_tid), existing_tags, fr)
            log('✓' if st != 'existed' else '·', 'Tag', f'CallRail - DNI - Swap Script ({st})')
        else:
            print('  [warn] Could not parse swap.js URL from CallRail API — DNI tag skipped')

    # ── Lead Form Attribution ─────────────────────────────────────────────────
    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, attribution_store_tag(ap_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'LNM - Attribution - Store ({st})')

    for field in _ATTRIBUTION_FIELDS:
        _, st = ensure_variable(service, acct_id, ctr_id, ws_id, attribution_variable(field), existing_variables, fr)
        log('✓' if st != 'existed' else '·', 'Variable', f'JS - Attribution - {field} ({st})')

    cf7_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, cf7_form_trigger(), existing_triggers, fr)
    log('✓' if st != 'existed' else '·', 'Trigger', f'CE - CF7 - Form Submitted ({st})')

    wpf_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, wpforms_form_trigger(), existing_triggers, fr)
    log('✓' if st != 'existed' else '·', 'Trigger', f'CE - WPForms - Form Submitted ({st})')

    gfs_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, generic_form_trigger(), existing_triggers, fr)
    log('✓' if st != 'existed' else '·', 'Trigger', f'FS - Generic Form Submit ({st})')

    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_lead_tag(ga4_id, [cf7_tid, wpf_tid, gfs_tid]), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - generate_lead ({st})')

    # ── Social & Advertising Pixels ──────────────────────────────────────────

    # 1. Ensure Variables (Placeholders)
    pixels = [
        ('Meta Pixel ID', 'PLACEHOLDER'),
        ('TikTok Pixel ID', 'PLACEHOLDER'),
        ('LinkedIn Partner ID', 'PLACEHOLDER'),
        ('Microsoft UET ID', 'PLACEHOLDER')
    ]
    for name, val in pixels:
        _, st = ensure_variable(service, acct_id, ctr_id, ws_id, constant_variable(name, val), existing_variables, fr)
        log('✓' if st != 'existed' else '·', 'Variable', f'C - {name} ({st})')

    # 2. Base Tags
    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, meta_pixel_tag(ap_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'Meta - Pixel - Base ({st})')

    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, tiktok_pixel_tag(ap_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'TikTok - Pixel - Base ({st})')

    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, linkedin_insight_tag(ap_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'LinkedIn - Insight Tag - Base ({st})')

    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, microsoft_uet_tag(ap_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'Microsoft - UET - Base ({st})')

    if not has_overrides:
        print('\nUpdating Supabase gtm_container_status + IDs...')
        update_supabase_status(args.gads_cid,
                               location_id=args.location_id,
                               account_id=acct_id,
                               container_id=ctr_id)

    print('\nCreating and publishing GTM version...')
    try:
        version_id = create_and_publish_version(service, acct_id, ctr_id, ws_id, f'LNM Setup - {loc["name"]}')
        print(f'  ✓ Published version {version_id}')
    except Exception as e:
        print(f'  [warn] Auto-publish failed ({e}). Publish manually in GTM UI.')

    print('\nGranting LNM service account access...')
    grant_lnm_access(service, acct_id)

    print('\n=== Done ===')


if __name__ == '__main__':
    main()
