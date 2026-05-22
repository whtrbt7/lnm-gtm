"""
setup_new_account.py — LNM Standard v1.0

Sets up all standard tags and triggers for a single new GTM account
without requiring the XLSX spreadsheet.

Usage (required args):
    python setup_new_account.py \
        --gtm-id   GTM-ABC1234 \
        --name     "Parker Automotive" \
        --ga4-id   G-XXXXXXXXXX \
        --gads-id  123456789 \
        --appt-label  abc123XYZ \
        --scheduler   oktorocket

Optional:
    --phone  5551234567 labelABC   (repeat for each number/label pair)
    --phone  5559876543 labelXYZ
    --token-file   token_alex.json  (default: token.json)
    --dry-run                       (preview without making API calls)
    --force-recreate                (delete and replace existing items)

Each --phone creates:
  - Its own CL trigger: CL - Phone Click - {number}
  - Its own GAds tag:   GAds - {store} - Phone_Click - {number}
The GA4 phone_click tag fires across all phone triggers combined.

Scheduler values: oktorocket (default) | shopgenie | autoops
"""

import re
import os
import sys
import json
import time
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH  = os.path.join(SCRIPT_DIR, 'token.json')


# ── Auth ──────────────────────────────────────────────────────────────────────

def get_gtm_service(token_path=None):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    path = token_path or TOKEN_PATH
    with open(path) as f:
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
            print('  [auth] Refreshing expired token...')
            creds.refresh(Request())
            data['token'] = creds.token
            data['expiry'] = creds.expiry.isoformat() if creds.expiry else None
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        else:
            raise RuntimeError('Credentials invalid and cannot be refreshed. Re-authenticate.')

    return build('tagmanager', 'v2', credentials=creds)


# ── API helpers ───────────────────────────────────────────────────────────────

def _api_call_with_retry(call, max_retries=8, base_delay=3.0):
    from googleapiclient.errors import HttpError
    delay = base_delay
    for attempt in range(max_retries):
        try:
            return call()
        except HttpError as e:
            status = e.resp.status
            if status in (429, 500, 503) and attempt < max_retries - 1:
                print(f'  [retry] HTTP {status}, waiting {delay:.1f}s...')
                time.sleep(delay)
                delay = min(delay * 2, 60)
            else:
                raise


# ── Container lookup ──────────────────────────────────────────────────────────

def find_container_by_gtm_id(service, gtm_public_id):
    """
    Scan all accessible GTM accounts to find the container matching gtm_public_id.
    Returns (account_id, container_id, public_id) or raises if not found.
    """
    gtm_public_id = gtm_public_id.strip().upper()
    print(f'Searching for container {gtm_public_id} across all accounts...')

    accounts_resp = _api_call_with_retry(lambda: service.accounts().list().execute())
    accounts = accounts_resp.get('account', [])
    print(f'  Found {len(accounts)} GTM account(s) — scanning...')

    for idx, acct in enumerate(accounts, 1):
        acct_path = acct['path']
        acct_id   = acct['accountId']

        if idx % 20 == 0:
            print(f'  Scanning account {idx}/{len(accounts)}...')

        ctrs_resp = _api_call_with_retry(
            lambda p=acct_path: service.accounts().containers().list(parent=p).execute()
        )
        for ctr in ctrs_resp.get('container', []):
            if ctr.get('publicId', '').upper() == gtm_public_id:
                print(f'  Found: account={acct_id}, container={ctr["containerId"]}')
                return acct_id, ctr['containerId'], ctr['publicId']

        time.sleep(0.5)

    raise RuntimeError(f'Container {gtm_public_id} not found in any accessible GTM account.')


LNM_SERVICE_ACCOUNTS = [
    'reports@leadsnearme.com',
    'analytics@leadsnearme.com',
    'analytics2@leadsnearme.com',
]

def grant_lnm_access(service, acct: str):
    """Ensure all 3 LNM service accounts have admin+publish on every container in acct."""
    containers = _api_call_with_retry(lambda: service.accounts().containers().list(
        parent=f'accounts/{acct}'
    ).execute()).get('container', [])

    existing_perms = _api_call_with_retry(lambda: service.accounts().user_permissions().list(
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
                _api_call_with_retry(lambda: service.accounts().user_permissions().update(
                    path=existing['path'], body=desired,
                ).execute())
            else:
                _api_call_with_retry(lambda: service.accounts().user_permissions().create(
                    parent=f'accounts/{acct}', body=desired,
                ).execute())
            print(f'  ✓ Granted admin+publish → {email}')
        except Exception as e:
            print(f'  [warn] Permission grant failed for {email}: {e}')


# ── Workspace ─────────────────────────────────────────────────────────────────

def get_workspace(service, account_id, container_id):
    parent = f'accounts/{account_id}/containers/{container_id}'
    resp = _api_call_with_retry(
        lambda: service.accounts().containers().workspaces().list(parent=parent).execute()
    )
    workspaces = resp.get('workspace', [])
    if not workspaces:
        raise RuntimeError(f'No workspaces found for container {parent}')
    return workspaces[0]['workspaceId']


# ── Idempotent create helpers ─────────────────────────────────────────────────

def get_existing_triggers(service, acct, ctr, ws):
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    resp = _api_call_with_retry(
        lambda: service.accounts().containers().workspaces().triggers().list(
            parent=parent).execute()
    )
    return {t['name']: t['triggerId'] for t in resp.get('trigger', [])}


def get_existing_tags(service, acct, ctr, ws):
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    resp = _api_call_with_retry(
        lambda: service.accounts().containers().workspaces().tags().list(
            parent=parent).execute()
    )
    return {t['name']: t['tagId'] for t in resp.get('tag', [])}


def ensure_trigger(service, acct, ctr, ws, body, existing, force_recreate=False):
    name   = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'

    if name in existing:
        if not force_recreate:
            return existing[name], 'existed'
        tid = existing[name]
        _api_call_with_retry(
            lambda p=f'{parent}/triggers/{tid}':
                service.accounts().containers().workspaces().triggers().delete(path=p).execute()
        )

    clean = {k: v for k, v in body.items() if k not in ('accountId', 'containerId', 'triggerId')}
    result = _api_call_with_retry(
        lambda: service.accounts().containers().workspaces().triggers().create(
            parent=parent, body=clean).execute()
    )
    status = 'recreated' if name in existing else 'new'
    return result['triggerId'], status


def ensure_tag(service, acct, ctr, ws, body, existing, force_recreate=False):
    name   = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'

    if name in existing:
        if not force_recreate:
            return existing[name], 'existed'
        tid = existing[name]
        _api_call_with_retry(
            lambda p=f'{parent}/tags/{tid}':
                service.accounts().containers().workspaces().tags().delete(path=p).execute()
        )

    clean = {k: v for k, v in body.items() if k not in ('accountId', 'containerId', 'tagId')}
    result = _api_call_with_retry(
        lambda: service.accounts().containers().workspaces().tags().create(
            parent=parent, body=clean).execute()
    )
    status = 'recreated' if name in existing else 'new'
    return result['tagId'], status


def get_existing_variables(service, acct, ctr, ws):
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    resp = _api_call_with_retry(
        lambda: service.accounts().containers().workspaces().variables().list(
            parent=parent).execute()
    )
    return {v['name']: v['variableId'] for v in resp.get('variable', [])}


def ensure_variable(service, acct, ctr, ws, body, existing, force_recreate=False):
    name   = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'

    if name in existing:
        if not force_recreate:
            return existing[name], 'existed'
        vid = existing[name]
        _api_call_with_retry(
            lambda p=f'{parent}/variables/{vid}':
                service.accounts().containers().workspaces().variables().delete(path=p).execute()
        )

    clean = {k: v for k, v in body.items() if k not in ('accountId', 'containerId', 'variableId')}
    result = _api_call_with_retry(
        lambda: service.accounts().containers().workspaces().variables().create(
            parent=parent, body=clean).execute()
    )
    return result['variableId'], ('recreated' if name in existing else 'new')


def enable_builtin_variable(service, acct, ctr, ws, var_type):
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    resp = _api_call_with_retry(
        lambda: service.accounts().containers().workspaces().built_in_variables().list(
            parent=parent).execute()
    )
    enabled = {v['type'] for v in resp.get('builtInVariable', [])}
    if var_type in enabled:
        return 'existed'
    _api_call_with_retry(
        lambda: service.accounts().containers().workspaces().built_in_variables().create(
            parent=parent, type=[var_type]).execute()
    )
    return 'new'


# ── Trigger / Tag body builders ───────────────────────────────────────────────

def build_appt_trigger(sched_label, appt_event):
    return {
        'name': f'CE - {sched_label} - Appointment Booked',
        'type': 'CUSTOM_EVENT',
        'customEventFilter': [{
            'type': 'EQUALS',
            'parameter': [
                {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{_event}}'},
                {'type': 'TEMPLATE', 'key': 'arg1', 'value': appt_event},
            ]
        }]
    }


def build_cl_trigger(phone):
    return {
        'name': f'CL - Phone Click - {phone}',
        'type': 'LINK_CLICK',
        'filter': [{
            'type': 'CONTAINS',
            'parameter': [
                {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{Click URL}}'},
                {'type': 'TEMPLATE', 'key': 'arg1', 'value': phone},
            ]
        }],
        'parameter': [
            {'type': 'BOOLEAN',  'key': 'waitForTags',       'value': 'true'},
            {'type': 'BOOLEAN',  'key': 'checkValidation',   'value': 'true'},
            {'type': 'TEMPLATE', 'key': 'waitForTagsTimeout', 'value': '2000'},
        ]
    }


def build_all_pages_trigger():
    return {'name': 'All Pages', 'type': 'PAGEVIEW'}


def build_ga4_config_tag(ga4_id, all_pages_trigger_id):
    return {
        'name': 'GA4 - Configuration',
        'type': 'gaawc',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'measurementId', 'value': ga4_id}
        ],
        'firingTriggerId': [all_pages_trigger_id],
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


def build_ga4_event_appt_tag(ga4_id, appt_event, appt_trigger_id):
    return {
        'name': f'GA4 - Event - {appt_event}',
        'type': 'gaawe',
        'parameter': [
            {'type': 'TAG_REFERENCE', 'key': 'gaSettings', 'value': 'GA4 - Configuration'},
            {'type': 'TEMPLATE',      'key': 'eventName',  'value': appt_event},
        ],
        'firingTriggerId': [appt_trigger_id],
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


def build_ga4_event_phone_tag(ga4_id, cl_trigger_ids):
    return {
        'name': 'GA4 - Event - phone_click',
        'type': 'gaawe',
        'parameter': [
            {'type': 'TAG_REFERENCE', 'key': 'gaSettings', 'value': 'GA4 - Configuration'},
            {'type': 'TEMPLATE',      'key': 'eventName',  'value': 'phone_click'},
        ],
        'firingTriggerId': cl_trigger_ids,
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


def build_gads_appt_tag(store_name, gads_id_str, appt_label, appt_trigger_id):
    return {
        'name': f'GAds - {store_name} - Booked_Appointment',
        'type': 'awct',
        'parameter': [
            {'type': 'INTEGER',  'key': 'conversionId',    'value': gads_id_str},
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


def build_gads_phone_tag(store_name, gads_id_str, phone, phone_label, cl_trigger_id):
    """One GAds Phone_Click tag per phone number, firing on that number's CL trigger."""
    return {
        'name': f'GAds - {store_name} - Phone_Click - {phone}',
        'type': 'awct',
        'parameter': [
            {'type': 'INTEGER',  'key': 'conversionId',    'value': gads_id_str},
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


def build_conversion_linker_tag(all_pages_trigger_id):
    return {
        'name': 'Conversion Linker',
        'type': 'gclidw',
        'parameter': [
            {'type': 'BOOLEAN', 'key': 'enableCrossDomainLinking', 'value': 'false'},
            {'type': 'BOOLEAN', 'key': 'enableUrlPassthrough',     'value': 'false'},
            {'type': 'BOOLEAN', 'key': 'decorateFormsWithData',    'value': 'false'},
        ],
        'firingTriggerId': [all_pages_trigger_id],
        'tagFiringOption': 'ONCE_PER_LOAD',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


def build_google_base_tag(gads_id, all_pages_trigger_id):
    return {
        'name': 'Google Tag - AW Config',
        'type': 'googtag',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'conversionId', 'value': f'AW-{gads_id}'},
        ],
        'firingTriggerId': [all_pages_trigger_id],
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


def build_ai_referrer_variable():
    return {
        'name': 'JS - AI Referrer',
        'type': 'jsm',
        'parameter': [{'type': 'TEMPLATE', 'key': 'javascript', 'value': _AI_REFERRER_JS}],
    }


def build_text_fragment_trigger():
    return {
        'name': 'HC - Text Fragment',
        'type': 'HISTORY_CHANGE',
        'filter': [{'type': 'CONTAINS', 'parameter': [
            {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{History New URL Fragment}}'},
            {'type': 'TEMPLATE', 'key': 'arg1', 'value': ':~:text='},
        ]}],
    }


def build_ai_referral_trigger():
    return {
        'name': 'PV - AI Referral',
        'type': 'PAGEVIEW',
        'filter': [{'type': 'MATCH_REGEX', 'parameter': [
            {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{JS - AI Referrer}}'},
            {'type': 'TEMPLATE', 'key': 'arg1', 'value': '.+'},
        ]}],
    }


def build_ga4_ai_overview_tag(trigger_id):
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


def build_ga4_ai_referral_tag(trigger_id):
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

def get_scheduler_info(scheduler_type):
    s = str(scheduler_type or '').lower().replace(' ', '')
    if 'shopgenie' in s:
        return 'appointment_booked', 'Shop Genie'
    if 'autoops' in s:
        return 'ao-appointment-booked', 'AutoOps'
    return 'dc-service-booked', 'OktoRocket'


def normalize_phone(raw):
    return re.sub(r'\D', '', str(raw or ''))


def derive_store_name(client_name):
    """Derive a short store label from the client name for use in tag names."""
    SKIP = {'auto', 'automotive', 'repair', 'service', 'center', 'care', 'shop',
            'tire', 'garage', 'motors', 'motor', 'llc', 'inc', 'and', '&', 'the',
            '1', 'of', 'at', 'in', 'for'}
    name = str(client_name or '').strip()

    if ' - ' in name:
        candidate = name.split(' - ')[-1].strip()
        if candidate:
            return candidate

    words = [w for w in name.split() if w.lower() not in SKIP]
    return ' '.join(words[:2]) if words else name


# ── Main ──────────────────────────────────────────────────────────────────────

def run(gtm_id, client_name, ga4_id, gads_id, appt_label,
        scheduler, phone_pairs,
        token_file=None, dry_run=False, force_recreate=False):
    """
    phone_pairs: list of (number, label) tuples, e.g. [('5551234567', 'abc123'), ...]
    """
    # Normalise phone numbers and drop blanks
    phone_pairs = [(normalize_phone(num), lbl)
                   for num, lbl in (phone_pairs or [])
                   if normalize_phone(num) and lbl]
    has_phone  = bool(phone_pairs)
    store_name = derive_store_name(client_name)
    appt_event, sched_label = get_scheduler_info(scheduler)
    gads_id_str = str(int(float(str(gads_id))))

    print(f'\n=== LNM GTM Setup: {gtm_id} ===')
    print(f'  Client    : {client_name}')
    print(f'  Store name: {store_name}')
    print(f'  GA4 ID    : {ga4_id}')
    print(f'  GAds ID   : {gads_id_str}')
    print(f'  Scheduler : {sched_label} (event={appt_event})')
    print(f'  Appt label: {appt_label}')
    if has_phone:
        for num, lbl in phone_pairs:
            print(f'  Phone     : {num}  label={lbl}')
    else:
        print(f'  Phones    : (none)')

    if dry_run:
        print('\n[DRY RUN] Would create:')
        print(f'  Trigger : CE - {sched_label} - Appointment Booked')
        for num, _ in phone_pairs:
            print(f'  Trigger : CL - Phone Click - {num}')
        print(f'  Trigger : All Pages')
        print(f'  Tag     : Conversion Linker')
        print(f'  Tag     : Google Tag - AW Config')
        print(f'  Tag     : GA4 - Configuration')
        print(f'  Tag     : GA4 - Event - {appt_event}')
        if has_phone:
            print(f'  Tag     : GA4 - Event - phone_click  (fires on all {len(phone_pairs)} CL trigger(s))')
        print(f'  Tag     : GAds - {store_name} - Booked_Appointment')
        for num, lbl in phone_pairs:
            print(f'  Tag     : GAds - {store_name} - Phone_Click - {num}  (label={lbl})')
        print(f'  Variable: JS - AI Referrer')
        print(f'  Trigger : HC - Text Fragment')
        print(f'  Trigger : PV - AI Referral')
        print(f'  Tag     : GA4 - Event - ai_overview_click')
        print(f'  Tag     : GA4 - Event - ai_referral')
        print('\n[DRY RUN] No changes made.')
        return

    # Connect to GTM API
    token_path = os.path.join(SCRIPT_DIR, token_file) if token_file else None
    service = get_gtm_service(token_path)

    # Find container
    acct_id, ctr_id, public_id = find_container_by_gtm_id(service, gtm_id)

    # Get workspace
    ws_id = get_workspace(service, acct_id, ctr_id)
    print(f'\nWorkspace ID: {ws_id}')

    # Load existing items (idempotency)
    existing_triggers  = get_existing_triggers(service, acct_id, ctr_id, ws_id)
    existing_tags      = get_existing_tags(service, acct_id, ctr_id, ws_id)
    existing_variables = get_existing_variables(service, acct_id, ctr_id, ws_id)
    print(f'Existing: {len(existing_triggers)} trigger(s), {len(existing_tags)} tag(s), {len(existing_variables)} variable(s)\n')

    def _t(label, name, status):
        icon = '✓' if status != 'existed' else '·'
        print(f'  {icon} {label}: {name} ({status})')

    # ── Triggers ──────────────────────────────────────────────────────────────

    # 1. Appointment Custom Event trigger
    body = build_appt_trigger(sched_label, appt_event)
    appt_trigger_id, st = ensure_trigger(service, acct_id, ctr_id, ws_id, body, existing_triggers, force_recreate)
    _t('Trigger', body['name'], st)

    # 2. Phone click triggers (one per number)
    cl_trigger_ids = []   # all CL trigger IDs — used by the combined GA4 tag
    phone_trigger_map = []  # [(phone, label, trigger_id), ...]
    for num, lbl in phone_pairs:
        body = build_cl_trigger(num)
        tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, body, existing_triggers, force_recreate)
        cl_trigger_ids.append(tid)
        phone_trigger_map.append((num, lbl, tid))
        _t('Trigger', body['name'], st)

    # 3. All Pages trigger
    body = build_all_pages_trigger()
    all_pages_id, st = ensure_trigger(service, acct_id, ctr_id, ws_id, body, existing_triggers, force_recreate)
    _t('Trigger', body['name'], st)

    # ── Tags ──────────────────────────────────────────────────────────────────

    # Conversion Linker — must exist before any GAds tag fires
    body = build_conversion_linker_tag(all_pages_id)
    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, body, existing_tags, force_recreate)
    _t('Tag', body['name'], st)

    # Google Tag — establishes AW account-level connection
    body = build_google_base_tag(gads_id_str, all_pages_id)
    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, body, existing_tags, force_recreate)
    _t('Tag', body['name'], st)

    # GA4 Configuration
    body = build_ga4_config_tag(ga4_id, all_pages_id)
    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, body, existing_tags, force_recreate)
    _t('Tag', body['name'], st)

    # GA4 Event — appointment booked
    body = build_ga4_event_appt_tag(ga4_id, appt_event, appt_trigger_id)
    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, body, existing_tags, force_recreate)
    _t('Tag', body['name'], st)

    # GA4 Event — phone_click
    if has_phone:
        body = build_ga4_event_phone_tag(ga4_id, cl_trigger_ids)
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, body, existing_tags, force_recreate)
        _t('Tag', body['name'], st)

    # Google Ads — Booked_Appointment
    body = build_gads_appt_tag(store_name, gads_id_str, appt_label, appt_trigger_id)
    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, body, existing_tags, force_recreate)
    _t('Tag', body['name'], st)

    # Google Ads — Phone_Click (one tag per phone number)
    for num, lbl, tid in phone_trigger_map:
        body = build_gads_phone_tag(store_name, gads_id_str, num, lbl, tid)
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, body, existing_tags, force_recreate)
        _t('Tag', body['name'], st)

    # ── AI Traffic Tracking ───────────────────────────────────────────────────

    st = enable_builtin_variable(service, acct_id, ctr_id, ws_id, 'HISTORY_NEW_URL_FRAGMENT')
    _t('Built-in var', 'History New URL Fragment', st)

    for v in ['clickUrl', 'clickText']:
        st = enable_builtin_variable(service, acct_id, ctr_id, ws_id, v)
        _t('Built-in var', v, st)

    body = build_ai_referrer_variable()
    _, st = ensure_variable(service, acct_id, ctr_id, ws_id, body, existing_variables, force_recreate)
    _t('Variable', body['name'], st)

    body = build_text_fragment_trigger()
    tf_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, body, existing_triggers, force_recreate)
    _t('Trigger', body['name'], st)

    body = build_ai_referral_trigger()
    ar_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, body, existing_triggers, force_recreate)
    _t('Trigger', body['name'], st)

    body = build_ga4_ai_overview_tag(tf_tid)
    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, body, existing_tags, force_recreate)
    _t('Tag', body['name'], st)

    body = build_ga4_ai_referral_tag(ar_tid)
    _, st = ensure_tag(service, acct_id, ctr_id, ws_id, body, existing_tags, force_recreate)
    _t('Tag', body['name'], st)

    print('\nGranting LNM service account access...')
    grant_lnm_access(service, acct_id)

    print('\n=== Done ===')


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Set up LNM standard tags/triggers for a single GTM account.'
    )

    # Required
    parser.add_argument('--gtm-id',      required=True, help='GTM Container public ID, e.g. GTM-ABC1234')
    parser.add_argument('--name',        required=True, help='Client/store name, e.g. "Parker Automotive"')
    parser.add_argument('--ga4-id',      required=True, help='GA4 Measurement ID, e.g. G-XXXXXXXXXX')
    parser.add_argument('--gads-id',     required=True, help='Google Ads Conversion ID (integer)')
    parser.add_argument('--appt-label',  required=True, help='Google Ads appointment booking conversion label')
    parser.add_argument('--scheduler',   required=True,
                        choices=['oktorocket', 'shopgenie', 'autoops'],
                        help='Scheduler type: oktorocket | shopgenie | autoops')

    # Optional — repeat --phone for each number/label pair
    parser.add_argument('--phone',        nargs=2, metavar=('NUMBER', 'LABEL'),
                        action='append', default=[],
                        help='Phone number and its GAds conversion label. Repeat for each phone. '
                             'e.g. --phone 5551234567 abc123XYZ --phone 5559876543 def456ABC')
    parser.add_argument('--token-file',   default=None, help='Token file (default: token.json), e.g. token_alex.json')
    parser.add_argument('--dry-run',      action='store_true', help='Preview without making API calls')
    parser.add_argument('--force-recreate', action='store_true', help='Delete and replace existing tags/triggers')

    args = parser.parse_args()

    run(
        gtm_id        = args.gtm_id,
        client_name   = args.name,
        ga4_id        = args.ga4_id,
        gads_id       = args.gads_id,
        appt_label    = args.appt_label,
        scheduler     = args.scheduler,
        phone_pairs   = [tuple(p) for p in args.phone],
        token_file    = args.token_file,
        dry_run       = args.dry_run,
        force_recreate= args.force_recreate,
    )
