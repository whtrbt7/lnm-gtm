from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

old_block = """    # Create Version (Publish skipped due to token scopes)
    try:
        service.accounts().containers().workspaces().create_version(path=f'accounts/{acct_id}/containers/{ctr_id}/workspaces/{ws_id}', body={'name': f'LNM Setup - {time.strftime(\"%Y-%m-%d %H:%M\")}'}).execute()
        print('\\n✓ Created GTM version.')
    except Exception as e:
        print(f'\\n[warn] Could not create GTM version (permission): {e}')
        print('Changes are saved in the workspace.')"""

new_block = """    # Create Version and Go Live
    try:
        res = service.accounts().containers().workspaces().create_version(
            path=f'accounts/{acct_id}/containers/{ctr_id}/workspaces/{ws_id}', 
            body={'name': f'LNM Setup - {time.strftime(\"%Y-%m-%d %H:%M\")}'}
        ).execute()
        
        version_id = res.get('containerVersion', {}).get('containerVersionId')
        version_path = res.get('containerVersion', {}).get('path')
        
        if version_path:
            print(f'\\n✓ Created GTM version {version_id}. Publishing...')
            service.accounts().containers().versions().publish(path=version_path).execute()
            print('✓ Container is now LIVE!')
        else:
            print('\\n✓ Created GTM version (no publish path found).')
            
    except Exception as e:
        print(f'\\n[warn] GTM Publish failed: {e}')
        print('Changes are saved in the workspace. You may need to re-authorize for Publish scope.')"""

if old_block in content:
    path.write_text(content.replace(old_block, new_block))
    print('Successfully enabled automatic publishing in setup_tags.py')
else:
    print('Could not find version block in setup_tags.py')
