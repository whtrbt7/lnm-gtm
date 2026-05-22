from pathlib import Path

def patch_script(filename, email, token_name, port):
    path = Path(f'~/llmprojects/lnm-gtm/{filename}').expanduser()
    content = """\"\"\"
One-time script to generate OAuth credentials for {email}.
Run this, log in with {email} in the browser window that opens,
then grant permissions. Token is saved to {token_name}.

Usage:
    python {filename}
\"\"\"

import json
import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRET = os.path.join(
    SCRIPT_DIR,
    'client_secret_1085978995784-8k7k7629ln2vsdn1j544d4f1b8kgf77o.apps.googleusercontent.com.json'
)
TOKEN_OUT = os.path.join(SCRIPT_DIR, '{token_name}')

SCOPES = [
    'https://www.googleapis.com/auth/tagmanager.manage.accounts',
    'https://www.googleapis.com/auth/tagmanager.edit.containers',
    'https://www.googleapis.com/auth/tagmanager.manage.users',
    'https://www.googleapis.com/auth/tagmanager.publish',
]

print(f'Opening browser for OAuth login...')
print(f'IMPORTANT: Log in with {email}')
print()

flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
creds = flow.run_local_server(
    port={port},
    prompt='consent',
    access_type='offline',
)

token_data = json.loads(creds.to_json())
with open(TOKEN_OUT, 'w') as f:
    json.dump(token_data, f, indent=2)

print(f'\nToken saved to {{TOKEN_OUT}}')
""".format(email=email, token_name=token_name, filename=filename, port=port)
    path.write_text(content)
    print(f'Updated {{filename}}')

patch_script('get_analytics_token.py', 'analytics@leadsnearme.com', 'token_analytics.json', 8080)
patch_script('get_reports_token.py', 'reports@leadsnearme.com', 'token_reports.json', 8082)
patch_script('get_alex_token.py', 'achiu@leadsnearme.com', 'token_alex.json', 8083)
