import json
from google.oauth2.credentials import Credentials
with open('token_analytics.json') as f: data = json.load(f)
creds = Credentials(**{k: v for k, v in data.items() if k in ['token','refresh_token','token_uri','client_id','client_secret','scopes']})
print(f'Scopes in creds: {creds.scopes}')
