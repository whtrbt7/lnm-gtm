from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# Fix AI tags by adding measurementIdOverride and using the ga4_event_tag helper logic style
old_ai_block = """    if ga4_id:
        ensure_tag(service, acct_id, ctr_id, ws_id, {'name': 'GA4 - Event - ai_overview_click', 'type': 'gaawe', 'parameter': [{'type': 'TAG_REFERENCE', 'key': 'gaSettings', 'value': 'GA4 - Configuration'}, {'type': 'TEMPLATE', 'key': 'eventName', 'value': 'ai_overview_click'}], 'firingTriggerId': [tf_tid]}, existing_tags, fr)
        ensure_tag(service, acct_id, ctr_id, ws_id, {'name': 'GA4 - Event - ai_referral', 'type': 'gaawe', 'parameter': [{'type': 'TAG_REFERENCE', 'key': 'gaSettings', 'value': 'GA4 - Configuration'}, {'type': 'TEMPLATE', 'key': 'eventName', 'value': 'ai_referral'}, {'type': 'LIST', 'key': 'eventParameters', 'list': [{'type': 'MAP', 'map': [{'type': 'TEMPLATE', 'key': 'name', 'value': 'ai_source'}, {'type': 'TEMPLATE', 'key': 'value', 'value': '{{JS - AI Referrer}}'}]}]}], 'firingTriggerId': [ar_tid]}, existing_tags, fr)
        log('✓', 'Feature', 'AI Traffic Tracking')"""

new_ai_block = """    if ga4_id:
        ensure_tag(service, acct_id, ctr_id, ws_id, {
            'name': 'GA4 - Event - ai_overview_click', 'type': 'gaawe', 
            'parameter': [
                {'type': 'TAG_REFERENCE', 'key': 'gaSettings', 'value': 'GA4 - Configuration'},
                {'type': 'TEMPLATE', 'key': 'eventName', 'value': 'ai_overview_click'},
                {'type': 'TEMPLATE', 'key': 'measurementIdOverride', 'value': ga4_id}
            ], 
            'firingTriggerId': [tf_tid]
        }, existing_tags, fr)
        
        ensure_tag(service, acct_id, ctr_id, ws_id, {
            'name': 'GA4 - Event - ai_referral', 'type': 'gaawe', 
            'parameter': [
                {'type': 'TAG_REFERENCE', 'key': 'gaSettings', 'value': 'GA4 - Configuration'},
                {'type': 'TEMPLATE', 'key': 'eventName', 'value': 'ai_referral'},
                {'type': 'TEMPLATE', 'key': 'measurementIdOverride', 'value': ga4_id},
                {'type': 'LIST', 'key': 'eventParameters', 'list': [{'type': 'MAP', 'map': [{'type': 'TEMPLATE', 'key': 'name', 'value': 'ai_source'}, {'type': 'TEMPLATE', 'key': 'value', 'value': '{{JS - AI Referrer}}'}]}]}
            ], 
            'firingTriggerId': [ar_tid]
        }, existing_tags, fr)
        log('✓', 'Feature', 'AI Traffic Tracking')"""

if old_ai_block in content:
    path.write_text(content.replace(old_ai_block, new_ai_block))
    print('Successfully fixed AI tags in setup_tags.py')
else:
    # Try with slight formatting difference
    print('Could not find AI block, trying robust replace...')
    import re
    content = re.sub(r'if ga4_id:\s+ensure_tag\(service, acct_id, ctr_id, ws_id, {\'name\': \'GA4 - Event - ai_overview_click\'.*?log\(\'✓\', \'Feature\', \'AI Traffic Tracking\'\)', new_ai_block, content, flags=re.DOTALL)
    path.write_text(content)
