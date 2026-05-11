"""
Fix gads_conversion_id for locations that have internal GAds API IDs instead of AW conversion IDs.

The AW conversion ID is the number in AW-XXXXXX/label (e.g. 635181883 from AW-635181883/xyz).
Internal API IDs are 10+ digits (e.g. 7521735325) and cannot be used as GTM conversionId.

Steps:
1. Find all locations with 10+ digit gads_conversion_id
2. Per unique gads_cid, fetch correct AW ID from tag snippets via GAds API
3. Update DB with correct conversion_id, appt_label, phone_label
4. Optionally queue gtm_setup for locations that already have GTM containers
"""
from __future__ import annotations

import os
import sys
import time
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from src.services.database import DatabaseService
from src.automation.setup import SetupAutomation

QUEUE_GTM = False  # set via --queue-gtm flag


def is_internal_id(val) -> bool:
    if not val:
        return False
    try:
        return len(str(int(float(str(val))))) > 9
    except (ValueError, TypeError):
        return False


def fetch_aw_labels(cid: str) -> dict:
    """Return {'conversion_id': str, 'appt_label': str, 'phone_label': str} or empty dict on failure."""
    try:
        sa = SetupAutomation(cid=cid, name='', city='')
        labels = sa.fetch_labels()
        return labels
    except Exception as e:
        print(f"  [error] fetch_labels({cid}): {e}")
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--queue-gtm', action='store_true',
                        help='Queue gtm_setup for locations with GTM containers after fixing DB')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would change without writing to DB')
    parser.add_argument('--cid', help='Process only this gads_cid (for testing)')
    args = parser.parse_args()

    db = DatabaseService()
    if not db.enabled:
        print('[fix] DB_ENABLED not true — check .env')
        sys.exit(1)

    # Fetch all locations with non-null gads_conversion_id
    res = db.client.table('locations').select(
        'id, name, gads_cid, gads_conversion_id, gads_appt_label, gads_phone_label, '
        'gtm_account_id, gtm_container_id'
    ).not_.is_('gads_conversion_id', 'null').execute()

    all_locs = res.data

    # Also include locations missing labels (even if conv_id looks OK)
    missing_labels = db.client.table('locations').select(
        'id, name, gads_cid, gads_conversion_id, gads_appt_label, gads_phone_label, '
        'gtm_account_id, gtm_container_id'
    ).not_.is_('gads_cid', 'null').not_.is_('gads_conversion_id', 'null').or_(
        'gads_appt_label.is.null,gads_phone_label.is.null'
    ).execute().data

    # Combine: 10+ digit IDs + missing labels (deduplicated by id)
    seen_ids: set[str] = set()
    affected = []
    for r in all_locs:
        if is_internal_id(r.get('gads_conversion_id')) and r['id'] not in seen_ids:
            affected.append(r)
            seen_ids.add(r['id'])
    for r in missing_labels:
        if r['id'] not in seen_ids:
            affected.append(r)
            seen_ids.add(r['id'])

    if args.cid:
        affected = [r for r in affected if str(r.get('gads_cid')) == args.cid]

    print(f'Affected locations: {len(affected)}')
    with_gtm = [r for r in affected if r.get('gtm_container_id')]
    print(f'  With GTM container: {len(with_gtm)}')
    print(f'  Without GTM container: {len(affected) - len(with_gtm)}')
    print()

    if not affected:
        print('Nothing to fix.')
        return

    # Group by gads_cid to minimize GAds API calls
    from collections import defaultdict
    by_cid: dict[str, list[dict]] = defaultdict(list)
    for r in affected:
        cid = str(r.get('gads_cid') or '')
        if cid:
            by_cid[cid].append(r)

    print(f'Unique CIDs to query: {len(by_cid)}')
    print()

    fixed = 0
    already_correct = 0
    failed = 0
    skipped = 0
    gtm_queued = 0

    for cid, locs in by_cid.items():
        loc_names = ', '.join(r['name'] for r in locs[:2])
        if len(locs) > 2:
            loc_names += f' +{len(locs)-2} more'
        print(f'CID {cid} ({loc_names})')

        labels = fetch_aw_labels(cid)
        aw_id = labels.get('conversion_id')
        appt_label = labels.get('appt_label')
        phone_label = labels.get('phone_label')

        if not aw_id:
            print(f'  [skip] No AW conversion ID found — leaving unchanged')
            skipped += len(locs)
            continue

        print(f'  AW ID: {aw_id}  appt: {appt_label}  phone: {phone_label}')

        for loc in locs:
            loc_id = loc['id']
            old_conv = str(loc.get('gads_conversion_id') or '')
            # Normalize to string for comparison
            new_conv = str(aw_id)
            if old_conv == new_conv:
                # Conversion ID already correct; still update labels if missing
                old_appt = str(loc.get('gads_appt_label') or '')
                old_phone = str(loc.get('gads_phone_label') or '')
                if (appt_label and appt_label != old_appt) or (phone_label and phone_label != old_phone):
                    print(f'  → {loc["name"]}: conv_id already correct, updating labels', end='')
                else:
                    print(f'  → {loc["name"]}: already correct [skip]')
                    already_correct += 1
                    continue
            else:
                print(f'  → {loc["name"]}: {old_conv} → {new_conv}', end='')

            if args.dry_run:
                print(' [dry-run]')
                fixed += 1
                continue

            updates: dict = {'gads_conversion_id': aw_id}
            if appt_label:
                updates['gads_appt_label'] = appt_label
            if phone_label:
                updates['gads_phone_label'] = phone_label

            try:
                db.client.table('locations').update(updates).eq('id', loc_id).execute()
                print(' ✓')
                fixed += 1
            except Exception as e:
                print(f' [error] {e}')
                failed += 1
                continue

            # Queue gtm_fix (force-recreate) if location has a GTM container
            if args.queue_gtm and loc.get('gtm_container_id') and not args.dry_run:
                try:
                    db.client.table('locations').update({
                        'automation_queued': 'gtm_fix',
                        'automation_status': 'queued',
                    }).eq('id', loc_id).execute()
                    print(f'    [queued] gtm_fix')
                    gtm_queued += 1
                except Exception as e:
                    print(f'    [queue error] {e}')

        # Throttle to avoid GAds quota
        time.sleep(0.5)

    print()
    print(f'Done. Fixed: {fixed}  Already correct: {already_correct}  Failed: {failed}  Skipped (no AW ID): {skipped}')
    if args.queue_gtm:
        print(f'GTM setup jobs queued: {gtm_queued}')
    if args.dry_run:
        print('(dry-run — no DB changes written)')


if __name__ == '__main__':
    main()
