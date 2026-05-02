"""
Recover missing GTM IDs for warning rows.

For each target row with no GTM ID, scans all GTM accounts (both main and analytics
tokens) looking for containers whose name or domain matches the row's URL.

Writes matches back to col 29 (1-based) = COL_GTM_ID in the XLSX.
"""
import os, re, json, openpyxl
from googleapiclient.errors import HttpError
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
XLSX_PATH  = os.path.join(SCRIPT_DIR, 'GTM Bulk Setup OktoRocket.xlsx')
SHEET_NAME = 'AA Client Import List (1)'

COL_NAME   = 1   # 0-based
COL_URL    = 20  # 0-based → col U
COL_GTM_ID = 28  # 0-based → col AC (written as column 29 1-based)

# The 23 warning rows from the Playwright run
TARGET_ROWS = [211, 427, 431, 440, 442, 449, 456, 460, 474, 476,
               506, 519, 525, 526, 544, 557, 562, 575, 579, 584,
               611, 615, 624]


def get_service(token_file):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    path = os.path.join(SCRIPT_DIR, token_file)
    with open(path) as f:
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
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        else:
            raise RuntimeError(f'Token {token_file} invalid.')
    return build('tagmanager', 'v2', credentials=creds)


def clean_domain(url):
    if not url:
        return ''
    url = re.sub(r'^https?://', '', str(url)).rstrip('/')
    url = url.split('/')[0]  # remove path
    return url.lower()


def domain_keywords(domain):
    """Extract meaningful keywords from a domain for fuzzy matching."""
    d = domain.lower()
    d = re.sub(r'\.(com|ca|net|org|io)$', '', d)
    d = re.sub(r'www\.', '', d)
    # Split on common separators and keep parts > 3 chars
    parts = re.split(r'[-_.]', d)
    return [p for p in parts if len(p) > 3]


def build_container_index(service, token_label):
    """Return dict: container_name_lower -> publicId"""
    index = {}
    accounts = service.accounts().list().execute().get('account', [])
    print(f'  [{token_label}] {len(accounts)} accounts')
    for i, acct in enumerate(accounts):
        if i % 50 == 0 and i > 0:
            print(f'  [{token_label}] scanned {i}/{len(accounts)}...')
        aid = acct['accountId']
        try:
            containers = service.accounts().containers().list(
                parent=f'accounts/{aid}'
            ).execute().get('container', [])
            for c in containers:
                name = c.get('name', '').lower()
                pub  = c.get('publicId', '')
                if pub:
                    index[name] = pub
        except HttpError as e:
            if e.resp.status == 429:
                time.sleep(5)
            # skip
        time.sleep(0.05)
    return index


def find_match(container_index, domain):
    """Try exact match, then keyword match."""
    domain_l = domain.lower()
    # Exact
    if domain_l in container_index:
        return container_index[domain_l], 'exact'
    # Strip www.
    stripped = re.sub(r'^www\.', '', domain_l)
    if stripped in container_index:
        return container_index[stripped], 'exact-stripped'
    # Keyword: all keywords must appear in container name
    keywords = domain_keywords(domain)
    if keywords:
        for name, pub in container_index.items():
            if all(kw in name for kw in keywords):
                return pub, f'keyword({keywords})'
    # Partial: first long keyword
    for kw in sorted(domain_keywords(domain), key=len, reverse=True):
        if len(kw) >= 5:
            for name, pub in container_index.items():
                if kw in name:
                    return pub, f'partial({kw})'
    return None, None


def load_targets():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    ws = wb[SHEET_NAME]
    targets = []
    for rn in TARGET_ROWS:
        row = list(ws.iter_rows(min_row=rn, max_row=rn, values_only=True))[0]
        name   = row[COL_NAME]
        url    = row[COL_URL]
        gtm_id = row[COL_GTM_ID]
        domain = clean_domain(url)
        targets.append((rn, name, domain, gtm_id))
    return targets


def writeback(row_num, gtm_id):
    wb = openpyxl.load_workbook(XLSX_PATH)
    ws = wb[SHEET_NAME]
    ws.cell(row=row_num, column=COL_GTM_ID + 1).value = gtm_id
    wb.save(XLSX_PATH)


def main():
    targets = load_targets()
    still_missing = [(rn, name, domain) for rn, name, domain, gtm_id in targets
                     if not (isinstance(gtm_id, str) and gtm_id.startswith('GTM-'))]
    print(f'{len(still_missing)} rows still need GTM IDs\n')
    for rn, name, domain in still_missing:
        print(f'  Row {rn}: {name} | domain: {domain}')

    print()

    # Build indexes for both tokens
    indexes = {}
    for token_file in ('token.json', 'token_analytics.json'):
        token_path = os.path.join(SCRIPT_DIR, token_file)
        if not os.path.exists(token_path):
            print(f'Skipping {token_file} (not found)')
            continue
        label = token_file.replace('.json', '')
        print(f'Building index for {label}...')
        try:
            svc = get_service(token_file)
            indexes[label] = build_container_index(svc, label)
            print(f'  {len(indexes[label])} containers indexed\n')
        except Exception as e:
            print(f'  ERROR: {e}\n')

    print('\n=== Matching ===')
    found = 0
    for rn, name, domain in still_missing:
        matched_pub = None
        matched_how = None
        matched_token = None
        for token_label, index in indexes.items():
            pub, how = find_match(index, domain)
            if pub:
                matched_pub = pub
                matched_how = how
                matched_token = token_label
                break

        if matched_pub:
            print(f'  FOUND  Row {rn}: {name} → {matched_pub} via {matched_how} [{matched_token}]')
            writeback(rn, matched_pub)
            found += 1
        else:
            print(f'  MISS   Row {rn}: {name} | domain: {domain}')

    print(f'\n=== {found}/{len(still_missing)} recovered ===')


if __name__ == '__main__':
    main()
