"""
Batch GTM setup for 14 accounts that have GA4 IDs but no GTM containers.

Step 1: Creates a new GTM Account + Web container for each via Playwright
        (connects to Chrome at localhost:9222)
Step 2: Configures each container with LNM standard tags/triggers via API

Before running:
  /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --user-data-dir=/tmp/chrome_gtm_auto \
    --no-first-run https://tagmanager.google.com/

Then log in to analytics@leadsnearme.com in that Chrome window, then run:
  python batch_gtm_setup_14.py
  python batch_gtm_setup_14.py --dry-run
  python batch_gtm_setup_14.py --start 5   # resume from index 5
"""

import sys, os, re, json, time, argparse, pathlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from create_accounts import create_gtm_account
from setup_new_account import run as gtm_setup_run
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

RESULTS_FILE = os.path.join(os.path.dirname(__file__), 'batch_gtm_14_results.json')

# ── Account data ──────────────────────────────────────────────────────────────
# Fields: (cid, name, folder, url, ga4_id, phone, appt_label, phone_label)
# folder = derived from GAds account name owner tag
ACCOUNTS = [
    (9073616441,  "A1 Automotive",         "Vargas",     "autorepairgadsden.com",
     "G-22GXGF8F23", "4027824567",  "VDhXCLefspQcENmtkdkp",  "wSF0COGIu5QcENmtkdkp"),

    (6204635674,  "ABC Tire And Auto",      "Swain",      "autorepairradfordva.com",
     "G-8FGRX9PS0M",  "5406163520",  "tcGxCLDPu5QcEMiUs85C",  "MQ9ZCLvospQcEMiUs85C"),

    (3562579783,  "All Day Towing",         "Kersey",     "alldaytowing.net",
     "G-QEGLHBYV3W",  "5034967674",  "Me0fCKWozv0bENe57uYD",  "PMZJCNnmyv0bENe57uYD"),

    (2238673213,  "All Season Auto & Tire", "Hase",       "allseasontireco.com",
     "G-CTG20ZLMWM",  "7154895659",  "j15wCPK5spQcEIyi89pC",  "Ie2UCPLYpZQcEIyi89pC"),

    (8339086419,  "All Tech Automotive",    "West",       "all-techautomotive.com",
     "G-CG7HY2NMEB",  "9709991673",  "lGOOCNO8pZQcEJXooe9C",  "tgh0CM-lspQcEJXooe9C"),

    (5815014100,  "Auto Care Plus",         "Forsyth",    "autocareplus.ca",
     "G-2D1PL4CHV4",  "7052432386",  "-5gmCKvTpZQcEMGFqLs-",  "9pTeCK7TpZQcEMGFqLs-"),

    (6196305950,  "Elite Auto Solution",    "Nguyen",     "eliteautosolution.com",
     "G-MGBNJES9D4",  "2145508042",  "1HjkCJjUspQcENTnhsVC",  "d6BpCMvAu5QcENTnhsVC"),

    (9639603356,  "Gibbs Automotive",       "Gibbs",      "gibbsautomotive.com",
     "G-YG53J6LQ5H",  "7703437355",  "so_NCKzapZQcEKLZi-VC",  "_TqCCPzWpZQcEKLZi-VC"),

    (8753501556,  "Hay's Tire & Auto",      "Hay",        "haystireandauto.com",
     "G-CT6TNQ4Z9K",  "2074072026",  "nIi4CNO7spQcEN2As88p",  "iYIYCIOou5QcEN2As88p"),

    (2103880617,  "Minnick Automotive",     "Minnick",    "minnickautoservice.com",
     "G-9ZQPKN8JBR",  "2253510381",  "j3lTCPXRspQcELDWmO5C",  "q4L9CK3OspQcELDWmO5C"),

    (8616181301,  "Poor Boys' Enterprises", "Petre",      "poorboysenterprises.com",
     "G-81KFKFNVZL",  "7173698365",  "PYwgCIrEu5QcENiJhMwB",  "T0P2CKTGu5QcENiJhMwB"),

    (9904523829,  "PW Auto Clinic",         "Garcia",     "pwautoclinic.com",
     "G-P8XMP73W5X",  "3312811743",  "hq9cCJ2ku5QcEKr5-aI-",  "3wtOCIGju5QcEKr5-aI-"),

    (3770205662,  "Scott's Auto",           "Scott",      "scottsautolitchfield.com",
     "G-54BJMVNCT5",  "3202447526",  "XEAiCPjJu5QcELbCqc8o",  "WOrmCPvJu5QcELbCqc8o"),

    (4291889246,  "Stagecoach Auto Repair", "Lowery",     "stagecoachautorepair.com",
     "G-5R5ELXRMS1",  "9315608174",  "T0urCL-3u5QcEK2-guRC",  "xn-uCMK3u5QcEK2-guRC"),
]

CDP_URL = 'http://localhost:9222'


def load_results():
    if pathlib.Path(RESULTS_FILE).exists():
        return json.loads(pathlib.Path(RESULTS_FILE).read_text())
    return {}


def save_results(results):
    pathlib.Path(RESULTS_FILE).write_text(json.dumps(results, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--start', type=int, default=0, help='Resume from this index (0-based)')
    parser.add_argument('--setup-only', action='store_true', help='Skip container creation, only run GTM setup (needs GTM IDs in results file)')
    args = parser.parse_args()

    results = load_results()

    if not args.setup_only and not args.dry_run:
        # Step 1: Create GTM containers via Playwright
        print("=== Step 1: Creating GTM containers ===\n")
        with sync_playwright() as p:
            for attempt in range(10):
                try:
                    browser = p.chromium.connect_over_cdp(CDP_URL)
                    context = browser.contexts[0]
                    print("Connected to Chrome.\n")
                    break
                except Exception as e:
                    if attempt == 9:
                        print(f"ERROR: Could not connect to Chrome at {CDP_URL}")
                        print("Launch Chrome first with remote debugging enabled.")
                        sys.exit(1)
                    time.sleep(2)

            for i, acct in enumerate(ACCOUNTS):
                if i < args.start:
                    continue
                cid, name, folder, url, ga4_id, phone, appt_lbl, phone_lbl = acct
                key = str(cid)

                if key in results and results[key].get('gtm_id'):
                    print(f"[{i+1}/14] SKIP {name} — already has GTM ID: {results[key]['gtm_id']}")
                    continue

                account_name = f"{name} - {folder}"
                print(f"[{i+1}/14] Creating GTM account+container: {account_name} | {url}")
                gtm_id = create_gtm_account(context, account_name, url)

                if gtm_id:
                    print(f"  → {gtm_id}\n")
                    results[key] = {
                        'cid': cid, 'name': name, 'url': url, 'ga4_id': ga4_id,
                        'phone': phone, 'appt_label': appt_lbl, 'phone_label': phone_lbl,
                        'gtm_id': gtm_id, 'setup_done': False,
                    }
                    save_results(results)
                else:
                    print(f"  → FAILED — skipping setup for this account\n")
                    results[key] = {'cid': cid, 'name': name, 'gtm_id': None, 'setup_done': False}
                    save_results(results)

    # Step 2: Configure each container with LNM standard setup
    print("\n=== Step 2: Configuring GTM containers ===\n")
    for acct in ACCOUNTS:
        cid, name, folder, url, ga4_id, phone, appt_lbl, phone_lbl = acct
        key = str(cid)
        r = results.get(key, {})
        gtm_id = r.get('gtm_id')

        if not gtm_id:
            print(f"SKIP {name} — no GTM ID")
            continue
        if r.get('setup_done') and not args.setup_only:
            print(f"SKIP {name} — setup already done ({gtm_id})")
            continue

        print(f"Setting up {name} ({gtm_id}) ...")
        if args.dry_run:
            print(f"  [DRY RUN] gtm_setup_run(gtm_id={gtm_id}, name={name}, ga4={ga4_id}, "
                  f"cid={cid}, appt={appt_lbl}, sched=autoops, phone=[({phone}, {phone_lbl})])")
            continue

        try:
            gtm_setup_run(
                gtm_id=gtm_id,
                client_name=name,
                ga4_id=ga4_id,
                gads_id=cid,
                appt_label=appt_lbl,
                scheduler='autoops',
                phone_pairs=[(phone, phone_lbl)],
            )
            results[key]['setup_done'] = True
            save_results(results)
            print(f"  → Done\n")
        except Exception as e:
            print(f"  → ERROR: {e}\n")

    print("\n=== Summary ===")
    for acct in ACCOUNTS:
        cid, name = acct[0], acct[1]
        r = results.get(str(cid), {})
        gtm = r.get('gtm_id', 'NOT CREATED')
        done = 'SETUP DONE' if r.get('setup_done') else 'setup pending'
        print(f"  {name:45s}  {gtm}  {done}")


if __name__ == '__main__':
    main()
