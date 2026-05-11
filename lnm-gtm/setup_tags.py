"""
setup_tags.py — Push LNM standard triggers + tags into a GTM container.
"""

import re
import os
import json
import time
import argparse
import requests
import random
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE   = os.path.join(SCRIPT_DIR, 'token.json')

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'http://127.0.0.1:54321')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']

SUPABASE_HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
}

# type: 'datalayer'    — scheduler fires a native dataLayer event
# type: 'postmessage'  — scheduler lives in an iframe, fires postMessage on booking complete
#                        listener tag pushes synthetic datalayer event so GA4/GAds tags fire normally
# type: 'click_link'   — scheduler opens in new tab via direct link; track the click as intent signal
SCHEDULER_MAP = {
    'autoops':    {'event': 'ao-appointment-booked',        'label': 'AutoOps',    'type': 'datalayer'},
    'shopgenie':  {'event': 'appointmentBooked',             'label': 'Shop Genie', 'type': 'datalayer'},
    'oktorocket': {'event': 'dc-service-booked',             'label': 'OktoRocket', 'type': 'datalayer'},
    # SteerCRM merged with AutoOps — their scheduler fires ao- events
    'steercrm':   {'event': 'ao-appointment-booked',         'label': 'AutoOps',    'type': 'datalayer'},
    # Tekmetric: iframe overlay at booking.tekmetric.com sends bookingTool:closeModal on completion
    'tekmetric':  {'event': 'tekmetric-appointment-booked',  'label': 'Tekmetric',  'type': 'postmessage',
                   'postmessage_listen': 'bookingTool:closeModal'},
    # Shopmonkey: direct link scheduler (URL TBD — update click_url_contains once known)
    'shopmonkey': {'event': 'shopmonkey-appointment-click',  'label': 'Shopmonkey', 'type': 'click_link',
                   'click_url_contains': 'shopmonkey'},
    # Protractor: direct link to appointment.protractor.com
    'protractor': {'event': 'protractor-appointment-click',  'label': 'Protractor', 'type': 'click_link',
                   'click_url_contains': 'appointment.protractor.com'},
}

def get_scheduler(scheduler_type):
    key = str(scheduler_type or '').lower().replace(' ', '').replace('-', '')
    for k, v in SCHEDULER_MAP.items():
        if k in key: return v
    return SCHEDULER_MAP['oktorocket']

def derive_store_name(client_name):
    SKIP = {'auto','automotive','repair','service','center','care','shop','tire','garage','motors','motor','llc','inc','and','&','the','of'}
    name = str(client_name or '').strip()
    if ' - ' in name:
        candidate = name.split(' - ')[-1].strip()
        if candidate: return candidate
    words = [w for w in name.split() if w.lower() not in SKIP]
    return ' '.join(words[:2]) if words else name

def clean_phone(raw):
    return re.sub(r'\D', '', str(raw or ''))

def log(icon, kind, name):
    print(f'  {icon} {kind}: {name}')

def _call(fn, retries=6):
    from googleapiclient.errors import HttpError
    for i in range(retries):
        try: return fn()
        except HttpError as e:
            if e.resp.status == 429 and i < retries - 1:
                wait = (2 ** i) + random.random()
                time.sleep(wait); continue
            raise

def _is_dup(e):
    from googleapiclient.errors import HttpError
    return isinstance(e, HttpError) and e.resp.status == 400 and b'duplicate' in (e.content or b'').lower()

def list_triggers(service, acct, ctr, ws):
    resp = _call(lambda: service.accounts().containers().workspaces().triggers().list(parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}').execute())
    return {t['name']: t['triggerId'] for t in resp.get('trigger', [])}

def ensure_trigger(service, acct, ctr, ws, body, existing, force):
    name = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    eid = existing.get(name)
    if eid:
        if not force: return eid, 'existed'
        res = _call(lambda: service.accounts().containers().workspaces().triggers().update(path=f'{parent}/triggers/{eid}', body=body).execute())
        return res['triggerId'], 'updated'
    try:
        res = _call(lambda: service.accounts().containers().workspaces().triggers().create(parent=parent, body=body).execute())
        return res['triggerId'], 'new'
    except Exception as e:
        if _is_dup(e):
            fresh = list_triggers(service, acct, ctr, ws)
            if name in fresh:
                res = _call(lambda: service.accounts().containers().workspaces().triggers().update(path=f'{parent}/triggers/{fresh[name]}', body=body).execute())
                return res['triggerId'], 'updated'
        raise

def list_tags(service, acct, ctr, ws):
    resp = _call(lambda: service.accounts().containers().workspaces().tags().list(parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}').execute())
    return {t['name']: t['tagId'] for t in resp.get('tag', [])}

def ensure_tag(service, acct, ctr, ws, body, existing, force):
    name = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    eid = existing.get(name)
    if eid:
        if not force: return eid, 'existed'
        res = _call(lambda: service.accounts().containers().workspaces().tags().update(path=f'{parent}/tags/{eid}', body=body).execute())
        return res['tagId'], 'updated'
    try:
        res = _call(lambda: service.accounts().containers().workspaces().tags().create(parent=parent, body=body).execute())
        return res['tagId'], 'new'
    except Exception as e:
        if _is_dup(e):
            fresh = list_tags(service, acct, ctr, ws)
            if name in fresh:
                res = _call(lambda: service.accounts().containers().workspaces().tags().update(path=f'{parent}/tags/{fresh[name]}', body=body).execute())
                return res['tagId'], 'updated'
        raise

def list_variables(service, acct, ctr, ws):
    resp = _call(lambda: service.accounts().containers().workspaces().variables().list(parent=f'accounts/{acct}/containers/{ctr}/workspaces/{ws}').execute())
    return {v['name']: v['variableId'] for v in resp.get('variable', [])}

def ensure_variable(service, acct, ctr, ws, body, existing, force):
    name = body['name']
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    eid = existing.get(name)
    if eid:
        if not force: return eid, 'existed'
        res = _call(lambda: service.accounts().containers().workspaces().variables().update(path=f'{parent}/variables/{eid}', body=body).execute())
        return res['variableId'], 'updated'
    try:
        res = _call(lambda: service.accounts().containers().workspaces().variables().create(parent=parent, body=body).execute())
        return res['variableId'], 'new'
    except Exception as e:
        if _is_dup(e):
            fresh = list_variables(service, acct, ctr, ws)
            if name in fresh:
                res = _call(lambda: service.accounts().containers().workspaces().variables().update(path=f'{parent}/variables/{fresh[name]}', body=body).execute())
                return res['variableId'], 'updated'
        raise

def enable_builtin_variable(service, acct, ctr, ws, var_type):
    parent = f'accounts/{acct}/containers/{ctr}/workspaces/{ws}'
    resp = _call(lambda: service.accounts().containers().workspaces().built_in_variables().list(parent=parent).execute())
    enabled = {v['type'] for v in resp.get('builtInVariable', [])}
    if var_type in enabled: return 'existed'
    try: _call(lambda: service.accounts().containers().workspaces().built_in_variables().create(parent=parent, type=[var_type]).execute())
    except: return 'failed'
    return 'new'

def ga4_config_tag(ga4_id, ap_tid):
    return {'name': 'GA4 - Configuration', 'type': 'gaawc', 'parameter': [{'type': 'TEMPLATE', 'key': 'measurementId', 'value': ga4_id}], 'firingTriggerId': [ap_tid]}

def ga4_event_tag(ga4_id, event_name, trigger_ids, tag_name=None):
    is_sg = event_name == 'appointmentBooked'
    ev = 'generate_lead' if is_sg else event_name
    body = {'name': tag_name or f'GA4 - Event - {ev}', 'type': 'gaawe', 'parameter': [{'type': 'TAG_REFERENCE', 'key': 'gaSettings', 'value': 'GA4 - Configuration'}, {'type': 'TEMPLATE', 'key': 'eventName', 'value': ev}, {'type': 'TEMPLATE', 'key': 'measurementIdOverride', 'value': ga4_id}], 'firingTriggerId': trigger_ids if isinstance(trigger_ids, list) else [trigger_ids]}
    if is_sg: body['parameter'].append({'type': 'LIST', 'key': 'eventParameters', 'list': [
        {'type': 'MAP', 'map': [{'type': 'TEMPLATE', 'key': 'name', 'value': 'method'}, {'type': 'TEMPLATE', 'key': 'value', 'value': 'shop_genie'}]}
    ]})
    return body

def gads_appt_tag(store, gads_id, label, trigger_id):
    return {'name': f'GAds - {store} - Booked_Appointment', 'type': 'awct', 'parameter': [{'type': 'INTEGER', 'key': 'conversionId', 'value': str(gads_id)}, {'type': 'TEMPLATE', 'key': 'conversionLabel', 'value': label}, {'type': 'TEMPLATE', 'key': 'conversionValue', 'value': '100'}, {'type': 'TEMPLATE', 'key': 'currencyCode', 'value': 'USD'}], 'firingTriggerId': [trigger_id]}

def gads_phone_tag(store, gads_id, phone, label, trigger_id):
    return {'name': f'GAds - {store} - Phone_Click - {phone}', 'type': 'awct', 'parameter': [{'type': 'INTEGER', 'key': 'conversionId', 'value': str(gads_id)}, {'type': 'TEMPLATE', 'key': 'conversionLabel', 'value': label}, {'type': 'TEMPLATE', 'key': 'conversionValue', 'value': '10'}, {'type': 'TEMPLATE', 'key': 'currencyCode', 'value': 'USD'}], 'firingTriggerId': [trigger_id]}

def meta_pixel_event_tag(pixel_id, event_name, trigger_id):
    html = f'<script>fbq("track", "{event_name}");</script>'
    return {'name': f'Meta Pixel - Event - {event_name}', 'type': 'html', 'parameter': [{'type': 'TEMPLATE', 'key': 'html', 'value': html}], 'firingTriggerId': [trigger_id]}

def tiktok_pixel_event_tag(pixel_id, event_name, trigger_id):
    html = f'<script>ttq.track("{event_name}");</script>'
    return {'name': f'TikTok Pixel - Event - {event_name}', 'type': 'html', 'parameter': [{'type': 'TEMPLATE', 'key': 'html', 'value': html}], 'firingTriggerId': [trigger_id]}

def linkedin_pixel_event_tag(pixel_id, event_name, trigger_id):
    html = f'<script>window.lintrk && window.lintrk("track", {{ conversion_id: {pixel_id} }});</script>'
    return {'name': f'LinkedIn Pixel - Event - Lead', 'type': 'html', 'parameter': [{'type': 'TEMPLATE', 'key': 'html', 'value': html}], 'firingTriggerId': [trigger_id]}

def ms_bing_pixel_event_tag(pixel_id, event_name, trigger_id):
    html = f'<script>window.uetq = window.uetq || []; window.uetq.push("event", "{event_name.lower()}", {{}});</script>'
    return {'name': f'MS Bing Pixel - Event - {event_name}', 'type': 'html', 'parameter': [{'type': 'TEMPLATE', 'key': 'html', 'value': html}], 'firingTriggerId': [trigger_id]}

def fetch_location(gads_cid, location_id=None):
    select = 'id,name,url,gtm_id,gtm_lnm_acct,gtm_account_id,gtm_container_id,ga4_measurement_id,gads_conversion_id,gads_appt_label,gads_phone_label,scheduler_type,phone_number,websites:websites!websites_location_id_fkey(pixel_meta,pixel_tiktok,pixel_linkedin,pixel_ms_bing,ga4_measurement_id)'
    params = {'id': f'eq.{location_id}'} if location_id else {'gads_cid': f'eq.{gads_cid}'}
    params['select'] = select
    r = requests.get(f'{SUPABASE_URL}/rest/v1/locations', params=params, headers=SUPABASE_HEADERS, timeout=10)
    r.raise_for_status()
    rows = r.json()
    if not rows: raise SystemExit('Location not found.')
    return rows[0]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--gads-cid', required=True)
    parser.add_argument('--location-id')
    parser.add_argument('--force-recreate', action='store_true')
    parser.add_argument('--token-file')
    args = parser.parse_args()

    loc = fetch_location(args.gads_cid, args.location_id)
    gtm_id = str(loc.get('gtm_id') or '').strip()
    ga4_id = str(loc.get('ga4_measurement_id') or '').strip()
    webs = loc.get('websites', [])
    if not ga4_id and webs: ga4_id = str(webs[0].get('ga4_measurement_id') or '').strip()
    
    raw_gads_id = loc.get('gads_conversion_id')
    gads_id = str(int(float(str(raw_gads_id)))) if raw_gads_id else ''
    if gads_id and len(gads_id) > 11:
        print(f'  [warn] gads_conversion_id={gads_id} has >11 digits and may be an internal GAds API ID rather than an AW conversion ID. Tags may not fire correctly.')
    store = derive_store_name(loc['name'])
    phone = clean_phone(loc.get('phone_number'))
    phone_lbl = str(loc.get('gads_phone_label') or '').strip()
    appt_label = str(loc.get('gads_appt_label') or '').strip()
    sched = get_scheduler(loc.get('scheduler_type')) if loc.get('scheduler_type') else None
    appt_event  = sched['event']              if sched else None
    sched_label = sched['label']              if sched else None
    sched_type  = sched.get('type', 'datalayer') if sched else None

    print(f'\n=== LNM GTM Setup: {gtm_id} ({loc["name"]}) ===')
    
    token_file = args.token_file
    if not token_file:
        acct_email = str(loc.get('gtm_lnm_acct') or '').lower().strip()
        if 'analytics2' in acct_email: token_file = os.path.join(SCRIPT_DIR, 'token_analytics2.json')
        elif 'reports' in acct_email:   token_file = os.path.join(SCRIPT_DIR, 'token_reports.json')
        elif 'analytics' in acct_email: token_file = os.path.join(SCRIPT_DIR, 'token_analytics.json')
        else: token_file = os.path.join(SCRIPT_DIR, 'token.json')

    print(f'  Using token: {os.path.basename(token_file)}')
    
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    with open(token_file) as f: data = json.load(f)
    creds = Credentials(**{k: v for k, v in data.items() if k in ['token','refresh_token','token_uri','client_id','client_secret','scopes']})
    service = build('tagmanager', 'v2', credentials=creds)

    acct_id, ctr_id = loc.get('gtm_account_id'), loc.get('gtm_container_id')
    if not acct_id or not ctr_id:
        accounts = _call(lambda: service.accounts().list().execute()).get('account', [])
        for a in accounts:
            conts = _call(lambda: service.accounts().containers().list(parent=a['path']).execute()).get('container', [])
            for c in conts:
                if c.get('publicId') == gtm_id:
                    acct_id, ctr_id = a['accountId'], c['containerId']; break
            if acct_id: break
    if not acct_id: raise SystemExit('Container not found.')
    
    resp_ws = _call(lambda: service.accounts().containers().workspaces().list(parent=f'accounts/{acct_id}/containers/{ctr_id}').execute())
    ws_id = resp_ws.get('workspace', [{'workspaceId': '1'}])[0]['workspaceId']
    
    existing_triggers = list_triggers(service, acct_id, ctr_id, ws_id)
    existing_tags = list_tags(service, acct_id, ctr_id, ws_id)
    existing_vars = list_variables(service, acct_id, ctr_id, ws_id)
    fr = args.force_recreate

    # 1. Variables
    for h in ['historySource', 'newHistoryFragment', 'oldHistoryFragment']: enable_builtin_variable(service, acct_id, ctr_id, ws_id, h)
    for v in ['clickUrl', 'clickText']: enable_builtin_variable(service, acct_id, ctr_id, ws_id, v)
    
    ensure_variable(service, acct_id, ctr_id, ws_id, {'name': 'JS - New Fragment', 'type': 'jsm', 'parameter': [{'type': 'TEMPLATE', 'key': 'javascript', 'value': 'function() { return window.location.hash || ""; }'}]}, existing_vars, fr)
    ensure_variable(service, acct_id, ctr_id, ws_id, {'name': 'JS - AI Referrer', 'type': 'jsm', 'parameter': [{'type': 'TEMPLATE', 'key': 'javascript', 'value': 'function() { var r = document.referrer || ""; var s = ["perplexity.ai","chatgpt.com","openai.com","gemini.google.com","copilot.microsoft.com","claude.ai"]; for (var i = 0; i < s.length; i++) { if (r.indexOf(s[i]) !== -1) return s[i]; } return ""; }'}]}, existing_vars, fr)

    # 2. Triggers
    ap_tid, _ = ensure_trigger(service, acct_id, ctr_id, ws_id, {'name': 'All Pages', 'type': 'PAGEVIEW'}, existing_triggers, fr)
    appt_tid = None
    is_ao = False
    if appt_event and sched_type:
        if sched_type == 'datalayer':
            is_ao = appt_event.startswith('ao-')
            appt_filter = {'type': 'MATCH_REGEX', 'parameter': [{'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{_event}}'}, {'type': 'TEMPLATE', 'key': 'arg1', 'value': '^ao-'}]} if is_ao else {'type': 'EQUALS', 'parameter': [{'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{_event}}'}, {'type': 'TEMPLATE', 'key': 'arg1', 'value': appt_event}]}
            appt_tid, _ = ensure_trigger(service, acct_id, ctr_id, ws_id, {'name': f'CE - {sched_label} - Appointment Booked', 'type': 'CUSTOM_EVENT', 'customEventFilter': [appt_filter]}, existing_triggers, fr)

        elif sched_type == 'postmessage':
            # Listener Custom HTML tag fires on All Pages, pushes synthetic datalayer event when iframe posts its completion message
            pm_listen = sched.get('postmessage_listen', '')
            listener_js = (
                f'<script>(function(){{'
                f'if(window.__lnmPmListener_{sched_label.replace(" ","")}__)return;'
                f'window.__lnmPmListener_{sched_label.replace(" ","")}__=true;'
                f'window.addEventListener("message",function(e){{'
                f'if(e.data==="{pm_listen}"){{'
                f'window.dataLayer=window.dataLayer||[];'
                f'window.dataLayer.push({{event:"{appt_event}"}});'
                f'}}}});'
                f'}})();</script>'
            )
            ensure_tag(service, acct_id, ctr_id, ws_id, {'name': f'LNM - {sched_label} Booking Listener', 'type': 'html', 'parameter': [{'type': 'TEMPLATE', 'key': 'html', 'value': listener_js}], 'firingTriggerId': [ap_tid]}, existing_tags, fr)
            appt_tid, _ = ensure_trigger(service, acct_id, ctr_id, ws_id, {'name': f'CE - {sched_label} - Appointment Booked', 'type': 'CUSTOM_EVENT', 'customEventFilter': [{'type': 'EQUALS', 'parameter': [{'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{_event}}'}, {'type': 'TEMPLATE', 'key': 'arg1', 'value': appt_event}]}]}, existing_triggers, fr)

        elif sched_type == 'click_link':
            click_url = sched.get('click_url_contains', '')
            enable_builtin_variable(service, acct_id, ctr_id, ws_id, 'clickUrl')
            appt_tid, _ = ensure_trigger(service, acct_id, ctr_id, ws_id, {'name': f'CL - {sched_label} - Appointment Link', 'type': 'LINK_CLICK', 'filter': [{'type': 'CONTAINS', 'parameter': [{'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{Click URL}}'}, {'type': 'TEMPLATE', 'key': 'arg1', 'value': click_url}]}]}, existing_triggers, fr)
    cl_tid = None
    if phone:
        cl_tid, _ = ensure_trigger(service, acct_id, ctr_id, ws_id, {'name': f'CL - Phone Click - {phone}', 'type': 'LINK_CLICK', 'filter': [{'type': 'CONTAINS', 'parameter': [{'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{Click URL}}'}, {'type': 'TEMPLATE', 'key': 'arg1', 'value': phone}]}]}, existing_triggers, fr)
    tf_tid, _ = ensure_trigger(service, acct_id, ctr_id, ws_id, {'name': 'HC - Text Fragment', 'type': 'HISTORY_CHANGE', 'filter': [{'type': 'CONTAINS', 'parameter': [{'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{JS - New Fragment}}'}, {'type': 'TEMPLATE', 'key': 'arg1', 'value': ':~:text='}]}]}, existing_triggers, fr)
    ar_tid, _ = ensure_trigger(service, acct_id, ctr_id, ws_id, {'name': 'PV - AI Referral', 'type': 'PAGEVIEW', 'filter': [{'type': 'MATCH_REGEX', 'parameter': [{'type': 'TEMPLATE', 'key': 'arg0', 'value': '{{JS - AI Referrer}}'}, {'type': 'TEMPLATE', 'key': 'arg1', 'value': '.+'}]}]}, existing_triggers, fr)

    # 3. Tags
    ensure_tag(service, acct_id, ctr_id, ws_id, {'name': 'Conversion Linker', 'type': 'gclidw', 'firingTriggerId': [ap_tid]}, existing_tags, fr)
    if gads_id:
        ensure_tag(service, acct_id, ctr_id, ws_id, {'name': 'Google Tag - AW Config', 'type': 'googtag', 'parameter': [{'type': 'TEMPLATE', 'key': 'tagId', 'value': f'AW-{gads_id}'}], 'firingTriggerId': [ap_tid]}, existing_tags, fr)
        if appt_tid and appt_label: ensure_tag(service, acct_id, ctr_id, ws_id, gads_appt_tag(store, gads_id, appt_label, appt_tid), existing_tags, fr)
        if cl_tid and phone_lbl: ensure_tag(service, acct_id, ctr_id, ws_id, gads_phone_tag(store, gads_id, phone, phone_lbl, cl_tid), existing_tags, fr)
    
    if ga4_id:
        ensure_tag(service, acct_id, ctr_id, ws_id, ga4_config_tag(ga4_id, ap_tid), existing_tags, fr)
        if appt_tid:
            if is_ao:
                ga4_tag = ga4_event_tag(ga4_id, '{{_event}}', appt_tid, tag_name='GA4 - Event - AutoOps Events')
            elif sched_type == 'click_link':
                ga4_tag = ga4_event_tag(ga4_id, 'appointment_click', appt_tid, tag_name=f'GA4 - Event - {sched_label} Appointment Click')
            else:
                ga4_tag = ga4_event_tag(ga4_id, appt_event, appt_tid)
            ensure_tag(service, acct_id, ctr_id, ws_id, ga4_tag, existing_tags, fr)
        ensure_tag(service, acct_id, ctr_id, ws_id, {'name': 'GA4 - Event - ai_overview_click', 'type': 'gaawe', 'parameter': [{'type': 'TAG_REFERENCE', 'key': 'gaSettings', 'value': 'GA4 - Configuration'}, {'type': 'TEMPLATE', 'key': 'eventName', 'value': 'ai_overview_click'}, {'type': 'TEMPLATE', 'key': 'measurementIdOverride', 'value': ga4_id}], 'firingTriggerId': [tf_tid]}, existing_tags, fr)
        ensure_tag(service, acct_id, ctr_id, ws_id, {'name': 'GA4 - Event - ai_referral', 'type': 'gaawe', 'parameter': [{'type': 'TAG_REFERENCE', 'key': 'gaSettings', 'value': 'GA4 - Configuration'}, {'type': 'TEMPLATE', 'key': 'eventName', 'value': 'ai_referral'}, {'type': 'TEMPLATE', 'key': 'measurementIdOverride', 'value': ga4_id}, {'type': 'LIST', 'key': 'eventParameters', 'list': [{'type': 'MAP', 'map': [{'type': 'TEMPLATE', 'key': 'name', 'value': 'ai_source'}, {'type': 'TEMPLATE', 'key': 'value', 'value': '{{JS - AI Referrer}}'}]}]}], 'firingTriggerId': [ar_tid]}, existing_tags, fr)

    # Pixels
    if webs and appt_tid:
        w = webs[0]
        if w.get('pixel_meta'): ensure_tag(service, acct_id, ctr_id, ws_id, meta_pixel_event_tag(w['pixel_meta'], 'Schedule', appt_tid), existing_tags, fr)
        if w.get('pixel_tiktok'): ensure_tag(service, acct_id, ctr_id, ws_id, tiktok_pixel_event_tag(w['pixel_tiktok'], 'CompleteRegistration', appt_tid), existing_tags, fr)
        if w.get('pixel_linkedin'): ensure_tag(service, acct_id, ctr_id, ws_id, linkedin_pixel_event_tag(w['pixel_linkedin'], 'Lead', appt_tid), existing_tags, fr)
        if w.get('pixel_ms_bing'): ensure_tag(service, acct_id, ctr_id, ws_id, ms_bing_pixel_event_tag(w['pixel_ms_bing'], 'Submit_Lead_Form', appt_tid), existing_tags, fr)

    # Publish
    try:
        res = _call(lambda: service.accounts().containers().workspaces().create_version(path=f'accounts/{acct_id}/containers/{ctr_id}/workspaces/{ws_id}', body={'name': f'LNM Setup - {time.strftime("%Y-%m-%d %H:%M")}'}).execute())
        v_path = res.get('containerVersion', {}).get('path')
        if v_path: 
            _call(lambda: service.accounts().containers().versions().publish(path=v_path).execute())
            print('\n✓ Published LIVE!')
    except Exception as e: 
        print(f'\n[warn] GTM Publish skipped: {e}')
    
    time.sleep(30) # Heavy mandatory pause between accounts

if __name__ == '__main__':
    main()
