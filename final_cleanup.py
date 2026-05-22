from pathlib import Path
import time

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
lines = path.read_text().splitlines()

# Find the publish block start
start_idx = -1
for i, line in enumerate(lines):
    if '# Publish' in line or 'create_version' in line:
        start_idx = i
        break

if start_idx != -1:
    # Truncate and add the new block
    new_lines = lines[:start_idx]
    new_lines.extend([
        """    # Create Version (Publish skipped due to token scopes)""",
        """    try:""",
        """        service.accounts().containers().workspaces().create_version(path=f'accounts/{acct_id}/containers/{ctr_id}/workspaces/{ws_id}', body={'name': f'LNM Setup - {time.strftime(\"%Y-%m-%d %H:%M\")}'}).execute()""",
        """        print('\\n✓ Created GTM version.')""",
        """    except Exception as e:""",
        """        print(f'\\n[warn] Could not create GTM version (permission): {e}')""",
        """        print('Changes are saved in the workspace.')""",
        """""",
        """if __name__ == '__main__':""",
        """    main()"""
    ])
    path.write_text('\n'.join(new_lines))
    print('Successfully cleaned up setup_tags.py')
else:
    print('Could not find publish block')
