from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# 1. Add all pixel tag body functions
pixel_tag_funcs = """
def tiktok_pixel_event_tag(pixel_id, event_name, trigger_id):
    html = f'''<script>
  ttq.track('{event_name}');
</script>'''
    return {
        'name': f'TikTok Pixel - Event - {event_name}',
        'type': 'html',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'html', 'value': html},
            {'type': 'BOOLEAN', 'key': 'supportDocumentWrite', 'value': 'false'},
        ],
        'firingTriggerId': [trigger_id],
        'tagFiringOption': 'ONCE_PER_EVENT',
    }

def linkedin_pixel_event_tag(pixel_id, event_name, trigger_id):
    # event_name for Schedule is often 'Lead' or 'Conversion' in LinkedIn
    html = f'''<script>
  window.lintrk && window.lintrk('track', {{ conversion_id: {pixel_id} }});
</script>'''
    return {
        'name': f'LinkedIn Pixel - Event - {event_name}',
        'type': 'html',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'html', 'value': html},
            {'type': 'BOOLEAN', 'key': 'supportDocumentWrite', 'value': 'false'},
        ],
        'firingTriggerId': [trigger_id],
        'tagFiringOption': 'ONCE_PER_EVENT',
    }

def ms_bing_pixel_event_tag(pixel_id, event_name, trigger_id):
    html = f'''<script>
  window.uetq = window.uetq || [];
  window.uetq.push('event', '{event_name.lower()}', {{}});
</script>'''
    return {
        'name': f'MS Bing Pixel - Event - {event_name}',
        'type': 'html',
        'parameter': [
            {'type': 'TEMPLATE', 'key': 'html', 'value': html},
            {'type': 'BOOLEAN', 'key': 'supportDocumentWrite', 'value': 'false'},
        ],
        'firingTriggerId': [trigger_id],
        'tagFiringOption': 'ONCE_PER_EVENT',
    }
"""

# Insert before meta_pixel_event_tag
content = content.replace('def meta_pixel_event_tag', pixel_tag_funcs + '\ndef meta_pixel_event_tag')

# 2. Update main logic to create all pixel tags
old_pixel_block = """    # Meta Pixel
    webs = loc.get('websites', [])

    pixel_meta = webs[0].get('pixel_meta') if webs and isinstance(webs, list) and len(webs) > 0 else (loc.get('pixel_meta') if 'pixel_meta' in loc else None)
    
    if pixel_meta and has_scheduler:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, meta_pixel_event_tag(pixel_meta, 'Schedule', appt_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'Meta Pixel - Event - Schedule ({st})')"""

new_pixel_block = """    # Pixel IDs
    webs = loc.get('websites', [])
    if webs and isinstance(webs, list) and len(webs) > 0:
        w = webs[0]
        p_meta = w.get('pixel_meta')
        p_tiktok = w.get('pixel_tiktok')
        p_linkedin = w.get('pixel_linkedin')
        p_bing = w.get('pixel_ms_bing')
        
        if has_scheduler:
            if p_meta:
                _, st = ensure_tag(service, acct_id, ctr_id, ws_id, meta_pixel_event_tag(p_meta, 'Schedule', appt_tid), existing_tags, fr)
                log('✓' if st != 'existed' else '·', 'Tag', f'Meta Pixel - Event - Schedule ({st})')
            if p_tiktok:
                _, st = ensure_tag(service, acct_id, ctr_id, ws_id, tiktok_pixel_event_tag(p_tiktok, 'CompleteRegistration', appt_tid), existing_tags, fr)
                log('✓' if st != 'existed' else '·', 'Tag', f'TikTok Pixel - Event - CompleteRegistration ({st})')
            if p_linkedin:
                _, st = ensure_tag(service, acct_id, ctr_id, ws_id, linkedin_pixel_event_tag(p_linkedin, 'Lead', appt_tid), existing_tags, fr)
                log('✓' if st != 'existed' else '·', 'Tag', f'LinkedIn Pixel - Event - Lead ({st})')
            if p_bing:
                _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ms_bing_pixel_event_tag(p_bing, 'Submit_Lead_Form', appt_tid), existing_tags, fr)
                log('✓' if st != 'existed' else '·', 'Tag', f'MS Bing Pixel - Event - Submit_Lead_Form ({st})')"""

if old_pixel_block in content:
    content = content.replace(old_pixel_block, new_pixel_block)
    path.write_text(content)
    print('Successfully patched setup_tags.py for all Pixel IDs')
else:
    print('Could not find target block in setup_tags.py')
