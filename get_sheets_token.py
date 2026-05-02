"""
One-time script to generate OAuth credentials with Google Sheets access.
Run this, log in with the Google account that owns the tracking sheet,
then grant permissions. Token is saved to token_sheets.json.

Usage:
    python get_sheets_token.py
"""

import json, os
from google_auth_oauthlib.flow import InstalledAppFlow

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRET = os.path.join(
    SCRIPT_DIR,
    'client_secret_1085978995784-8k7k7629ln2vsdn1j544d4f1b8kgf77o.apps.googleusercontent.com.json'
)
TOKEN_OUT = os.path.join(SCRIPT_DIR, 'token_sheets.json')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

print('Opening browser for OAuth login...')
print('Log in with the Google account that has access to the tracking sheet.')
print()

flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
creds = flow.run_local_server(port=8080, prompt='consent', access_type='offline')

with open(TOKEN_OUT, 'w') as f:
    json.dump(json.loads(creds.to_json()), f, indent=2)

print(f'\nToken saved to {TOKEN_OUT}')
