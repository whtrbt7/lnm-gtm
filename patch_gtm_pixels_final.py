from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# 1. Update fetch_location with aliased join
old_select = """select = 'id,name,url,gtm_id,gtm_account_id,gtm_container_id,ga4_measurement_id,gads_conversion_id,gads_appt_label,gads_phone_label,scheduler_type,phone_number,callrail_account_id,callrail_company_id,websites!websites_location_id_fkey(pixel_meta,pixel_tiktok,pixel_linkedin,pixel_ms_bing)'"""
new_select = """select = 'id,name,url,gtm_id,gtm_account_id,gtm_container_id,ga4_measurement_id,gads_conversion_id,gads_appt_label,gads_phone_label,scheduler_type,phone_number,callrail_account_id,callrail_company_id,websites:websites!websites_location_id_fkey(pixel_meta,pixel_tiktok,pixel_linkedin,pixel_ms_bing)'"""
content = content.replace(old_select, new_select)

# 2. Fix the logic to read from the 'websites' key
content = content.replace("""    webs = loc.get('websites!websites_location_id_fkey', [])""", """    webs = loc.get('websites', [])""")

# 3. Clean up debug prints
content = content.replace("""    print(f"  [DEBUG] websites: {webs}")\n""", "")

path.write_text(content)
print('Successfully finalized GTM pixels patch')
