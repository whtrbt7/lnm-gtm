from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# 1. Update fetch_location to join with websites and get pixel IDs
old_select = """select = 'id,name,url,gtm_id,gtm_account_id,gtm_container_id,ga4_measurement_id,gads_conversion_id,gads_appt_label,gads_phone_label,scheduler_type,phone_number,callrail_account_id,callrail_company_id'"""
new_select = """select = 'id,name,url,gtm_id,gtm_account_id,gtm_container_id,ga4_measurement_id,gads_conversion_id,gads_appt_label,gads_phone_label,scheduler_type,phone_number,callrail_account_id,callrail_company_id,websites(pixel_meta,pixel_tiktok,pixel_linkedin,pixel_ms_bing)'"""
content = content.replace(old_select, new_select)

# 2. Add Meta Pixel tag body function
meta_pixel_tag_func = """
def meta_pixel_event_tag(pixel_id, event_name, trigger_id):
    # This is a basic implementation assuming a custom HTML tag or a standard template
    # For now, let's use a custom HTML tag as it's most common for Facebook Pixel events
    html = f'''<script>
  fbq('track', '{event_name}');
</script>'''
    return {
        'name': f'Meta Pixel - Event - {event_name}',
        'type': 'html',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'html', 'value': html},
            {'type': 'BOOLEAN', 'key': 'supportDocumentWrite', 'value': 'false'},
        ],
        'firingTriggerId': [trigger_id],
        'tagFiringOption': 'ONCE_PER_EVENT',
    }
"""

# Insert before AI Traffic Tracking section
content = content.replace('# ── AI Traffic Tracking', meta_pixel_tag_func + '\n# ── AI Traffic Tracking')

# 3. Update main logic to use pixel IDs and create Meta Pixel tags
old_pixel_logic_pos = """    if has_phone and ga4_id:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_event_tag(ga4_id, 'phone_click', [cl_tid]), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - phone_click ({st})')"""

new_pixel_logic = """    if has_phone and ga4_id:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_event_tag(ga4_id, 'phone_click', [cl_tid]), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - phone_click ({st})')

    # Meta Pixel
    webs = loc.get('websites', [])
    pixel_meta = webs[0].get('pixel_meta') if webs and isinstance(webs, list) and len(webs) > 0 else (loc.get('pixel_meta') if 'pixel_meta' in loc else None)
    
    if pixel_meta and has_scheduler:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, meta_pixel_event_tag(pixel_meta, 'Schedule', appt_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'Meta Pixel - Event - Schedule ({st})')"""

content = content.replace(old_pixel_logic_pos, new_pixel_logic)

path.write_text(content)
print('Successfully patched setup_tags.py for Meta Pixel and Website join')
