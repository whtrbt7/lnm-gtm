import os
import sys
import json
import time
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_FILE = SCRIPT_DIR / 'gtm_id_cache.json'
INDEX_CACHE_FILE = SCRIPT_DIR / 'container_index_cache.json'
TOKEN_FILE = SCRIPT_DIR / 'token_reports.json'

def get_gtm_service():
    with open(TOKEN_FILE) as f:
        data = json.load(f)
    creds = Credentials(
        token=data.get('token'),
        refresh_token=data.get('refresh_token'),
        token_uri=data.get('token_uri', 'https://oauth2.googleapis.com/token'),
        client_id=data.get('client_id'),
        client_secret=data.get('client_secret'),
        scopes=data.get('scopes'),
    )
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            data['token'] = creds.token
            with open(TOKEN_FILE, 'w') as f:
                json.dump(data, f, indent=2)
    return build('tagmanager', 'v2', credentials=creds)

def enable_vars(service, gtm_public_id, account_id, container_id, name):
    parent = f'accounts/{account_id}/containers/{container_id}'
    try:
        # Get workspace
        res = service.accounts().containers().workspaces().list(parent=parent).execute()
        workspaces = res.get('workspace', [])
        if not workspaces:
            print(f"  ✗ Error: No workspaces found")
            return False, False
        ws_id = workspaces[0]['workspaceId']
        ws_path = f'{parent}/workspaces/{ws_id}'
        
        # List enabled
        res = service.accounts().containers().workspaces().built_in_variables().list(parent=ws_path).execute()
        enabled = {v['type'] for v in res.get('builtInVariable', [])}
        
        changed = False
        for var_type in ['clickUrl', 'clickText']:
            if var_type not in enabled:
                service.accounts().containers().workspaces().built_in_variables().create(parent=ws_path, type=[var_type]).execute()
                print(f"  ✓ Enabled {var_type}")
                changed = True
            else:
                print(f"  · {var_type} already enabled")
                
        if changed:
            print(f"  Publishing version...")
            version = service.accounts().containers().workspaces().create_version(
                path=ws_path,
                body={'name': f'LNM - Activate Click Variables', 'notes': 'Automated activation of Click URL and Click Text'},
            ).execute()
            version_id = version['containerVersion']['containerVersionId']
            service.accounts().containers().versions().publish(
                path=f'{parent}/versions/{version_id}',
            ).execute()
            print(f"  ✓ Published version {version_id}")
            return True, False
        else:
            print(f"  No changes needed.")
            return True, False
    except Exception as e:
        if "rateLimitExceeded" in str(e):
            print(f"  ✗ Rate limit exceeded")
            return False, True
        print(f"  ✗ Error: {e}")
        return False, False

def main():
    input_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('gtm_locations.json')
    with open(input_file) as f:
        locations = json.load(f)
        
    cache = {}
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cache = json.load(f)
            
    if INDEX_CACHE_FILE.exists():
        with open(INDEX_CACHE_FILE) as f:
            idx = json.load(f).get('gtm_index', {})
            for k, v in idx.items():
                if k not in cache:
                    cache[k] = {'account_id': v[0], 'container_id': v[1]}
        
    print(f"Processing {len(locations)} locations...")
    service = get_gtm_service()
    
    success_count = 0
    fail_count = 0
    skipped = 0
    
    for i, loc in enumerate(locations, 1):
        gtm_id = str(loc.get('gtm_id') or '').upper().strip()
        acct_id = str(loc.get('gtm_account_id') or '')
        ctr_id = str(loc.get('gtm_container_id') or '')
        
        if not acct_id or not ctr_id:
            if gtm_id in cache:
                acct_id = cache[gtm_id]['account_id']
                ctr_id = cache[gtm_id]['container_id']
            else:
                # print(f"({i}/{len(locations)}) Skipping {loc['name']} ({gtm_id}) - no account/container ID")
                skipped += 1
                continue
                
        print(f"({i}/{len(locations)}) processing {loc['name']} ({gtm_id})...")
        success, is_rate_limit = enable_vars(service, gtm_id, acct_id, ctr_id, loc['name'])
        if success:
            success_count += 1
        else:
            fail_count += 1
            if is_rate_limit:
                print("Sleeping for 60s due to rate limit...")
                time.sleep(60)
            
        time.sleep(0.5)
            
    print(f"\nBatch complete.")
    print(f"Success: {success_count}")
    print(f"Failed : {fail_count}")
    print(f"Skipped: {skipped}")

if __name__ == '__main__':
    main()
