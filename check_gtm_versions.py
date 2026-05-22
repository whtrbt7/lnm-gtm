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

def check_version(service, gtm_public_id, account_id, container_id):
    parent = f'accounts/{account_id}/containers/{container_id}'
    try:
        res = service.accounts().containers().versions().live(parent=parent).execute()
        version_name = res.get('name', 'Untitled Version')
        version_id = res.get('containerVersionId', '0')
        is_ours = "Activate Click Variables" in version_name
        return True, version_name, version_id, is_ours
    except Exception as e:
        return False, str(e), None, False

def main():
    input_file = Path('gtm_locations.json')
    if not input_file.exists():
        print(f"Error: Input file {input_file} not found.")
        sys.exit(1)
        
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
        
    print(f"Checking versions for {len(locations)} locations...")
    service = get_gtm_service()
    
    published_ours = 0
    published_other = 0
    errors = 0
    missing_ids = 0
    
    results = []
    
    for i, loc in enumerate(locations, 1):
        gtm_id = str(loc.get('gtm_id') or '').upper().strip()
        acct_id = str(loc.get('gtm_account_id') or '')
        ctr_id = str(loc.get('gtm_container_id') or '')
        
        if not acct_id or not ctr_id:
            if gtm_id in cache:
                acct_id = cache[gtm_id]['account_id']
                ctr_id = cache[gtm_id]['container_id']
            else:
                missing_ids += 1
                continue
                
        success, name, vid, ours = check_version(service, gtm_id, acct_id, ctr_id)
        
        if not success:
            errors += 1
            if "rateLimitExceeded" in name:
                print(f"Rate limit hit at {i}. Sleeping 30s...")
                time.sleep(30)
        elif ours:
            published_ours += 1
        else:
            published_other += 1
            
        if i % 50 == 0:
            print(f"Processed {i}/{len(locations)}...")
            
        time.sleep(0.1) # Fast check
            
    print(f"\nAudit complete.")
    print(f"Published (Ours) : {published_ours}")
    print(f"Published (Other): {published_other}")
    print(f"Errors          : {errors}")
    print(f"Missing IDs     : {missing_ids}")

if __name__ == '__main__':
    main()
