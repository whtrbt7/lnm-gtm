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
TOKEN_FILE   = os.path.join(SCRIPT_DIR, 'token.json')  # overridden by --token-file
CACHE_FILE   = os.path.join(SCRIPT_DIR, 'gtm_id_cache.json')

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']

SUPABASE_HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
}


# ── Supabase ──────────────────────────────────────────────────────────────────

def fetch_location(gads_cid):
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={
            'gads_cid': f'eq.{gads_cid}',
            'select': 'id,name,url,gtm_id,gtm_account_id,gtm_container_id,ga4_measurement_id,gads_conversion_id,gads_appt_label,gads_phone_label,scheduler_type,phone_number',
        },
        headers=SUPABASE_HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise SystemExit(f'No location found for GAds CID {gads_cid}')
    return rows[0]


def update_supabase_status(gads_cid):
    r = requests.patch(
        f'{SUPABASE_URL}/rest/v1/locations',
        params={'gads_cid': f'eq.{gads_cid}'},
        headers={**SUPABASE_HEADERS, 'Prefer': 'return=representation'},
        json={'gtm_container_status': 'has_container'},
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

    for idx, acct in enumerate(accounts, 1):
        if idx % 50 == 0:
            print(f'  Scanning {idx}/{len(accounts)}...')
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
        except Exception as e:
            print(f'  [warn] account {acct.get("accountId")}: {e}')
        time.sleep(0.5)

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


def ensure_trigger(service, acct, ctr, ws, body, existing, force_recreate):
    name   = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    if name in existing:
        if not force_recreate:
            return existing[name], 'existed'
        _call(lambda: service.accounts().containers().workspaces().triggers().delete(
            path=f'{parent}/triggers/{existing[name]}'
        ).execute())
    result = _call(lambda: service.accounts().containers().workspaces().triggers().create(
        parent=parent, body={k: v for k, v in body.items() if k not in ('accountId','containerId','triggerId')}
    ).execute())
    return result['triggerId'], ('recreated' if name in existing else 'new')


def ensure_tag(service, acct, ctr, ws, body, existing, force_recreate):
    name   = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    if name in existing:
        if not force_recreate:
            return existing[name], 'existed'
        _call(lambda: service.accounts().containers().workspaces().tags().delete(
            path=f'{parent}/tags/{existing[name]}'
        ).execute())
    result = _call(lambda: service.accounts().containers().workspaces().tags().create(
        parent=parent, body={k: v for k, v in body.items() if k not in ('accountId','containerId','tagId')}
    ).execute())
    return result['tagId'], ('recreated' if name in existing else 'new')


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
        _call(lambda: service.accounts().containers().workspaces().variables().delete(
            path=f'{parent}/variables/{existing[name]}'
        ).execute())
    result = _call(lambda: service.accounts().containers().workspaces().variables().create(
        parent=parent,
        body={k: v for k, v in body.items() if k not in ('accountId', 'containerId', 'variableId')}
    ).execute())
    return result['variableId'], ('recreated' if name in existing else 'new')


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
            {'type': 'TEMPLATE', 'key': 'conversionId', 'value': f'AW-{gads_id}'},
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
            {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{History New URL Fragment}}'},
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


def ga4_ai_overview_tag(trigger_id):
    return {
        'name': 'GA4 - Event - ai_overview_click',
        'type': 'gaawe',
        'parameter': [
            {'type': 'TAG_REFERENCE', 'key': 'gaSettings', 'value': 'GA4 - Configuration'},
            {'type': 'TEMPLATE',      'key': 'eventName',  'value': 'ai_overview_click'},
        ],
        'firingTriggerId': [trigger_id],
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


def ga4_ai_referral_tag(trigger_id):
    return {
        'name': 'GA4 - Event - ai_referral',
        'type': 'gaawe',
        'parameter': [
            {'type': 'TAG_REFERENCE', 'key': 'gaSettings', 'value': 'GA4 - Configuration'},
            {'type': 'TEMPLATE',      'key': 'eventName',  'value': 'ai_referral'},
            {'type': 'LIST',          'key': 'eventParameters', 'list': [
                {'type': 'MAP', 'map': [
                    {'type': 'TEMPLATE', 'key': 'name',  'value': 'ai_source'},
                    {'type': 'TEMPLATE', 'key': 'value', 'value': '{{JS - AI Referrer}}'},
                ]},
            ]},
        ],
        'firingTriggerId': [trigger_id],
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

SCHEDULER_MAP = {
    'autoops':    ('ao-appointment-booked', 'AutoOps'),
    'shopgenie':  ('appointment_booked',    'Shop Genie'),
    'oktorocket': ('dc-service-booked',     'OktoRocket'),
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
    parser.add_argument('--scheduler',         default=None, help='Scheduler: autoops | shopgenie | oktorocket')
    parser.add_argument('--name',              default=None, help='Client name (for store tag derivation)')
    parser.add_argument('--account-id',        default=None, help='GTM account ID — bypasses full account scan, seeds cache')
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
        loc = fetch_location(args.gads_cid)

        required = ['gtm_id', 'ga4_measurement_id', 'gads_conversion_id', 'gads_appt_label', 'scheduler_type']
        missing  = [f for f in required if not loc.get(f)]
        if missing:
            raise SystemExit(f'Missing required fields in Supabase: {", ".join(missing)}\n'
                             f'Pass them as CLI flags (--gtm-id, --ga4-id, --gads-conversion-id,\n'
                             f'--appt-label, --scheduler, --name) to bypass Supabase.')

    gtm_id     = str(loc['gtm_id']).strip()
    ga4_id     = str(loc['ga4_measurement_id']).strip()
    gads_id    = str(int(float(str(loc['gads_conversion_id']))))
    appt_label = str(loc['gads_appt_label']).strip()
    phone_lbl  = str(loc.get('gads_phone_label') or '').strip()
    phone      = clean_phone(loc.get('phone_number', ''))
    has_phone  = bool(phone and phone_lbl)

    appt_event, sched_label = get_scheduler(loc['scheduler_type'])
    store = derive_store_name(loc['name'])

    print(f'\n=== LNM GTM Setup: {gtm_id} ===')
    print(f'  Client    : {loc["name"]}')
    print(f'  Store tag : {store}')
    print(f'  GA4       : {ga4_id!r}')  # repr shows invisible chars
    print(f'  GAds ID   : {gads_id}')
    print(f'  Scheduler : {sched_label} (event={appt_event})')
    print(f'  Appt label: {appt_label}')
    if has_phone:
        print(f'  Phone     : {phone}  label={phone_lbl}')
    else:
        print(f'  Phone     : (none)')

    if args.dry_run:
        print('\n[DRY RUN] Would create:')
        print(f'  Trigger: CE - {sched_label} - Appointment Booked')
        if has_phone:
            print(f'  Trigger: CL - Phone Click - {phone}')
        print(f'  Trigger: All Pages')
        print(f'  Tag: Conversion Linker')
        print(f'  Tag: Google Tag - AW Config')
        print(f'  Tag: GA4 - Configuration')
        print(f'  Tag: GA4 - Event - {appt_event}')
        if has_phone:
            print(f'  Tag: GA4 - Event - phone_click')
        print(f'  Tag: GAds - {store} - Booked_Appointment')
        if has_phone:
            print(f'  Tag: GAds - {store} - Phone_Click - {phone}')
        print(f'  Variable: JS - AI Referrer')
        print(f'  Trigger: HC - Text Fragment')
        print(f'  Trigger: PV - AI Referral')
        print(f'  Tag: GA4 - Event - ai_overview_click')
        print(f'  Tag: GA4 - Event - ai_referral')
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

    print(f'\nWorkspace: {ws_id} | existing triggers: {len(existing_triggers)}, tags: {len(existing_tags)}, variables: {len(existing_variables)}\n')

    fr = args.force_recreate

    # Triggers
    appt_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, appt_trigger(sched_label, appt_event), existing_triggers, fr)
    log('✓' if st != 'existed' else '·', 'Trigger', f'CE - {sched_label} - Appointment Booked ({st})')

    cl_tid = None
    if has_phone:
        cl_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, phone_trigger(phone), existing_triggers, fr)
        log('✓' if st != 'existed' else '·', 'Trigger', f'CL - Phone Click - {phone} ({st})')

    ap_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, all_pages_trigger(), existing_triggers, fr)
    log('✓' if st != 'existed' else '·', 'Trigger', f'All Pages ({st})')

    # Tags
    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, conversion_linker_tag(ap_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'Conversion Linker ({st})')

    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, google_base_tag(gads_id, ap_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'Google Tag - AW Config ({st})')

    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_config_tag(ga4_id, ap_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Configuration ({st})')

    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_event_tag(ga4_id, appt_event, appt_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - {appt_event} ({st})')

    if has_phone:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_event_tag(ga4_id, 'phone_click', [cl_tid]), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - phone_click ({st})')

    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, gads_appt_tag(store, gads_id, appt_label, appt_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'GAds - {store} - Booked_Appointment ({st})')

    if has_phone:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, gads_phone_tag(store, gads_id, phone, phone_lbl, cl_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GAds - {store} - Phone_Click - {phone} ({st})')

    # ── AI Traffic Tracking ───────────────────────────────────────────────────

    st = enable_builtin_variable(service, acct_id, ctr_id, ws_id, 'HISTORY_NEW_URL_FRAGMENT')
    log('✓' if st != 'existed' else '·', 'Built-in var', f'History New URL Fragment ({st})')

    _, st = ensure_variable(service, acct_id, ctr_id, ws_id, ai_referrer_variable(), existing_variables, fr)
    log('✓' if st != 'existed' else '·', 'Variable', f'JS - AI Referrer ({st})')

    tf_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, text_fragment_trigger(), existing_triggers, fr)
    log('✓' if st != 'existed' else '·', 'Trigger', f'HC - Text Fragment ({st})')

    ar_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, ai_referral_trigger(), existing_triggers, fr)
    log('✓' if st != 'existed' else '·', 'Trigger', f'PV - AI Referral ({st})')

    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_ai_overview_tag(tf_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - ai_overview_click ({st})')

    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_ai_referral_tag(ar_tid), existing_tags, fr)
    log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - ai_referral ({st})')

    if not has_overrides:
        print('\nUpdating Supabase gtm_container_status = configured...')
        update_supabase_status(args.gads_cid)

    print('\n=== Done ===')


if __name__ == '__main__':
    main()
