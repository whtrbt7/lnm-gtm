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
            print("  [auth] Refreshing expired token...")
            creds.refresh(Request())
            data['token'] = creds.token
            with open(TOKEN_FILE, 'w') as f:
                json.dump(data, f, indent=2)
    return build('tagmanager', 'v2', credentials=creds)

def audit_vars(service, gtm_public_id, account_id, container_id):
    parent = f'accounts/{account_id}/containers/{container_id}'
    try:
        # Get workspace
        res = service.accounts().containers().workspaces().list(parent=parent).execute()
        workspaces = res.get('workspace', [])
        if not workspaces:
            return False, "No workspaces", False, False
        ws_id = workspaces[0]['workspaceId']
        ws_path = f'{parent}/workspaces/{ws_id}'
        
        # List enabled
        res = service.accounts().containers().workspaces().built_in_variables().list(parent=ws_path).execute()
        enabled = {v['type'] for v in res.get('builtInVariable', [])}
        
        has_url = 'clickUrl' in enabled
        has_text = 'clickText' in enabled
        
        # Check if workspace is clean (no uncommitted changes)
        # Note: This is hard to check via API without more calls, but we can assume
        # if the variables are enabled in the workspace, they will be in the next publish.
        
        return True, "OK", has_url, has_text
    except Exception as e:
        return False, str(e), False, False

def main():
    input_file = Path('gtm_locations.json')
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
        
    print(f"Auditing variables for {len(locations)} locations...")
    service = get_gtm_service()
    
    both_enabled = 0
    missing_vars = 0
    errors = 0
    
    for i, loc in enumerate(locations, 1):
        gtm_id = str(loc.get('gtm_id') or '').upper().strip()
        acct_id = str(loc.get('gtm_account_id') or '')
        ctr_id = str(loc.get('gtm_container_id') or '')
        
        if not acct_id or not ctr_id:
            if gtm_id in cache:
                acct_id = cache[gtm_id]['account_id']
                ctr_id = cache[gtm_id]['container_id']
            else:
                continue
                
        success, msg, has_url, has_text = audit_vars(service, gtm_id, acct_id, ctr_id)
        
        if not success:
            errors += 1
            if "rateLimitExceeded" in msg:
                time.sleep(30)
        elif has_url and has_text:
            both_enabled += 1
        else:
            missing_vars += 1
            print(f"[{loc['name']}] Missing variables (URL={has_url}, Text={has_text})")
            
        if i % 50 == 0:
            print(f"Processed {i}/{len(locations)}...")
            
        time.sleep(0.2)
            
    print(f"\nFinal Audit Report:")
    print(f"Both Enabled   : {both_enabled}")
    print(f"Missing Vars   : {missing_vars}")
    print(f"Errors/Skipped : {len(locations) - both_enabled - missing_vars}")

if __name__ == '__main__':
    main()
