from pathlib import Path

path = Path('~/llmprojects/lnm-gtm/get_analytics2_token.py').expanduser()
content = path.read_text()

old_scopes = """SCOPES = [
    'https://www.googleapis.com/auth/tagmanager.manage.accounts',
    'https://www.googleapis.com/auth/tagmanager.edit.containers',
    'https://www.googleapis.com/auth/tagmanager.manage.users',
]"""

new_scopes = """SCOPES = [
    'https://www.googleapis.com/auth/tagmanager.manage.accounts',
    'https://www.googleapis.com/auth/tagmanager.edit.containers',
    'https://www.googleapis.com/auth/tagmanager.manage.users',
    'https://www.googleapis.com/auth/tagmanager.publish',
]"""

if old_scopes in content:
    path.write_text(content.replace(old_scopes, new_scopes))
    print('Successfully added publish scope to token script')
else:
    print('Could not find scopes block in token script')
