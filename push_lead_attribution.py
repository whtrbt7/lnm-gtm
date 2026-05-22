"""
push_lead_attribution.py — Bulk-add lead form attribution tags to all LNM GTM containers.

For each location that has gtm_id + gtm_account_id + gtm_container_id:
  1. Ensure 'LNM - Attribution - Store' Custom HTML tag exists (All Pages)
  2. Ensure JS variables for utm_source, utm_medium, utm_campaign, gclid
  3. Ensure CF7, WPForms, and generic form triggers
  4. Ensure 'GA4 - Event - generate_lead' tag firing on all 3 form triggers
  5. Skip locations where all items already exist (idempotent)

Results saved to push_lead_attribution_results.json (resumable).

Usage:
  python push_lead_attribution.py               # run all eligible
  python push_lead_attribution.py --dry-run     # preview only
  python push_lead_attribution.py --limit 10    # process first N
  python push_lead_attribution.py --reset       # clear results and re-run all
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

GTM_TOKEN_MAP = {
    'analytics@leadsnearme.com':  SCRIPT_DIR / 'token_analytics.json',
    'analytics2@leadsnearme.com': SCRIPT_DIR / 'token_analytics2.json',
    'reports@leadsnearme.com':    SCRIPT_DIR / 'token_reports.json',
}
GTM_TOKEN_DEFAULT = SCRIPT_DIR / 'token_analytics.json'

RESULTS_FILE = SCRIPT_DIR / 'push_lead_attribution_results.json'

# ── Supabase ──────────────────────────────────────────────────────────────────

def fetch_eligible_locations() -> list[dict]:
    params = {
        'select':           'id,name,gtm_id,gtm_account_id,gtm_container_id,gtm_lnm_acct,ga4_measurement_id',
        'gtm_id':           'not.is.null',
        'gtm_account_id':   'not.is.null',
        'gtm_container_id': 'not.is.null',
        'ga4_measurement_id': 'not.is.null',
        'limit':            '1000',
    }
    r = requests.get(f'{SUPABASE_URL}/rest/v1/locations', params=params, headers=SB_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


# ── GTM helpers ───────────────────────────────────────────────────────────────

def get_gtm_service(token_file: Path):
    sys.path.insert(0, str(SCRIPT_DIR))
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


def list_tags(service, acct, ctr, ws) -> dict[str, str]:
    resp = _call(lambda: service.accounts().containers().workspaces().tags().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())
    return {t['name']: t['tagId'] for t in resp.get('tag', [])}


def list_variables(service, acct, ctr, ws) -> dict[str, str]:
    resp = _call(lambda: service.accounts().containers().workspaces().variables().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())
    return {v['name']: v['variableId'] for v in resp.get('variable', [])}


def list_triggers(service, acct, ctr, ws) -> dict[str, str]:
    resp = _call(lambda: service.accounts().containers().workspaces().triggers().list(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    ).execute())
    return {t['name']: t['triggerId'] for t in resp.get('trigger', [])}


def ensure_variable(service, acct, ctr, ws, body, existing) -> tuple[str, str]:
    name   = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    if name in existing:
        return existing[name], 'existed'
    result = _call(lambda: service.accounts().containers().workspaces().variables().create(
        parent=parent,
        body={k: v for k, v in body.items() if k not in ('accountId', 'containerId', 'variableId')}
    ).execute())
    return result['variableId'], 'new'


def ensure_trigger(service, acct, ctr, ws, body, existing) -> tuple[str, str]:
    name   = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    if name in existing:
        return existing[name], 'existed'
    result = _call(lambda: service.accounts().containers().workspaces().triggers().create(
        parent=parent,
        body={k: v for k, v in body.items() if k not in ('accountId', 'containerId', 'triggerId')}
    ).execute())
    return result['triggerId'], 'new'


def ensure_tag(service, acct, ctr, ws, body, existing) -> tuple[str, str]:
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
    result = _call(lambda: service.accounts().containers().workspaces().triggers().create(
        parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}',
        body={'name': 'All Pages', 'type': 'PAGEVIEW'},
    ).execute())
    return result['triggerId']


# ── Tag / trigger / variable bodies (mirrors setup_tags.py) ──────────────────

_ATTRIBUTION_FIELDS = ['utm_source', 'utm_medium', 'utm_campaign', 'gclid']

_ATTRIBUTION_STORE_HTML = (
    '<script>\n'
    '(function() {\n'
    "  if (document.cookie.indexOf('lnm_attribution=') !== -1) return;\n"
    '  var p = new URLSearchParams(window.location.search);\n'
    '  var a = {};\n'
    "  ['utm_source','utm_medium','utm_campaign','gclid','msclkid'].forEach(function(k) {\n"
    '    if (p.get(k)) a[k] = p.get(k);\n'
    '  });\n'
    '  if (Object.keys(a).length) {\n'
    "    document.cookie = 'lnm_attribution=' + encodeURIComponent(JSON.stringify(a)) + ';path=/;max-age=2592000;SameSite=Lax';\n"
    '  }\n'
    '})();\n'
    '</script>'
)


def attribution_store_tag_body(all_pages_id: str) -> dict:
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


def attribution_variable_body(field: str) -> dict:
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


def cf7_trigger_body() -> dict:
    return {
        'name': 'CE - CF7 - Form Submitted',
        'type': 'CUSTOM_EVENT',
        'customEventFilter': [{'type': 'EQUALS', 'parameter': [
            {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{_event}}'},
            {'type': 'TEMPLATE', 'key': 'arg1', 'value': 'wpcf7mailsent'},
        ]}],
    }


def wpforms_trigger_body() -> dict:
    return {
        'name': 'CE - WPForms - Form Submitted',
        'type': 'CUSTOM_EVENT',
        'customEventFilter': [{'type': 'EQUALS', 'parameter': [
            {'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{_event}}'},
            {'type': 'TEMPLATE', 'key': 'arg1', 'value': 'wpforms_successful_submit'},
        ]}],
    }


def generic_form_trigger_body() -> dict:
    return {
        'name': 'FS - Generic Form Submit',
        'type': 'FORM_SUBMISSION',
        'parameter': [
            {'type': 'BOOLEAN',  'key': 'waitForTags',        'value': 'true'},
            {'type': 'BOOLEAN',  'key': 'checkValidation',    'value': 'false'},
            {'type': 'TEMPLATE', 'key': 'waitForTagsTimeout', 'value': '2000'},
        ],
    }


def ga4_lead_tag_body(ga4_id: str, trigger_ids: list[str]) -> dict:
    return {
        'name': 'GA4 - Event - generate_lead',
        'type': 'gaawe',
        'parameter': [
            {'type': 'TAG_REFERENCE', 'key': 'gaSettings',            'value': 'GA4 - Configuration'},
            {'type': 'TEMPLATE',      'key': 'measurementIdOverride', 'value': ga4_id},
            {'type': 'TEMPLATE',      'key': 'eventName',             'value': 'generate_lead'},
            {'type': 'LIST', 'key': 'eventParameters', 'list': [
                {'type': 'MAP', 'map': [
                    {'type': 'TEMPLATE', 'key': 'name',  'value': f},
                    {'type': 'TEMPLATE', 'key': 'value', 'value': '{{JS - Attribution - %s}}' % f},
                ]}
                for f in _ATTRIBUTION_FIELDS
            ]},
        ],
        'firingTriggerId': trigger_ids,
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit',   type=int, default=0)
    parser.add_argument('--reset',   action='store_true')
    args = parser.parse_args()

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

    by_token: dict[str, list[dict]] = {}
    for loc in locations:
        acct_email = (loc.get('gtm_lnm_acct') or '').lower().strip()
        token_file = GTM_TOKEN_MAP.get(acct_email, GTM_TOKEN_DEFAULT)
        by_token.setdefault(str(token_file), []).append(loc)

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
            loc_id  = loc['id']
            name    = loc['name']
            gtm_id  = loc['gtm_id']
            acct_id = loc['gtm_account_id']
            ctr_id  = loc['gtm_container_id']
            ga4_id  = str(loc.get('ga4_measurement_id') or '').strip()

            prev = results.get(loc_id, {})
            if prev.get('status') in ('done', 'existed'):
                skipped += 1
                continue

            print(f'\n[{i}/{len(locs)}] {name} ({gtm_id})')

            if args.dry_run:
                print(f'  [DRY RUN] would add lead attribution to {gtm_id}')
                results[loc_id] = {'status': 'dry_run', 'name': name, 'gtm_id': gtm_id}
                done += 1
                continue

            if not ga4_id:
                print(f'  [skip] no ga4_measurement_id')
                results[loc_id] = {'status': 'error', 'name': name, 'gtm_id': gtm_id, 'error': 'no ga4_measurement_id'}
                failed += 1
                RESULTS_FILE.write_text(json.dumps(results, indent=2))
                continue

            try:
                ws_id = get_workspace(service, acct_id, ctr_id)

                existing_tags  = list_tags(service, acct_id, ctr_id, ws_id)
                existing_vars  = list_variables(service, acct_id, ctr_id, ws_id)
                existing_trigs = list_triggers(service, acct_id, ctr_id, ws_id)

                # Check if all items already present
                lead_tag_name  = 'GA4 - Event - generate_lead'
                store_tag_name = 'LNM - Attribution - Store'
                all_present = (
                    lead_tag_name in existing_tags
                    and store_tag_name in existing_tags
                    and all(f'JS - Attribution - {f}' in existing_vars for f in _ATTRIBUTION_FIELDS)
                    and 'CE - CF7 - Form Submitted' in existing_trigs
                    and 'CE - WPForms - Form Submitted' in existing_trigs
                    and 'FS - Generic Form Submit' in existing_trigs
                )
                if all_present:
                    print(f'  · all attribution items already exist — skipping')
                    results[loc_id] = {'status': 'existed', 'name': name, 'gtm_id': gtm_id}
                    skipped += 1
                    RESULTS_FILE.write_text(json.dumps(results, indent=2))
                    continue

                ap_tid = get_all_pages_trigger_id(existing_trigs, service, acct_id, ctr_id, ws_id)

                _, st = ensure_tag(service, acct_id, ctr_id, ws_id, attribution_store_tag_body(ap_tid), existing_tags)
                print(f'  {"✓" if st == "new" else "·"} Tag: LNM - Attribution - Store ({st})')

                for field in _ATTRIBUTION_FIELDS:
                    _, st = ensure_variable(service, acct_id, ctr_id, ws_id, attribution_variable_body(field), existing_vars)
                    print(f'  {"✓" if st == "new" else "·"} Variable: JS - Attribution - {field} ({st})')
                    existing_vars[f'JS - Attribution - {field}'] = _  # update local state

                cf7_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, cf7_trigger_body(), existing_trigs)
                print(f'  {"✓" if st == "new" else "·"} Trigger: CE - CF7 - Form Submitted ({st})')

                wpf_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, wpforms_trigger_body(), existing_trigs)
                print(f'  {"✓" if st == "new" else "·"} Trigger: CE - WPForms - Form Submitted ({st})')

                gfs_tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, generic_form_trigger_body(), existing_trigs)
                print(f'  {"✓" if st == "new" else "·"} Trigger: FS - Generic Form Submit ({st})')

                _, lead_st = ensure_tag(service, acct_id, ctr_id, ws_id,
                                       ga4_lead_tag_body(ga4_id, [cf7_tid, wpf_tid, gfs_tid]), existing_tags)
                print(f'  {"✓" if lead_st == "new" else "·"} Tag: GA4 - Event - generate_lead ({lead_st})')

                try:
                    ver = create_and_publish_version(service, acct_id, ctr_id, ws_id, f'LNM - Lead Attribution - {name}')
                    print(f'  ✓ Published version {ver}')
                except Exception as pub_e:
                    print(f'  [warn] publish failed: {pub_e}')

                results[loc_id] = {'status': 'done', 'name': name, 'gtm_id': gtm_id}
                done += 1

            except Exception as e:
                print(f'  [error] {e}')
                results[loc_id] = {'status': 'error', 'name': name, 'gtm_id': gtm_id, 'error': str(e)}
                failed += 1

            RESULTS_FILE.write_text(json.dumps(results, indent=2))
            time.sleep(0.3)

    print(f'\n══ Done ══')
    print(f'  Added/confirmed : {done}')
    print(f'  Already existed : {skipped}')
    print(f'  Errors          : {failed}')
    print(f'  Results file    : {RESULTS_FILE}')


if __name__ == '__main__':
    main()
