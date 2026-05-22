from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# 1. Improved ga4_id extraction
old_ga4_line = """    ga4_id     = str(loc.get('ga4_measurement_id') or '').strip()"""
new_ga4_line = """    # Extract GA4 ID (prefer locations, fallback to websites)
    ga4_id = str(loc.get('ga4_measurement_id') or '').strip()
    webs = loc.get('websites', [])
    if not ga4_id and webs and isinstance(webs, list) and len(webs) > 0:
        ga4_id = str(webs[0].get('ga4_measurement_id') or '').strip()"""
content = content.replace(old_ga4_line, new_ga4_line)

# 2. Fix redundant log calls
# Remove the extra logs that were outside the 'if ga4_id' blocks
content = content.replace("""    if gads_id:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, google_base_tag(gads_id, ap_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'Google Tag - AW Config ({st})')
    log('✓' if st != 'existed' else '·', 'Tag', f'Google Tag - AW Config ({st})')""",
    """    if gads_id:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, google_base_tag(gads_id, ap_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'Google Tag - AW Config ({st})')""")

content = content.replace("""    if ga4_id:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_config_tag(ga4_id, ap_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Configuration ({st})')
    log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Configuration ({st})')""",
    """    if ga4_id:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_config_tag(ga4_id, ap_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Configuration ({st})')""")

content = content.replace("""    if ga4_id:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_ai_overview_tag(ga4_id, tf_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - ai_overview_click ({st})')
    log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - ai_overview_click ({st})')""",
    """    if ga4_id:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_ai_overview_tag(ga4_id, tf_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - ai_overview_click ({st})')""")

content = content.replace("""    if ga4_id:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_ai_referral_tag(ga4_id, ar_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - ai_referral ({st})')
    log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - ai_referral ({st})')""",
    """    if ga4_id:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_ai_referral_tag(ga4_id, ar_tid), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - ai_referral ({st})')""")

content = content.replace("""    if ga4_id:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_lead_tag(ga4_id, [cf7_tid, wpf_tid, gfs_tid]), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - generate_lead ({st})')
    log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - generate_lead ({st})')""",
    """    if ga4_id:
        _, st = ensure_tag(service, acct_id, ctr_id, ws_id, ga4_lead_tag(ga4_id, [cf7_tid, wpf_tid, gfs_tid]), existing_tags, fr)
        log('✓' if st != 'existed' else '·', 'Tag', f'GA4 - Event - generate_lead ({st})')""")

path.write_text(content)
print('Successfully robustified setup_tags.py')
