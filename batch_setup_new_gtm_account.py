"""
Batch-apply LNM standard GTM template to all containers in "LNM New GTM" account.
Reads container IDs from batch_new_containers_progress.json.
Fetches ga4_id, gads_cid, labels, phone, scheduler from Supabase by campaign_id.
Calls setup_new_account building blocks directly (no full-account scan).

Usage:
  python batch_setup_new_gtm_account.py
  python batch_setup_new_gtm_account.py --dry-run
  python batch_setup_new_gtm_account.py --publish
"""
import os, sys, re, json, time, argparse, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from setup_new_account import (
    get_gtm_service,
    get_workspace,
    get_existing_triggers, get_existing_tags, get_existing_variables,
    ensure_trigger, ensure_tag, ensure_variable,
    enable_builtin_variable,
    build_all_pages_trigger, build_appt_trigger, build_cl_trigger,
    build_conversion_linker_tag, build_google_base_tag,
    build_ga4_config_tag, build_ga4_event_appt_tag, build_ga4_event_phone_tag,
    build_gads_appt_tag, build_gads_phone_tag,
    build_ai_referrer_variable, build_text_fragment_trigger,
    build_ai_referral_trigger, build_ga4_ai_overview_tag, build_ga4_ai_referral_tag,
    _api_call_with_retry, normalize_phone, derive_store_name, get_scheduler_info,
)

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
PROGRESS_FILE = os.path.join(SCRIPT_DIR, 'batch_new_containers_progress.json')
SETUP_LOG     = os.path.join(SCRIPT_DIR, 'batch_setup_new_gtm_progress.json')
TOKEN_FILE    = os.path.join(SCRIPT_DIR, 'token_developer.json')

SUPA_URL = 'https://supabase.alexanderchiu.com'
SUPA_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyAgCiAgICAicm9sZSI6ICJzZXJ2aWNlX3JvbGUiLAogICAgImlzcyI6ICJzdXBhYmFzZS1kZW1vIiwKICAgICJpYXQiOiAxNjQxNzY5MjAwLAogICAgImV4cCI6IDE3OTk1MzU2MDAKfQ.DaYlNEoUrrEn2Ig7tqibS-PHK5vgusbcbo7X36XVt4Q'
SUPA_H   = {'apikey': SUPA_KEY, 'Authorization': f'Bearer {SUPA_KEY}'}

SCHEDULER_MAP = {
    'shopgenie':  'shopgenie',
    'shop genie': 'shopgenie',
    'autoops':    'autoops',
    'auto ops':   'autoops',
}

def map_scheduler(raw):
    k = (raw or '').lower().strip()
    return SCHEDULER_MAP.get(k, 'oktorocket')


def fetch_location_data(campaign_id):
    r = requests.get(f'{SUPA_URL}/rest/v1/locations',
        params={
            'campaign_id': f'eq.{campaign_id}',
            'deleted_at': 'is.null',
            'select': 'id,name,gads_cid,gads_conversion_id,ga4_measurement_id,ga4_id,'
                      'gads_appt_label,gads_phone_label,phone_number,scheduler_type',
            'limit': 1,
        }, headers=SUPA_H, timeout=10)
    rows = r.json()
    if not rows:
        return None
    loc = rows[0]
    # Fetch correct Conversion ID from gads_conversions (distinct from Customer ID)
    cr = requests.get(f'{SUPA_URL}/rest/v1/gads_conversions',
        params={'location_id': f'eq.{loc["id"]}', 'select': 'conversion_id',
                'conversion_id': 'not.is.null', 'limit': 1},
        headers=SUPA_H, timeout=10)
    cr.raise_for_status()
    conv_rows = cr.json()
    if conv_rows and conv_rows[0].get('conversion_id'):
        loc['_conv_id'] = str(conv_rows[0]['conversion_id'])
    return loc


def setup_container(service, acct_id, ctr_id, container_id, loc, name, dry_run=False):
    """Apply LNM template to a single container using known account/container IDs."""
    ga4_id     = loc.get('ga4_measurement_id') or loc.get('ga4_id') or ''
    # gads_cid = Customer ID (for AW base tag config only)
    # conv_id  = actual Conversion ID from gads_conversions (for awct conversion tags)
    gads_cid   = str(loc.get('gads_cid') or '').replace('-', '').strip()
    conv_id    = str(loc.get('_conv_id') or loc.get('gads_conversion_id') or gads_cid).strip()
    appt_label = loc.get('gads_appt_label') or ''
    phone_raw  = normalize_phone(loc.get('phone_number') or '')
    phone_lbl  = loc.get('gads_phone_label') or ''
    scheduler  = map_scheduler(loc.get('scheduler_type'))

    appt_event, sched_label = get_scheduler_info(scheduler)
    store_name = derive_store_name(name)
    has_phone  = bool(phone_raw and phone_lbl)
    phone_pairs = [(phone_raw, phone_lbl)] if has_phone else []

    if dry_run:
        print(f'  ga4={ga4_id} gads_cid={gads_cid} conv_id={conv_id} appt_label={appt_label}')
        print(f'  phone={phone_raw} phone_lbl={phone_lbl} scheduler={scheduler}')
        return True

    if not conv_id:
        print(f'  SKIP: no conversion ID available')
        return False
    if not appt_label:
        print(f'  WARN: no appt_label — appointment tags will be created but label empty')

    ws_id = get_workspace(service, acct_id, ctr_id)

    existing_triggers  = get_existing_triggers(service, acct_id, ctr_id, ws_id)
    existing_tags      = get_existing_tags(service, acct_id, ctr_id, ws_id)
    existing_variables = get_existing_variables(service, acct_id, ctr_id, ws_id)

    def et(label, body, existing):
        tid, st = ensure_trigger(service, acct_id, ctr_id, ws_id, body, existing)
        icon = '✓' if st != 'existed' else '·'
        print(f'    {icon} Trigger: {body["name"]} ({st})')
        return tid

    def etag(label, body, existing):
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, body, existing)
        icon = '✓' if st != 'existed' else '·'
        print(f'    {icon} Tag: {body["name"]} ({st})')

    # Triggers
    appt_tid   = et('appt',      build_appt_trigger(sched_label, appt_event), existing_triggers)
    all_pages  = et('allpages',  build_all_pages_trigger(),                    existing_triggers)
    cl_tids    = []
    for num, lbl in phone_pairs:
        tid = et('phone', build_cl_trigger(num), existing_triggers)
        cl_tids.append(tid)

    # Tags
    etag('linker',   build_conversion_linker_tag(all_pages),           existing_tags)
    etag('googtag',  build_google_base_tag(conv_id, all_pages),        existing_tags)

    if ga4_id:
        etag('ga4cfg', build_ga4_config_tag(ga4_id, all_pages),            existing_tags)
        etag('ga4appt', build_ga4_event_appt_tag(ga4_id, appt_event, appt_tid), existing_tags)
        if cl_tids:
            etag('ga4phone', build_ga4_event_phone_tag(ga4_id, cl_tids),   existing_tags)
    else:
        print(f'    ! No GA4 ID — skipping GA4 tags')

    if appt_label:
        etag('gadsappt', build_gads_appt_tag(store_name, conv_id, appt_label, appt_tid), existing_tags)
    for num, lbl, tid in [(p[0], p[1], cl_tids[i]) for i, p in enumerate(phone_pairs)]:
        etag('gadsphone', build_gads_phone_tag(store_name, conv_id, num, lbl, tid), existing_tags)

    # AI tracking
    enable_builtin_variable(service, acct_id, ctr_id, ws_id, 'newHistoryFragment')
    for v in ['clickUrl', 'clickText']:
        enable_builtin_variable(service, acct_id, ctr_id, ws_id, v)
    body = build_ai_referrer_variable()
    ensure_variable(service, acct_id, ctr_id, ws_id, body, existing_variables)
    print(f'    ✓ Variable: JS - AI Referrer')

    tf_tid = et('textfrag',  build_text_fragment_trigger(),  existing_triggers)
    ar_tid = et('aireferral', build_ai_referral_trigger(),   existing_triggers)
    if ga4_id:
        etag('aiov', build_ga4_ai_overview_tag(tf_tid, ga4_id), existing_tags)
        etag('airef', build_ga4_ai_referral_tag(ar_tid, ga4_id), existing_tags)

    return True


def publish_container(service, acct_id, ctr_id, name):
    ws_id = get_workspace(service, acct_id, ctr_id)
    ws_path = f'accounts/{acct_id}/containers/{ctr_id}/workspaces/{ws_id}'
    try:
        version = _api_call_with_retry(lambda: service.accounts().containers().workspaces().create_version(
            path=ws_path, body={'name': 'LNM Standard Setup v1'}
        ).execute())
        ver_path = version.get('containerVersion', {}).get('path', '')
        if not ver_path:
            print(f'    ! No version path returned for {name}')
            return False
        _api_call_with_retry(lambda: service.accounts().containers().versions().publish(
            path=ver_path
        ).execute())
        print(f'    ✓ Published')
        return True
    except Exception as e:
        print(f'    ! Publish failed: {e}')
        return False


def load_setup_log():
    if os.path.exists(SETUP_LOG):
        with open(SETUP_LOG) as f:
            return json.load(f)
    return {}


def save_setup_log(log):
    with open(SETUP_LOG, 'w') as f:
        json.dump(log, f, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run',  action='store_true')
    parser.add_argument('--publish',  action='store_true', help='Publish each container after setup')
    args = parser.parse_args()

    with open(PROGRESS_FILE) as f:
        progress = json.load(f)

    setup_log = load_setup_log()
    service = None if args.dry_run else get_gtm_service(TOKEN_FILE)

    items = list(progress['done_urls'].items())
    print(f'Containers to set up: {len(items)} | Already done: {len(setup_log)}')

    success = failed = skipped = 0

    for url, data in items:
        gtm_id      = data['gtm_id']
        acct_id     = data['account_id']
        ctr_id      = data['container_id']
        campaign_ids = data['campaigns']

        if url in setup_log and setup_log[url].get('setup_done'):
            skipped += 1
            continue

        # Use first campaign_id to get location data
        loc = fetch_location_data(campaign_ids[0])
        name = loc['name'] if loc else url

        print(f'\n[{url}] {name} | {gtm_id}')

        if not loc:
            print(f'  ! No Supabase row for campaign {campaign_ids[0]} — skipping')
            failed += 1
            continue

        try:
            ok = setup_container(service, acct_id, ctr_id, ctr_id, loc, name, dry_run=args.dry_run)
            if ok and not args.dry_run:
                if args.publish:
                    publish_container(service, acct_id, ctr_id, name)
                setup_log[url] = {'gtm_id': gtm_id, 'setup_done': True}
                save_setup_log(setup_log)
                success += 1
            elif args.dry_run:
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f'  FAILED: {e}')
            failed += 1

        if not args.dry_run:
            time.sleep(1)

    print(f'\n=== Done: {success} set up, {skipped} already done, {failed} failed ===')


if __name__ == '__main__':
    main()
