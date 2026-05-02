"""
One-time script to generate OAuth credentials for analytics@leadsnearme.com.
Run this, log in with analytics@leadsnearme.com in the browser window that opens,
then grant permissions. Token is saved to token_analytics.json.

Usage:
    python get_analytics_token.py
"""

import json
import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRET = os.path.join(
    SCRIPT_DIR,
    'client_secret_1085978995784-8k7k7629ln2vsdn1j544d4f1b8kgf77o.apps.googleusercontent.com.json'
)
TOKEN_OUT = os.path.join(SCRIPT_DIR, 'token_analytics.json')

SCOPES = [
    'https://www.googleapis.com/auth/tagmanager.manage.accounts',
    'https://www.googleapis.com/auth/tagmanager.edit.containers',
    'https://www.googleapis.com/auth/tagmanager.manage.users',
]

print('Opening browser for OAuth login...')
print('IMPORTANT: Log in with analytics@leadsnearme.com')
print()

flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
creds = flow.run_local_server(
    port=8080,
    prompt='consent',
    access_type='offline',
)

token_data = json.loads(creds.to_json())
with open(TOKEN_OUT, 'w') as f:
    json.dump(token_data, f, indent=2)

print(f'\nToken saved to {TOKEN_OUT}')
print('You can now run:')
print('  python push_gtm_setup.py --tier 3 --token-file token_analytics.json --rebuild-index')
