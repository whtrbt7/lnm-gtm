"""Re-authorize reports@ with full scopes including tagmanager.publish."""
import json, os
from urllib.parse import urlparse
from google_auth_oauthlib.flow import InstalledAppFlow

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, 'config.json')
TOKEN_OUT   = os.path.join(SCRIPT_DIR, 'token_reports.json')

with open(CONFIG_FILE) as f:
    config = json.load(f)

SCOPES = [
    'https://www.googleapis.com/auth/tagmanager.manage.accounts',
    'https://www.googleapis.com/auth/tagmanager.edit.containers',
    'https://www.googleapis.com/auth/tagmanager.edit.containerversions',
    'https://www.googleapis.com/auth/tagmanager.publish',
    'https://www.googleapis.com/auth/tagmanager.manage.users',
]

client_config = {
    'installed': {
        'client_id':     config['client_id'],
        'client_secret': config['client_secret'],
        'redirect_uris': [config.get('redirect_uri', 'http://localhost:8080')],
        'auth_uri':      'https://accounts.google.com/o/oauth2/auth',
        'token_uri':     'https://oauth2.googleapis.com/token',
    }
}

print('Starting OAuth flow — copy the URL below into your browser, log in as reports@leadsnearme.com.')
flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=8080, prompt='consent', access_type='offline', open_browser=False)

token_data = json.loads(creds.to_json())
token_data['scopes'] = SCOPES
with open(TOKEN_OUT, 'w') as f:
    json.dump(token_data, f, indent=2)

print(f'Saved to {TOKEN_OUT}')
print(f'Scopes: {token_data.get("scopes")}')
