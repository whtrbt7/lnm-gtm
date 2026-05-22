"""
Remove a user from all GTM accounts.

Usage:
  python3 remove_gtm_user.py --email master@drivenleads.rocks [--dry-run]

Output: one line per account — REMOVED / NOT_FOUND / ERROR
"""
import argparse, json, os, time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE  = os.path.join(SCRIPT_DIR, 'token.json')


def get_service(token_file=TOKEN_FILE):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    with open(token_file) as f:
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
            data['expiry'] = creds.expiry.isoformat() if creds.expiry else None
            with open(token_file, 'w') as f:
                json.dump(data, f, indent=2)
        else:
            raise RuntimeError('Token invalid. Re-run token auth script.')
    return build('tagmanager', 'v2', credentials=creds)


def call(fn, retries=5):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = 60 if '429' in str(e) or 'rateLimitExceeded' in str(e) else 2 ** attempt
            print(f'    [retry {attempt+1}] sleeping {wait}s: {e}')
            time.sleep(wait)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--email', required=True, help='Email address to remove from all GTM accounts')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--token-file', default=TOKEN_FILE)
    args = parser.parse_args()

    service = get_service(args.token_file)

    accounts = call(lambda: service.accounts().list().execute()).get('account', [])
    print(f'Found {len(accounts)} GTM accounts\n')
    if args.dry_run:
        print('[DRY RUN — no changes will be made]\n')

    removed = not_found = errors = 0

    for acct in accounts:
        acct_id   = acct['accountId']
        acct_name = acct.get('name', acct_id)

        try:
            perms = call(lambda: service.accounts().user_permissions().list(
                parent=f'accounts/{acct_id}'
            ).execute()).get('userPermission', [])

            existing = next(
                (p for p in perms if p.get('emailAddress', '').lower() == args.email.lower()),
                None,
            )

            if not existing:
                print(f'  NOT_FOUND  {acct_name}')
                not_found += 1
            elif args.dry_run:
                print(f'  [DRY] REMOVE  {acct_name}')
                removed += 1
            else:
                call(lambda: service.accounts().user_permissions().delete(
                    path=existing['path'],
                ).execute())
                print(f'  REMOVED  {acct_name}')
                removed += 1

        except Exception as e:
            print(f'  ERROR  {acct_name}: {e}')
            errors += 1

        time.sleep(0.5)

    print(f'\nDone — Removed: {removed}  Not found: {not_found}  Errors: {errors}')


if __name__ == '__main__':
    main()
