"""
One-time script to generate OAuth credentials for analytics@leadsnearme.com.
Usage: python get_analytics_token.py
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

# Expanded scopes to cover every possibility for creation/publishing
SCOPES = [
    'https://www.googleapis.com/auth/tagmanager.manage.accounts',
    'https://www.googleapis.com/auth/tagmanager.edit.containers',
    'https://www.googleapis.com/auth/tagmanager.delete.containers',
    'https://www.googleapis.com/auth/tagmanager.edit.containerversions',
    'https://www.googleapis.com/auth/tagmanager.manage.users',
    'https://www.googleapis.com/auth/tagmanager.publish',
]

print(f'Opening browser for OAuth login...')
print(f'IMPORTANT: Log in with analytics@leadsnearme.com')
print()

# Delete old token to ensure a fresh flow with new scopes
if os.path.exists(TOKEN_OUT):
    os.remove(TOKEN_OUT)

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
