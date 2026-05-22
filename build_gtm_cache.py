"""
build_gtm_cache.py — Scan all GTM accounts in parallel and write gtm_id_cache.json.

After running, setup_tags.py skips the full scan entirely (cache hit = instant).

Usage:
    python build_gtm_cache.py                         # uses token.json
    python build_gtm_cache.py --token-file token_analytics.json
    python build_gtm_cache.py --workers 20            # default 15
"""

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCRIPT_DIR = Path(__file__).parent
CACHE_FILE = SCRIPT_DIR / 'gtm_id_cache.json'

SCOPES = ['https://www.googleapis.com/auth/tagmanager.readonly']


def _build_service(token_file: str):
    creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    return build('tagmanager', 'v2', credentials=creds, cache_discovery=False)


def _fetch_containers(service, acct: dict) -> list[dict]:
    """Return list of {gtm_id, account_id, container_id} for one account."""
    results = []
    try:
        containers = service.accounts().containers().list(
            parent=acct['path']
        ).execute().get('container', [])
        for c in containers:
            gtm_id = c.get('publicId', '').upper()
            if gtm_id:
                results.append({
                    'gtm_id':       gtm_id,
                    'account_id':   acct['accountId'],
                    'container_id': str(c['containerId']),
                })
    except HttpError as e:
        if e.resp.status == 429:
            time.sleep(2)
        # Skip accounts we can't read — service account may not have access
    except Exception:
        pass
    return results


def build_cache(token_file: str, workers: int = 15) -> dict:
    service = _build_service(token_file)
    accounts = service.accounts().list().execute().get('account', [])
    print(f'Fetched {len(accounts)} GTM accounts. Scanning with {workers} workers...')

    cache = {}
    done = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_containers, service, acct): acct for acct in accounts}
        for future in as_completed(futures):
            done += 1
            if done % 50 == 0:
                print(f'  {done}/{len(accounts)} accounts scanned, {len(cache)} containers found...')
            for entry in future.result():
                cache[entry['gtm_id']] = {
                    'account_id':   entry['account_id'],
                    'container_id': entry['container_id'],
                }

    return cache


def main():
    parser = argparse.ArgumentParser(description='Build full GTM ID → account/container cache.')
    parser.add_argument('--token-file', default=str(SCRIPT_DIR / 'token_analytics.json'),
                        help='OAuth token JSON (default: token_analytics.json)')
    parser.add_argument('--workers', type=int, default=15,
                        help='Parallel workers for account scanning (default: 15)')
    args = parser.parse_args()

    if not os.path.exists(args.token_file):
        print(f'Token file not found: {args.token_file}')
        return

    t0 = time.time()
    cache = build_cache(args.token_file, args.workers)
    elapsed = time.time() - t0

    CACHE_FILE.write_text(json.dumps(cache, indent=2))
    print(f'\nDone. {len(cache)} containers cached in {elapsed:.1f}s → {CACHE_FILE}')


if __name__ == '__main__':
    main()
