# LNM GTM Automation — Audit Fixes & 3-Month Roadmap

## Fixes Applied (2026-04-28)

| File | Change |
|------|--------|
| `setup_new_account.py` | Added `build_conversion_linker_tag()` + wired into `run()` before GA4 config tag |
| `setup_new_account.py` | Removed redundant `measurementIdOverride` from both GA4 event tag builders |
| `push_gtm_setup.py` | Added `build_conversion_linker_tag_body()` + wired into live push loop |
| `push_gtm_setup.py` | Removed redundant `measurementIdOverride` from GA4 event tag builders |
| `push_gtm_setup.py` | Removed dead `COL_GTM_ID = 27` (collided with `COL_LABEL_PHONE = 27`) |
| `inject_wordpress.py` | Fixed `lstrip` URL bug — replaced with `re.sub(r'^https?://', ...)` |

### Why Conversion Linker matters

GAds conversion tags (`type: awct`) require a Conversion Linker tag firing on All Pages to capture the GCLID from the URL. Without it, Google Ads cannot attribute conversions to the correct click. The tag fires `ONCE_PER_LOAD` (not `ONCE_PER_EVENT`) — one capture per page load is all that's needed.

### Why measurementIdOverride was removed

GA4 event tags already reference the config tag via `gaSettings: TAG_REFERENCE`. Adding `measurementIdOverride` on top means if the GA4 ID ever changes, it must be updated in two places per tag. The config tag reference is the single source of truth.

---

## Month 1 — Reliability + Observability

### 1. Post-injection site verification

**File:** `inject_wordpress.py`

After marking `gtm_injected_at` in Supabase, fetch `https://{domain}/` and confirm `GTM-XXXXX` appears in the rendered HTML. If not found, set `gtm_connected = False` and log the failure.

Right now the script trusts the HTTP 200 from the WP admin POST with no proof the script actually renders on the live site.

```python
def verify_gtm_live(domain: str, gtm_id: str) -> bool:
    try:
        resp = requests.get(f"https://{domain}/", timeout=15)
        return gtm_id in resp.text
    except requests.RequestException:
        return False
```

Call after `mark_injected()`. If `False`, print a warning and set `gtm_connected = False` in the patch payload.

---

### 2. Supabase `gtm_setup_status` enum

**Migration:** add column to `locations` table

Replace the current patchwork of boolean columns (`gtm_connected`, `gtm_injected_at`) with a single state machine:

```
no_container → has_container → tags_pushed → script_injected → verified_live
```

Each script transitions exactly one step forward. A single Supabase query then surfaces every stuck location:

```sql
SELECT name, url, gtm_setup_status
FROM locations
WHERE gtm_setup_status != 'verified_live'
  AND churned = false
ORDER BY gtm_setup_status;
```

---

### 3. CallRail backfill script

**New file:** `match_callrail_by_url.py`

303 locations have no `phone_number` / `gads_phone_label` → no phone tags created.

Steps:
1. Fetch all CallRail trackers via CallRail API (already have token in `reference_api_tokens.md`)
2. Fuzzy-match tracker source URL to Supabase `locations.url` by domain
3. Write matched `phone_number` and `gads_phone_label` back to Supabase
4. Re-run `push_gtm_setup.py --force-recreate` for those rows to create CL triggers + phone tags

Target: clear the 303 unmatched from `2026-04-26-callrail-unmatched.md`.

---

## Month 2 — Scale + Coverage

### 4. Publish GTM workspaces after push

**Files:** `push_gtm_setup.py`, `setup_new_account.py`

Tags pushed via API land in a workspace but are never published. The container serving live traffic has none of the new tags until someone manually publishes in the GTM UI.

Add after all tags are created:

```python
def publish_workspace(service, acct_id, ctr_id, ws_id, description):
    parent = f"accounts/{acct_id}/containers/{ctr_id}/workspaces/{ws_id}"
    return _api_call_with_retry(
        lambda: service.accounts().containers().workspaces().create_version(
            path=parent,
            body={"name": description, "notes": "LNM standard setup — automated"}
        ).execute()
    )
```

Then publish the version immediately after creation. Add `--no-publish` flag to skip for dry-run or staged rollouts.

---

### 5. Token expiry health check

**New file:** `check_tokens.py`

`token.json` and `token_analytics.json` expire silently — the bulk push just fails mid-run with a cryptic auth error.

Check both tokens on a daily cron, send Telegram alert if either expires within 48 hours:

```python
from datetime import datetime, timezone

def check_token_expiry(path):
    with open(path) as f:
        data = json.load(f)
    expiry = datetime.fromisoformat(data.get('expiry', ''))
    delta = expiry - datetime.now(timezone.utc)
    return delta.total_seconds() / 3600  # hours remaining
```

Telegram bot already configured — use `@Whtrbt7plexbot` alert pattern from existing setup.

---

### 6. Per-client DC Bookings shopId

**File:** `inject_dcbookings.py`

`DC_IFRAME` hardcodes `shopId=66843b3597c22ed870010841` and `domain=lanier`. Will inject the wrong booking widget on every non-Lanier client.

Fix:
1. Add `dc_shop_id` (string) and `dc_domain_slug` (string) columns to Supabase `locations`
2. Read both at injection time from `fetch_location()`
3. Replace hardcoded values with the fetched fields
4. Raise `SystemExit` if either field is null — no silent wrong injection

---

## Month 3 — Full Pipeline Automation

### 7. Single-command client onboarding

**New file:** `onboard_client.py`

```
python onboard_client.py --gads-cid 1234567890
```

Chains the full pipeline:

1. `push_gtm_setup.py` logic — create triggers + tags (including Conversion Linker)
2. Publish workspace
3. `inject_wordpress.py` logic — install GTM snippet on WP
4. Site verification fetch
5. Supabase status → `verified_live`
6. Telegram confirmation: `"GTM live: {name} ({gtm_id}) ✓"`

Zero manual steps per client after data is in Supabase.

---

### 8. Weekly GTM audit script

**New file:** `audit_gtm_containers.py`

Weekly cron. For each active location with `gtm_setup_status = verified_live`:

1. List tags in live container version
2. Assert presence of: `Conversion Linker`, `GA4 - Configuration`, `GA4 - Event - *`, `GAds - * - Booked_Appointment`
3. Assert `All Pages` trigger exists
4. Report missing items to Telegram grouped by severity

Catches drift from clients or agencies manually editing containers after setup.

---

### 9. Scheduler-type auto-detection

**New file:** `detect_scheduler.py`

`scheduler_type` is a manual XLSX column — wrong value = wrong event name = broken conversion tracking.

Fetch `https://{domain}/` and look for JS signatures:

| Scheduler | Signature to detect |
|-----------|-------------------|
| AutoOps | `ao-appointment-booked` or `autoops` in page source |
| ShopGenie | `appointment_booked` or `shopgenie` in page source |
| OktoRocket | `dc-service-booked` or `oktorocket` or `dcPortal` in page source |

Write detected `scheduler_type` to Supabase. Flag conflicts (multiple signatures found) for manual review.

Run before `push_gtm_setup.py` as a pre-flight check, or as a standalone batch to clean up the existing dataset.
