from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# 1. Update mapping
old_mapping = """    'shopgenie':  ('appointment_booked',    'Shop Genie'),"""
new_mapping = """    'shopgenie':  ('appointmentBooked',     'Shop Genie'),"""
content = content.replace(old_mapping, new_mapping)

# 2. Update GA4 event name and parameters for Shop Genie
old_ga4_event_tag = """def ga4_event_tag(ga4_id, event_name, trigger_ids):
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
    }"""

new_ga4_event_tag = """def ga4_event_tag(ga4_id, event_name, trigger_ids):
    is_shop_genie = event_name == 'appointmentBooked'
    ga4_event_name = 'generate_lead' if is_shop_genie else event_name
    
    body = {
        'name': f'GA4 - Event - {ga4_event_name}',
        'type': 'gaawe',
        'parameter': [
            {'type': 'TAG_REFERENCE', 'key': 'gaSettings',            'value': 'GA4 - Configuration'},
            {'type': 'TEMPLATE',      'key': 'eventName',             'value': ga4_event_name},
            {'type': 'TEMPLATE',      'key': 'measurementIdOverride', 'value': ga4_id},
        ],
        'firingTriggerId': trigger_ids if isinstance(trigger_ids, list) else [trigger_ids],
        'tagFiringOption': 'ONCE_PER_EVENT',
        'monitoringMetadata': {'type': 'MAP'},
        'consentSettings': {'consentStatus': 'NOT_SET'},
    }
    
    if is_shop_genie:
        body['parameter'].append({
            'type': 'LIST', 'key': 'eventParameters', 'list': [
                {'type': 'MAP', 'map': [
                    {'type': 'TEMPLATE', 'key': 'name',  'value': 'method'},
                    {'type': 'TEMPLATE', 'key': 'value', 'value': 'shop_genie'},
                ]},
            ]
        })
    
    return body"""

content = content.replace(old_ga4_event_tag, new_ga4_event_tag)

path.write_text(content)
print('Successfully patched setup_tags.py for Shop Genie')
