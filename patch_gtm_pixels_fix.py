from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# Fix the join syntax to resolve ambiguity
content = content.replace('websites(pixel_meta,pixel_tiktok,pixel_linkedin,pixel_ms_bing)', 
                          'websites!websites_location_id_fkey(pixel_meta,pixel_tiktok,pixel_linkedin,pixel_ms_bing)')

# Fix the logic to read from the joined table
content = content.replace("""    webs = loc.get('websites', [])""", """    webs = loc.get('websites!websites_location_id_fkey', [])""")

path.write_text(content)
print('Successfully fixed GTM pixels patch')
