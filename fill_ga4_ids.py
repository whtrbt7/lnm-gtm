"""
Fetch all GA4 properties accessible to the authenticated account,
match them to LNM locations by domain/name, and write ga4_measurement_id to Supabase.

Run after: python get_ga4_token.py
Usage:     python fill_ga4_ids.py --token-file token_ga4.json [--dry-run]
           python fill_ga4_ids.py --token-file token_reports.json [--dry-run]
           (run once per account; already-filled rows are skipped)
"""
import os, re, requests, argparse
from difflib import SequenceMatcher
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

KEY = os.environ["SUPABASE_SERVICE_KEY"]
SB  = os.getenv("SUPABASE_URL", "http://127.0.0.1:54321")
SBH = {"apikey": KEY, "Authorization": "Bearer " + KEY}

TARGET_CIDS = "3460959396,7298926500,3381401866,7653236962,5051989395,2642972164,8346784396,1417582770,8668256246,1877137403,4362666156,5832788080,1967311992,4965974148,4773596891,1446082468,1889441641,2778577395,9703735958,9279448444,3917057054,1527228456,5064001676,2292602443,8353585562,2024577846,7302316697,2013645649,3652346952,4220135994,1886788303,3530212596,5201532990,1192122062,8560044401,5323680470,3085028786,8314243729,7568215700,9467089594,2063999496,1236692152,9048264007,4906264519,9552331807,8710004339,6620794848"
FAKE_GA4    = {"G-PRELOADER", "G-GALLERY", "G-PZ2GFM9NED"}
GA4_SCOPE   = "https://www.googleapis.com/auth/analytics.readonly"


def get_service(token_file):
    creds = Credentials.from_authorized_user_file(token_file, [GA4_SCOPE])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build('analyticsadmin', 'v1beta', credentials=creds)


def normalize_domain(url):
    if not url:
        return ""
    url = re.sub(r'^https?://', '', url.strip().lower()).rstrip('/')
    return re.sub(r'^www\.', '', url).split('/')[0]


def name_sim(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def fetch_all_properties(svc):
    results = []
    page_token = None
    while True:
        kwargs = {"pageSize": 200}
        if page_token:
            kwargs["pageToken"] = page_token
        resp = svc.accountSummaries().list(**kwargs).execute()
        for acct in resp.get('accountSummaries', []):
            for prop in acct.get('propertySummaries', []):
                prop_id   = prop['property'].replace('properties/', '')
                prop_name = prop.get('displayName', '')
                try:
                    streams = svc.properties().dataStreams().list(
                        parent=f'properties/{prop_id}', pageSize=10
                    ).execute()
                    for stream in streams.get('dataStreams', []):
                        if stream.get('type') != 'WEB_DATA_STREAM':
                            continue
                        web = stream.get('webStreamData', {})
                        mid = web.get('measurementId', '')
                        uri = web.get('defaultUri', '')
                        if mid:
                            results.append({
                                'prop_name':      prop_name,
                                'measurement_id': mid,
                                'domain':         normalize_domain(uri),
                            })
                except Exception as e:
                    print(f'  [warn] streams for {prop_name}: {e}')
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return results


def fetch_locations():
    r = requests.get(f"{SB}/rest/v1/locations",
        params={"gads_cid": f"in.({TARGET_CIDS})", "select": "id,name,gads_cid,url,ga4_measurement_id", "limit": "200"},
        headers=SBH, timeout=10)
    return r.json()


def update_ga4(loc_id, ga4_id, dry_run):
    if dry_run:
        return 200
    r = requests.patch(f"{SB}/rest/v1/locations",
        params={"id": f"eq.{loc_id}"},
        headers={**SBH, "Content-Type": "application/json", "Prefer": "return=representation"},
        json={"ga4_measurement_id": ga4_id},
        timeout=10)
    return r.status_code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--token-file', default='token_ga4.json')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print(f"Using token: {args.token_file}")
    print("Fetching GA4 properties from Google Analytics Admin API...")
    svc   = get_service(args.token_file)
    props = fetch_all_properties(svc)
    print(f"  Found {len(props)} web data streams")

    domain_map = {p['domain']: p for p in props if p['domain']}

    print("\nFetching locations from Supabase...")
    locs    = fetch_locations()
    missing = [l for l in locs if not l.get('ga4_measurement_id') or l['ga4_measurement_id'] in FAKE_GA4]
    print(f"  {len(locs)} total | {len(missing)} still missing GA4")

    if not missing:
        print("Nothing to do.")
        return

    matched, unmatched = [], []

    for loc in missing:
        loc_domain = normalize_domain(loc.get('url', ''))
        loc_name   = loc.get('name', '')

        # 1. Exact domain
        if loc_domain and loc_domain in domain_map:
            p = domain_map[loc_domain]
            matched.append((loc, p['measurement_id'], f"domain:{loc_domain}"))
            continue

        # 2. Partial domain
        hit = next(((d, p) for d, p in domain_map.items() if d and loc_domain and (loc_domain in d or d in loc_domain)), None)
        if hit:
            matched.append((loc, hit[1]['measurement_id'], f"domain~:{hit[0]}"))
            continue

        # 3. Name similarity ≥ 0.72
        best_score, best_prop = 0.0, None
        for p in props:
            s = name_sim(loc_name, p['prop_name'])
            if s > best_score:
                best_score, best_prop = s, p
        if best_score >= 0.72 and best_prop:
            matched.append((loc, best_prop['measurement_id'], f"name~{best_score:.2f}:{best_prop['prop_name']}"))
        else:
            unmatched.append(loc)

    print(f"\nMATCHED ({len(matched)}):")
    for loc, ga4, note in sorted(matched, key=lambda x: x[0]['name']):
        print(f"  {ga4:20s}  {loc['name'][:45]:<45}  [{note}]")

    print(f"\nUNMATCHED ({len(unmatched)}):")
    for loc in sorted(unmatched, key=lambda x: x['name']):
        print(f"  {loc['name'][:45]:<45}  {loc.get('url','')[:40]}")

    if not matched:
        print("\nNothing to write.")
        return

    tag = "[DRY RUN] " if args.dry_run else ""
    print(f"\n{tag}Writing {len(matched)} GA4 IDs to Supabase...")
    for loc, ga4, note in matched:
        status = update_ga4(loc['id'], ga4, args.dry_run)
        print(f"  {'OK' if status in (200,201) else 'ERR '+str(status)}  {ga4}  {loc['name'][:40]}")


if __name__ == '__main__':
    main()
