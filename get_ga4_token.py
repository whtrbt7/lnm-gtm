"""
One-time script to generate OAuth credentials for analytics@leadsnearme.com
with Google Analytics Admin API (read) scope.
Run locally on LNM Mac (needs browser): python get_ga4_token.py
"""
import json, os
from google_auth_oauthlib.flow import InstalledAppFlow

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRET = os.path.join(SCRIPT_DIR, 'client_secret_1085978995784-8k7k7629ln2vsdn1j544d4f1b8kgf77o.apps.googleusercontent.com.json')
TOKEN_OUT     = os.path.join(SCRIPT_DIR, 'token_ga4.json')

SCOPES = [
    'https://www.googleapis.com/auth/analytics.readonly',
]

print('Opening browser for OAuth login...')
print('IMPORTANT: Log in with analytics@leadsnearme.com (or whichever account owns the GA4 properties)')
print()

if os.path.exists(TOKEN_OUT):
    os.remove(TOKEN_OUT)

flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
creds = flow.run_local_server(port=8082, prompt='consent', access_type='offline')

with open(TOKEN_OUT, 'w') as f:
    json.dump(json.loads(creds.to_json()), f, indent=2)

print(f'\nToken saved to {TOKEN_OUT}')
