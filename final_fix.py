from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# 1. Fix create_version call (use path instead of parent)
content = content.replace("""create_version(parent=f'accounts/{acct_id}/containers/{ctr_id}/workspaces/{ws_id}', body={""",
                          """create_version(path=f'accounts/{acct_id}/containers/{ctr_id}/workspaces/{ws_id}', body={""")

# 2. Fix log message for GA4 event mapping
content = content.replace("""log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - {appt_event}')""",
                          """ga4_event_name = 'generate_lead' if appt_event == 'appointmentBooked' else appt_event
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - {ga4_event_name}')""")

path.write_text(content)
print('Successfully applied final fixes to setup_tags.py')
