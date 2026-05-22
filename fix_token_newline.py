from pathlib import Path

scripts = ['get_analytics_token.py', 'get_reports_token.py', 'get_alex_token.py', 'get_analytics2_token.py']

for s in scripts:
    path = Path(f'~/llmprojects/lnm-gtm/{s}').expanduser()
    if not path.exists(): continue
    content = path.read_text()
    
    # Replace the broken f' with a newline
    content = content.replace("print(f'\nToken saved to", "print(f'\\nToken saved to")
    
    # Specifically target the literal newline error
    content = content.replace("print(f'\nToken saved to", "print(f'\\nToken saved to")
    
    # Manual surgical fix for the exact pattern seen in cat
    import re
    content = re.sub(r"print\(f'\nToken saved to", "print(f'\\nToken saved to", content)
    
    # Let's just rewrite them cleanly to be sure
    def get_content(email, token_name, filename, port):
        return f"""\"\"\"
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

print(f'\\nToken saved to {{TOKEN_OUT}}')
"""

    if s == 'get_analytics_token.py': path.write_text(get_content('analytics@leadsnearme.com', 'token_analytics.json', s, 8080))
    elif s == 'get_analytics2_token.py': path.write_text(get_content('analytics2@leadsnearme.com', 'token_analytics2.json', s, 8081))
    elif s == 'get_reports_token.py': path.write_text(get_content('reports@leadsnearme.com', 'token_reports.json', s, 8082))
    elif s == 'get_alex_token.py': path.write_text(get_content('achiu@leadsnearme.com', 'token_alex.json', s, 8083))
    
    print(f'Cleaned up {{s}}')
