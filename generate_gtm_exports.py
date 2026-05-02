"""
GTM Bulk Export Generator — LNM Standard v1.0

Reads the XLSX and generates a GTM container JSON export for each row
that has a GA4 Measurement ID and GAds conversion data filled in.

Output: one JSON file per row → GTM-Automation/exports/{safe_name}_row{N}.json

Usage:
    python generate_gtm_exports.py             # All tiers with data
    python generate_gtm_exports.py --tier 2    # Tier 2 only
    python generate_gtm_exports.py --row 138   # Single row
    python generate_gtm_exports.py --dry-run   # Preview without writing
"""

import re
import os
import json
import argparse
import openpyxl
from datetime import date

# ── Config ────────────────────────────────────────────────────────────────────
XLSX_PATH  = '/Users/alexchiu/Downloads/GTM Bulk Setup OktoRocket (4).xlsx'
SHEET_NAME = 'AA Client Import List (1)'
OUT_DIR    = os.path.join(os.path.dirname(__file__), 'exports')

# Column indices (0-based)
COL_TIER        = 0
COL_NAME        = 1
COL_SCHED       = 21
COL_PHONE       = 22
COL_GA4_ID      = 23
COL_GADS_ID     = 25
COL_LABEL_APPT  = 26
COL_LABEL_PHONE = 27
COL_MULTI_PHONE = 32   # JSON array of extra phone numbers


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_store_name(client_name, campaign_name=None):
    GENERIC = {'main', 'primary', 'default', 'location', 'store', 'dfw', 'n/a'}
    SKIP_WORDS = {'auto', 'automotive', 'repair', 'service', 'center', 'care', 'shop',
                  'tire', 'garage', 'motors', 'motor', 'llc', 'inc', 'and', '&', 'the',
                  '1', 'of', 'at', 'in', 'for', 'n', 'by', 'st', 'ave', 'blvd'}
    name = str(client_name or '').strip()

    def _clean(s):
        s = re.sub(r'<[^>]+>', '', s)
        return s.replace('/', '').replace('  ', ' ').strip()

    def _valid(s):
        s = s.strip()
        if not s or s.lower() in GENERIC:
            return False
        if re.search(r'<[^>]+>', s):
            return False
        sl = s.lower()
        if sl.startswith('lnm') or sl in {'leads near me', 'general auto repair',
                                           'general auto repair services',
                                           'main campaign', 'general & euro'}:
            return False
        return True

    def _filter_words(text):
        return [w for w in text.split() if w.lower() not in SKIP_WORDS]

    if ' - ' in name:
        location = name.split(' - ')[-1].strip()
        cleaned = _clean(location)
        if _valid(cleaned):
            return cleaned

    paren_match = re.search(r'\(([^)]+)\)', name)
    if paren_match:
        paren_words = _filter_words(paren_match.group(1))
        if paren_words and paren_words[0].lower() not in GENERIC and len(paren_words[0]) > 1:
            candidate = _clean(' '.join(paren_words[:3]))
            if _valid(candidate):
                return candidate

    if campaign_name and ' - ' in str(campaign_name):
        camp_city = str(campaign_name).split(' - ')[-1].strip()
        cleaned = _clean(camp_city)
        if cleaned and _valid(cleaned):
            return cleaned

    name_no_paren = re.sub(r'\([^)]*\)', '', name).strip()
    words = _filter_words(name_no_paren)
    if words:
        return _clean(' '.join(words[:2]))

    return _clean(name_no_paren) or _clean(name)


def get_scheduler_info(scheduler_type):
    """
    Returns (event_name, trigger_label) for the appointment booking scheduler.
    event_name  → the dataLayer/custom event GTM listens for
    trigger_label → human-readable label for the CE trigger name
    """
    s = str(scheduler_type or '').lower()
    if 'shop genie' in s or 'shopgenie' in s:
        return 'appointment_booked', 'Shop Genie'
    if 'autoops' in s or 'auto ops' in s:
        return 'ao-appointment-booked', 'AutoOps'
    # OktoRocket / default
    return 'dc-service-booked', 'OktoRocket'


def normalize_phone(raw):
    """Strip tel: prefix and non-digits."""
    return re.sub(r'\D', '', str(raw or ''))


def safe_filename(name):
    """Convert store name to a filesystem-safe string."""
    return re.sub(r'[^\w\-]', '_', name).strip('_')


# ── GTM JSON builder ──────────────────────────────────────────────────────────

def build_gtm_export(client_name, store_name, ga4_id, gads_id,
                     appt_label, phone_label, phones, scheduler_type):
    """
    Build a complete GTM container export dict.

    Tags:
      1  GA4 - Configuration              (fires: All Pages)
      2  GA4 - Event - {appt_event}       (fires: CE appt trigger)
      3  GA4 - Event - phone_click        (fires: CL trigger(s))  — only if phones
      4  GAds - {store} - Booked_Appointment  (fires: CE appt trigger)
      5+ GAds - {store} - Phone_Click     (fires: CL trigger(s))  — only if phones

    Triggers:
      1  CE  - {Scheduler} - Appointment Booked
      2  CL  - Phone Click - {phone}     (one per phone number)
      3  All Pages
    """
    appt_event, sched_label = get_scheduler_info(scheduler_type)
    today = date.today().strftime('%Y-%m-%d')
    gads_id_str = str(int(gads_id))  # ensure no decimal

    has_phone = bool(phones and phone_label)

    # ── Triggers ──────────────────────────────────────────────────────────────
    # Trigger IDs: 1 = CE appt, 2..N = CL phone(s), N+1 = All Pages
    triggers = []

    # 1. Custom Event — appointment booked
    triggers.append({
        "accountId": "0", "containerId": "0",
        "triggerId": "1",
        "name": f"CE - {sched_label} - Appointment Booked",
        "type": "CUSTOM_EVENT",
        "customEventFilter": [{
            "type": "EQUALS",
            "parameter": [
                {"type": "TEMPLATE", "key": "arg0", "value": "{{_event}}"},
                {"type": "TEMPLATE", "key": "arg1", "value": appt_event}
            ]
        }]
    })

    # 2. Link Click — one trigger per phone number
    cl_trigger_ids = []
    if has_phone:
        for idx, phone in enumerate(phones, start=2):
            tid = str(idx)
            cl_trigger_ids.append(tid)
            triggers.append({
                "accountId": "0", "containerId": "0",
                "triggerId": tid,
                "name": f"CL - Phone Click - {phone}",
                "type": "LINK_CLICK",
                "filter": [{
                    "type": "CONTAINS",
                    "parameter": [
                        {"type": "TEMPLATE", "key": "arg0", "value": "{{Click URL}}"},
                        {"type": "TEMPLATE", "key": "arg1", "value": phone}
                    ]
                }],
                "parameter": [
                    {"type": "BOOLEAN",  "key": "waitForTags",       "value": "true"},
                    {"type": "BOOLEAN",  "key": "checkValidation",    "value": "true"},
                    {"type": "TEMPLATE", "key": "waitForTagsTimeout", "value": "2000"}
                ]
            })

    # Last trigger: All Pages
    all_pages_id = str(len(triggers) + 1)
    triggers.append({
        "accountId": "0", "containerId": "0",
        "triggerId": all_pages_id,
        "name": "All Pages",
        "type": "PAGEVIEW"
    })

    # ── Tags ──────────────────────────────────────────────────────────────────
    tags = []
    tag_id = 1

    # Tag 1: GA4 Configuration
    tags.append({
        "accountId": "0", "containerId": "0",
        "tagId": str(tag_id),
        "name": "GA4 - Configuration",
        "type": "gaawc",
        "parameter": [
            {"type": "TEMPLATE", "key": "measurementId", "value": ga4_id}
        ],
        "firingTriggerId": [all_pages_id],
        "tagFiringOption": "ONCE_PER_EVENT",
        "monitoringMetadata": {"type": "MAP"},
        "consentSettings": {"consentStatus": "NOT_SET"}
    })
    tag_id += 1

    # Tag 2: GA4 Event — appointment
    tags.append({
        "accountId": "0", "containerId": "0",
        "tagId": str(tag_id),
        "name": f"GA4 - Event - {appt_event}",
        "type": "gaawe",
        "parameter": [
            {"type": "TAG_REFERENCE", "key": "gaSettings",            "value": "GA4 - Configuration"},
            {"type": "TEMPLATE",      "key": "eventName",             "value": appt_event},
            {"type": "TEMPLATE",      "key": "measurementIdOverride", "value": ga4_id}
        ],
        "firingTriggerId": ["1"],
        "tagFiringOption": "ONCE_PER_EVENT",
        "monitoringMetadata": {"type": "MAP"},
        "consentSettings": {"consentStatus": "NOT_SET"}
    })
    tag_id += 1

    # Tag 3: GA4 Event — phone_click (only if phones)
    if has_phone:
        tags.append({
            "accountId": "0", "containerId": "0",
            "tagId": str(tag_id),
            "name": "GA4 - Event - phone_click",
            "type": "gaawe",
            "parameter": [
                {"type": "TAG_REFERENCE", "key": "gaSettings",            "value": "GA4 - Configuration"},
                {"type": "TEMPLATE",      "key": "eventName",             "value": "phone_click"},
                {"type": "TEMPLATE",      "key": "measurementIdOverride", "value": ga4_id}
            ],
            "firingTriggerId": cl_trigger_ids,
            "tagFiringOption": "ONCE_PER_EVENT",
            "monitoringMetadata": {"type": "MAP"},
            "consentSettings": {"consentStatus": "NOT_SET"}
        })
        tag_id += 1

    # Tag: GAds Booked_Appointment
    tags.append({
        "accountId": "0", "containerId": "0",
        "tagId": str(tag_id),
        "name": f"GAds - {store_name} - Booked_Appointment",
        "type": "awct",
        "parameter": [
            {"type": "INTEGER",  "key": "conversionId",    "value": gads_id_str},
            {"type": "TEMPLATE", "key": "conversionLabel", "value": appt_label},
            {"type": "TEMPLATE", "key": "conversionValue", "value": "65"},
            {"type": "TEMPLATE", "key": "currencyCode",    "value": "USD"},
            {"type": "BOOLEAN",  "key": "remarketingOnly", "value": "false"},
            {"type": "BOOLEAN",  "key": "enabledMd",       "value": "true"}
        ],
        "firingTriggerId": ["1"],
        "tagFiringOption": "ONCE_PER_EVENT",
        "monitoringMetadata": {"type": "MAP"},
        "consentSettings": {"consentStatus": "NOT_SET"}
    })
    tag_id += 1

    # Tag: GAds Phone_Click (only if phones)
    if has_phone:
        tags.append({
            "accountId": "0", "containerId": "0",
            "tagId": str(tag_id),
            "name": f"GAds - {store_name} - Phone_Click",
            "type": "awct",
            "parameter": [
                {"type": "INTEGER",  "key": "conversionId",    "value": gads_id_str},
                {"type": "TEMPLATE", "key": "conversionLabel", "value": phone_label},
                {"type": "TEMPLATE", "key": "conversionValue", "value": "10"},
                {"type": "TEMPLATE", "key": "currencyCode",    "value": "USD"},
                {"type": "BOOLEAN",  "key": "remarketingOnly", "value": "false"},
                {"type": "BOOLEAN",  "key": "enabledMd",       "value": "false"}
            ],
            "firingTriggerId": cl_trigger_ids,
            "tagFiringOption": "ONCE_PER_EVENT",
            "monitoringMetadata": {"type": "MAP"},
            "consentSettings": {"consentStatus": "NOT_SET"}
        })

    return {
        "exportFormatVersion": 2,
        "exportTime": f"{today} 00:00:00",
        "containerVersion": {
            "path": "accounts/0/containers/0/versions/0",
            "accountId": "0",
            "containerId": "0",
            "containerVersionId": "0",
            "container": {
                "path": "accounts/0/containers/0",
                "accountId": "0",
                "containerId": "0",
                "name": client_name,
                "publicId": "GTM-XXXXXXX",
                "usageContext": ["WEB"]
            },
            "builtInVariable": [
                {"accountId": "0", "containerId": "0", "type": "CLICK_URL",     "name": "Click URL"},
                {"accountId": "0", "containerId": "0", "type": "CLICK_ELEMENT", "name": "Click Element"}
            ],
            "tag": tags,
            "trigger": triggers,
            "variable": []
        }
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def run(tier=None, row_filter=None, dry_run=False):
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    ws = wb[SHEET_NAME]

    if not dry_run:
        os.makedirs(OUT_DIR, exist_ok=True)

    generated = 0
    skipped_no_data = 0
    skipped_tier = 0

    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        row_tier    = row[COL_TIER]
        client_name = row[COL_NAME]
        sched       = row[COL_SCHED]
        phone_raw   = row[COL_PHONE]
        ga4_id      = row[COL_GA4_ID]
        gads_id     = row[COL_GADS_ID]
        appt_label  = row[COL_LABEL_APPT]
        phone_label = row[COL_LABEL_PHONE]
        multi_raw   = row[COL_MULTI_PHONE]

        if not client_name:
            continue

        # Row filter
        if row_filter is not None and i != row_filter:
            continue

        # Tier filter
        if tier is not None:
            try:
                if float(str(row_tier or '')) != float(tier):
                    skipped_tier += 1
                    continue
            except (ValueError, TypeError):
                skipped_tier += 1
                continue

        # Must have GA4 ID and GAds conversion data
        if not ga4_id or not gads_id or not appt_label:
            skipped_no_data += 1
            continue

        # Collect phone numbers
        phones = []
        p = normalize_phone(phone_raw)
        if p:
            phones.append(p)
        if multi_raw:
            try:
                for extra in json.loads(str(multi_raw)):
                    ep = normalize_phone(extra)
                    if ep and ep not in phones:
                        phones.append(ep)
            except Exception:
                pass

        store_name = get_store_name(client_name)
        export = build_gtm_export(
            client_name=client_name,
            store_name=store_name,
            ga4_id=str(ga4_id),
            gads_id=gads_id,
            appt_label=str(appt_label),
            phone_label=str(phone_label) if phone_label else None,
            phones=phones,
            scheduler_type=sched,
        )

        appt_event, sched_label = get_scheduler_info(sched)
        phone_note = f"  phones={phones}" if phones else "  no phone"
        print(f"Row {i:3d}: '{client_name}' → store='{store_name}' | ga4={ga4_id} | "
              f"sched={sched_label} | event={appt_event}{phone_note}")

        if not dry_run:
            fname = f"{safe_filename(store_name)}_row{i}.json"
            fpath = os.path.join(OUT_DIR, fname)
            with open(fpath, 'w') as f:
                json.dump(export, f, indent=2)
            print(f"         → {fpath}")

        generated += 1

    print(f"\n=== Done: {generated} exports {'previewed' if dry_run else 'written'}, "
          f"{skipped_no_data} skipped (missing data), {skipped_tier} skipped (wrong tier) ===")
    if not dry_run and generated:
        print(f"    Output directory: {OUT_DIR}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tier',    default=None, help='Only this tier (e.g. 2, 3, 3.5)')
    parser.add_argument('--row',     type=int, default=None, help='Single XLSX row')
    parser.add_argument('--dry-run', action='store_true', help='Preview without writing files')
    args = parser.parse_args()
    run(tier=args.tier, row_filter=args.row, dry_run=args.dry_run)
