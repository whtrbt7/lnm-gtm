"""
Audit every GTM account and ensure all LNM service accounts have:
  - Account-level access: admin
  - All containers: publish

LNM GTM service accounts managed by this script:
  - reports@leadsnearme.com
  - analytics@leadsnearme.com
  - analytics2@leadsnearme.com
  - master@drivenleads.rocks

Usage:
  python3 ensure_reports_admin.py [--dry-run]

Output: one line per account per email — OK / FIXED / ERROR
"""
import argparse, json, os, sys, time

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE  = os.path.join(SCRIPT_DIR, 'token.json')

TARGET_EMAILS = [
    'reports@leadsnearme.com',
    'analytics@leadsnearme.com',
    'analytics2@leadsnearme.com',
]

TARGET_ACCOUNT_ACCESS   = 'admin'
TARGET_CONTAINER_ACCESS = 'publish'


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


def build_desired_permission(email, containers):
    """Build userPermission body: admin account access + publish on all containers."""
    return {
        'emailAddress': email,
        'accountAccess': {'permission': TARGET_ACCOUNT_ACCESS},
        'containerAccess': [
            {'containerId': c['containerId'], 'permission': TARGET_CONTAINER_ACCESS}
            for c in containers
        ],
    }


def check_permission(perm):
    """Return (account_ok, bad_containers) for an existing permission entry."""
    acct_ok = perm.get('accountAccess', {}).get('permission') == TARGET_ACCOUNT_ACCESS
    bad_containers = [
        c['containerId']
        for c in perm.get('containerAccess', [])
        if c.get('permission') != TARGET_CONTAINER_ACCESS
    ]
    return acct_ok, bad_containers


def ensure_email(service, acct_id, acct_name, email, perms, containers, dry_run):
    """Ensure a single email has correct permissions. Returns 'ok', 'fixed', or 'error'."""
    existing = next((p for p in perms if p.get('emailAddress', '').lower() == email.lower()), None)

    try:
        if existing:
            acct_ok, bad_ctrs = check_permission(existing)
            if acct_ok and not bad_ctrs:
                print(f'  OK      [{email}] {acct_name}')
                return 'ok'

            desired = build_desired_permission(email, containers)
            desired['path'] = existing['path']
            if dry_run:
                print(f'  [DRY] UPDATE [{email}] {acct_name} — acct_ok={acct_ok}, bad_containers={bad_ctrs}')
            else:
                try:
                    call(lambda: service.accounts().user_permissions().update(
                        path=existing['path'],
                        body=desired,
                    ).execute())
                except Exception as upd_err:
                    if '404' in str(upd_err):
                        desired.pop('path', None)
                        call(lambda: service.accounts().user_permissions().create(
                            parent=f'accounts/{acct_id}',
                            body=desired,
                        ).execute())
                    else:
                        raise
                print(f'  FIXED   [{email}] {acct_name} (updated)')
            return 'fixed'
        else:
            desired = build_desired_permission(email, containers)
            if dry_run:
                print(f'  [DRY] CREATE [{email}] {acct_name}')
            else:
                call(lambda: service.accounts().user_permissions().create(
                    parent=f'accounts/{acct_id}',
                    body=desired,
                ).execute())
                print(f'  FIXED   [{email}] {acct_name} (created)')
            return 'fixed'

    except Exception as e:
        print(f'  ERROR   [{email}] {acct_name}: {e}')
        return 'error'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--token-file', default=TOKEN_FILE)
    parser.add_argument('--email', action='append', dest='emails',
                        help='Override target emails (can repeat). Defaults to all 4 service accounts.')
    args = parser.parse_args()

    target_emails = args.emails or TARGET_EMAILS

    service = get_service(args.token_file)

    accounts = call(lambda: service.accounts().list().execute()).get('account', [])
    print(f'Found {len(accounts)} GTM accounts | Checking {len(target_emails)} email(s): {", ".join(target_emails)}\n')

    totals = {e: {'ok': 0, 'fixed': 0, 'error': 0} for e in target_emails}

    for acct in accounts:
        acct_id   = acct['accountId']
        acct_name = acct.get('name', acct_id)

        try:
            perms = call(lambda: service.accounts().user_permissions().list(
                parent=f'accounts/{acct_id}'
            ).execute()).get('userPermission', [])

            containers = call(lambda: service.accounts().containers().list(
                parent=f'accounts/{acct_id}'
            ).execute()).get('container', [])

        except Exception as e:
            for email in target_emails:
                print(f'  ERROR   [{email}] {acct_name}: {e}')
                totals[email]['error'] += 1
            time.sleep(0.5)
            continue

        for email in target_emails:
            result = ensure_email(service, acct_id, acct_name, email, perms, containers, args.dry_run)
            totals[email][result] += 1

        time.sleep(0.5)  # stay under per-minute quota

    print('\n--- Summary ---')
    for email in target_emails:
        t = totals[email]
        print(f'  {email:<35}  OK: {t["ok"]:>3}  Fixed: {t["fixed"]:>3}  Errors: {t["error"]:>3}')


if __name__ == '__main__':
    main()
