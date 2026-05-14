#!/usr/bin/env python3
"""
Scan search_term_log for terms wasting budget across N+ locations
and promote them to config/negatives.txt as EXACT match negatives.

Thresholds (adjust as needed):
  --min-locations  5   term must appear across this many distinct locations
  --min-cost      50   total $ wasted (0 conversions) across all locations
  --days          30   look-back window
"""
import argparse
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from src.services.database import DatabaseService


def load_existing_negatives(negatives_path: Path) -> set[str]:
    """Return set of bare lowercase terms already in negatives.txt."""
    terms: set[str] = set()
    for line in negatives_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # strip notation: "phrase" -> phrase, [exact] -> exact, broad -> broad
        bare = re.sub(r'^[\["\']+|[\]"\']+$', '', line).lower().strip()
        if bare:
            terms.add(bare)
    return terms


def promote(min_locations: int, min_cost_usd: float, days: int, dry_run: bool) -> None:
    db = DatabaseService()
    if not db.enabled:
        print("DB not enabled — check .env")
        sys.exit(1)

    since = str(date.today() - timedelta(days=days))
    negatives_path = ROOT / 'config' / 'negatives.txt'
    existing = load_existing_negatives(negatives_path)

    # Find terms with 0 conversions, high cost, across many locations
    try:
        res = db.client.table("search_term_log") \
            .select("term, location_id, cost_micros, conversions") \
            .gte("run_date", since) \
            .eq("conversions", 0) \
            .execute()
        rows = res.data
    except Exception as e:
        print(f"DB query failed: {e}")
        sys.exit(1)

    # Aggregate by term
    term_stats: dict[str, dict] = {}
    for row in rows:
        t = row["term"].lower().strip()
        if t not in term_stats:
            term_stats[t] = {"locations": set(), "cost_usd": 0.0}
        term_stats[t]["locations"].add(row["location_id"])
        term_stats[t]["cost_usd"] += row["cost_micros"] / 1_000_000

    # Filter by thresholds and exclude existing negatives
    candidates = [
        (t, stats)
        for t, stats in term_stats.items()
        if len(stats["locations"]) >= min_locations
        and stats["cost_usd"] >= min_cost_usd
        and t not in existing
    ]
    candidates.sort(key=lambda x: x[1]["cost_usd"], reverse=True)

    if not candidates:
        print("No new network-wide negatives found.")
        return

    print(f"Found {len(candidates)} candidates (≥{min_locations} locations, ≥${min_cost_usd:.0f} wasted):\n")
    for term, stats in candidates[:30]:
        n_locs = len(stats["locations"])
        cost = stats["cost_usd"]
        print(f"  [{term}]  — {n_locs} locations, ${cost:.2f} wasted")

    if dry_run:
        print(f"\n[DRY RUN] Would append {len(candidates)} terms to {negatives_path}")
        return

    # Append to negatives.txt
    new_lines = [
        "",
        f"# --- Auto-promoted {date.today()} (≥{min_locations} locations, ≥${min_cost_usd:.0f} wasted) ---",
    ] + [f"[{t}]" for t, _ in candidates]

    with open(negatives_path, 'a') as f:
        f.write('\n'.join(new_lines) + '\n')

    print(f"\nAppended {len(candidates)} EXACT negatives to {negatives_path}")

    # Log to negative_history
    neg_rows = [{
        "location_id": None,
        "gads_cid":    "NETWORK",
        "term":        t,
        "match_type":  "EXACT",
        "level":       "shared_set",
        "reason":      "AUTO_PROMOTED",
        "is_dry_run":  False,
    } for t, _ in candidates]
    db.bulk_insert_negative_history(neg_rows)
    print(f"Logged {len(neg_rows)} entries to negative_history.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Promote network-wide wasted terms to negatives.txt")
    parser.add_argument("--min-locations", type=int, default=5,
                        help="Min distinct locations a term must appear across (default 5)")
    parser.add_argument("--min-cost",      type=float, default=50.0,
                        help="Min total $ wasted across all locations (default $50)")
    parser.add_argument("--days",          type=int, default=30,
                        help="Look-back window in days (default 30)")
    parser.add_argument("--dry-run",       action="store_true",
                        help="Preview without writing changes")
    args = parser.parse_args()
    promote(args.min_locations, args.min_cost, args.days, args.dry_run)
