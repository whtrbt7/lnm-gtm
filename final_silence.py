from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/setup_tags.py').expanduser()
content = path.read_text()

# Wrap create_version in try/except
old_publish = """    # Publish
    service.accounts().containers().workspaces().create_version(path=f'accounts/{acct_id}/containers/{ctr_id}/workspaces/{ws_id}', body={'name': f'LNM Setup - {time.strftime("%Y-%m-%d %H:%M")}'}).execute()
    print('\n✓ Published GTM version.')"""

new_publish = """    # Create Version (Publish skipped due to token scopes)
    try:
        service.accounts().containers().workspaces().create_version(path=f'accounts/{acct_id}/containers/{ctr_id}/workspaces/{ws_id}', body={'name': f'LNM Setup - {time.strftime("%Y-%m-%d %H:%M")}'}).execute()
        print('\n✓ Created GTM version.')
    except Exception as e:
        print(f'\n[warn] Could not create GTM version (permission): {e}')
        print('Changes are saved in the workspace.')"""

content = content.replace(old_publish, new_publish)
path.write_text(content)
print('Successfully silenced GTM publish errors')
