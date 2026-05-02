# LNM GTM Setup Guide

Full workflow for setting up Google Tag Manager for a new LNM client.

---

## Prerequisites

**Before starting, you need:**

| Field | Where to find it |
|---|---|
| Google Ads CID | GAds UI → account selector, or the `gads_cid` column in Supabase |
| GA4 Measurement ID (`G-XXXXXXXX`) | GA4 → Admin → Data Streams → stream name |
| GAds Conversion ID (integer) | GAds → Goals → Conversions → select conversion → Tag setup → `AW-XXXXXXXXX` (the number) |
| Appointment booking label | Same conversion page — string after the `/` in the tag snippet |
| Phone click label | Same location, for the phone click conversion |
| Scheduler type | `autoops` / `shopgenie` / `oktorocket` |
| Phone number | Client's main tracking number (digits only OK) |

**All fields must be saved to the Supabase `locations` table before running Step 2.**

---

## Step 0 — Populate Supabase

If the client row exists but fields are missing, update via the REST API or Supabase Studio:

```bash
curl -X PATCH "http://localhost:54321/rest/v1/locations?gads_cid=eq.YOUR_CID" \
  -H "apikey: YOUR_SUPABASE_SERVICE_KEY" \
  -H "Authorization: Bearer YOUR_SUPABASE_SERVICE_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "ga4_id": "G-XXXXXXXXXX",
    "gads_conversion_id": "123456789",
    "gads_dc_label": "APPT_LABEL_HERE",
    "gads_phone_label": "PHONE_LABEL_HERE",
    "scheduler_type": "autoops",
    "phone_number": "8005551234"
  }'
```

Verify the row:
```bash
curl "http://localhost:54321/rest/v1/locations?gads_cid=eq.YOUR_CID&select=name,url,gtm_id,ga4_id,gads_conversion_id,scheduler_type" \
  -H "apikey: YOUR_SUPABASE_SERVICE_KEY" \
  -H "Authorization: Bearer YOUR_SUPABASE_SERVICE_KEY"
```

---

## Step 1 — Create GTM Container

**Requires Chrome running with remote debugging:**

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome_gtm \
  --no-first-run \
  https://tagmanager.google.com/
```

Log in to the correct Google account in that Chrome window. Then:

```bash
cd GTM-Automation
python create_container.py --gads-cid YOUR_CID
```

**What it does:**
- Reads client name + URL from Supabase
- Creates a GTM account + Web container via Playwright
- Writes the `GTM-XXXXXXXX` ID back to Supabase (`gtm_id` field)
- Caches the internal account/container IDs to `gtm_id_cache.json` (speeds up Step 2)

**Dry run (no changes):**
```bash
python create_container.py --gads-cid YOUR_CID --dry-run
```

**Override name or URL:**
```bash
python create_container.py --gads-cid YOUR_CID --name "Custom Name" --url "customdomain.com"
```

---

## Step 2 — Set Up Tags and Triggers

Reads all values from Supabase. No extra args needed.

```bash
python setup_tags.py --gads-cid YOUR_CID
```

**What it creates:**

| Type | Name |
|---|---|
| Trigger | `CE - {Scheduler} - Appointment Booked` |
| Trigger | `CL - Phone Click - {number}` |
| Trigger | `All Pages` |
| Tag | `Conversion Linker` |
| Tag | `Google Tag - AW Config` |
| Tag | `GA4 - Configuration` |
| Tag | `GA4 - Event - {appt_event}` |
| Tag | `GA4 - Event - phone_click` |
| Tag | `GAds - {store} - Booked_Appointment` |
| Tag | `GAds - {store} - Phone_Click - {number}` |
| Variable | `JS - AI Referrer` |
| Trigger | `HC - Text Fragment` |
| Trigger | `PV - AI Referral` |
| Tag | `GA4 - Event - ai_overview_click` |
| Tag | `GA4 - Event - ai_referral` |

**Scheduler → event name mapping:**

| `scheduler_type` in Supabase | GTM event | Trigger label |
|---|---|---|
| `autoops` | `ao-appointment-booked` | AutoOps |
| `shopgenie` | `appointment_booked` | Shop Genie |
| `oktorocket` | `dc-service-booked` | OktoRocket |

After success, Supabase `gtm_container_status` is set to `configured`.

**Dry run:**
```bash
python setup_tags.py --gads-cid YOUR_CID --dry-run
```

**Re-run to fix wrong tags (deletes and recreates):**
```bash
python setup_tags.py --gads-cid YOUR_CID --force-recreate
```

---

## Step 3 — Publish GTM Workspace

Before the snippet can be injected, the workspace must be published in GTM.

1. Go to [tagmanager.google.com](https://tagmanager.google.com)
2. Open the client's container (`GTM-XXXXXXXX`)
3. Click **Submit** → add a version name → **Publish**

This makes the tags live. Skipping this means the snippet exists on the site but no tags fire.

---

## Step 4 — Inject GTM into WordPress

Logs into the client's WordPress site, ensures the WPCode plugin is active, and injects the GTM head + body snippets automatically.

```bash
python inject_wordpress.py --gads-cid YOUR_CID
```

**What it does:**
- Reads domain + GTM ID from Supabase
- Logs in to WordPress using shared `lnm-dev` credentials (from `.env`)
- Activates the WPCode / Insert Headers and Footers plugin if not already active
- Injects GTM `<head>` script + `<body>` noscript tag
- Sets `gtm_injected_at` timestamp and `gtm_connected = true` in Supabase

**Dry run:**
```bash
python inject_wordpress.py --gads-cid YOUR_CID --dry-run
```

**Injection methods (auto-detected):**

| Plugin found | Method |
|---|---|
| WPCode / Insert Headers and Footers | Writes via WPCode settings page |
| Code Snippets | Creates PHP snippet via REST API |
| Neither | Fails — manual install required |

---

## Step 5 — Verify

Confirm the snippet is live:

```bash
python verify_gtm_live.py
```

Or manually: view source on the client site, search for `GTM-XXXXXXXX` in the `<head>`.

---

## Full Command Summary

```bash
# 0. Fill Supabase fields (if needed)
curl -X PATCH "http://localhost:54321/rest/v1/locations?gads_cid=eq.YOUR_CID" \
  -H "apikey: YOUR_SUPABASE_SERVICE_KEY" \
  -H "Authorization: Bearer YOUR_SUPABASE_SERVICE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ga4_id":"G-XXXXXXXXXX","gads_conversion_id":"123456789","gads_dc_label":"APPT","gads_phone_label":"PHONE","scheduler_type":"autoops","phone_number":"8005551234"}'

# 1. Launch Chrome (once per session)
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --user-data-dir=/tmp/chrome_gtm \
  --no-first-run https://tagmanager.google.com/

# 2. Create GTM container
cd GTM-Automation
python create_container.py --gads-cid YOUR_CID

# 3. Set up tags + triggers
python setup_tags.py --gads-cid YOUR_CID

# 4. Publish workspace in GTM UI (manual)

# 5. Inject GTM into WordPress
python inject_wordpress.py --gads-cid YOUR_CID

# 6. Verify
python verify_gtm_live.py
```

---

## Files

| File | Purpose |
|---|---|
| `create_container.py` | Step 1 — Playwright container creation + Supabase write |
| `setup_tags.py` | Step 2 — GTM API tag/trigger setup + Supabase status update |
| `inject_wordpress.py` | Step 4 — WordPress GTM injection + Supabase update |
| `wp_auth.py` | WP login + REST nonce helper |
| `wp_installer.py` | Ensures WPCode plugin installed + active |
| `wp_injector.py` | Injects GTM head/body scripts via WPCode or Code Snippets |
| `gtm_id_cache.json` | Auto-generated cache: `GTM-XXXXX` → internal account/container IDs |
| `.env` | WP credentials + Supabase config |
| `token.json` | OAuth token for `reports@leadsnearme.com` (GTM API) |
| `token_analytics.json` | OAuth token for `analytics@leadsnearme.com` |
| `verify_gtm_live.py` | Checks if GTM snippet is live on client site |

---

## Troubleshooting

**`Chrome CDP not running`** — Launch Chrome with `--remote-debugging-port=9222` (Step 1 command above).

**`Not logged in to Google`** — Log in manually in the Chrome window before running `create_container.py`.

**`Missing required fields in Supabase`** — Run Step 0 to fill in the missing data.

**`Token invalid`** — Re-run the auth script: `python get_alex_token.py` or `python get_analytics_token.py`.

**Tags already exist** — Use `--force-recreate` to delete and replace them.

**429 rate limit errors** — Normal for large accounts. The retry logic handles it automatically.

**`WP login failed`** — Check that `lnm-dev` credentials in `.env` are correct for this site. Some sites use a different admin account.

**`Neither WPCode nor Code Snippets available`** — Plugin must be installed manually in WP admin before injection will work.
