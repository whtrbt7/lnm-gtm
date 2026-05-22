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
| Client URL | Required for container creation (Step 1) |

**All fields must be saved to the Supabase `locations` table before running Step 2.**

**GTM account is created under `analytics2@leadsnearme.com`.** Log in to that Google account in the Chrome debug window before running Step 1.

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

### Core Tracking

| Type | Name | Condition |
|---|---|---|
| Trigger | `All Pages` | always |
| Tag | `Conversion Linker` | All Pages |
| Tag | `Google Tag - AW Config` | All Pages |
| Tag | `GA4 - Configuration` | All Pages |

### Appointment Booking

| Type | Name | Condition |
|---|---|---|
| Trigger | `CE - {Scheduler} - Appointment Booked` | if `scheduler_type` set |
| Tag | `GA4 - Event - {appt_event}` | if `scheduler_type` set |
| Tag | `GAds - {store} - Booked_Appointment` | if `scheduler_type` set |
| Trigger | `CE - AutoOps - All Events` | AutoOps only (matches `^ao-.*`) |
| Tag | `GA4 - Event - AutoOps Events` | AutoOps only |

**Scheduler → event name mapping:**

| `scheduler_type` in Supabase | GTM event | Trigger label |
|---|---|---|
| `autoops` | `ao-appointment-booked` | AutoOps |
| `shopgenie` | `appointment_booked` | Shop Genie |
| `oktorocket` | `dc-service-booked` | OktoRocket |

### Phone Click Tracking

| Type | Name | Condition |
|---|---|---|
| Trigger | `CL - Phone Click - {number}` | if `phone_number` + `gads_phone_label` set |
| Tag | `GA4 - Event - phone_click` | fires on all phone triggers |
| Tag | `GAds - {store} - Phone_Click - {number}` | one per number |

**Multi-location phone support:** If `dashboard_type` is `All Locations One Site`, `New MSO structure`, or `Mothership Site with Microsites`, the script fetches **all brand locations** and creates one phone trigger + GAds tag per unique number in the brand.

### UTM / Lead Form Attribution

Captures UTM parameters and click IDs on first visit, stores in a 30-day cookie (`lnm_attribution`), then sends them as parameters on every form submission.

**Tag: `LNM - Attribution - Store`** — fires All Pages (once per load)
- On page load, checks if `lnm_attribution` cookie already set
- If not, reads URL params and stores them in the cookie as JSON
- Fields captured: `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`, `gclid`, `msclkid`
- Cookie: path=/, max-age=2592000 (30 days), SameSite=Lax

**Variables (7):** `JS - Attribution - {field}` for each field above
- Each reads the `lnm_attribution` cookie and returns the value for that field

**Form triggers (3):**

| Type | Name | Fires on |
|---|---|---|
| Custom Event | `CE - CF7 - Form Submitted` | `wpcf7mailsent` |
| Custom Event | `CE - WPForms - Form Submitted` | `wpforms_successful_submit` |
| Form Submission | `FS - Generic Form Submit` | any form submit |

**Tag: `GA4 - Event - generate_lead`** — fires on all three form triggers
- Event name: `generate_lead`
- Parameters: all 7 attribution fields (from `JS - Attribution - *` variables)
- This is how form submissions in GA4 carry UTM / gclid source data

### AI Traffic Tracking

Built-in GTM variables enabled: `Click URL`, `Click Text`, `History New URL Fragment`

| Type | Name | What it does |
|---|---|---|
| Variable | `JS - AI Referrer` | Returns referrer domain if from an AI source (Perplexity, ChatGPT, Gemini, Copilot, Claude, You.com, Phind) — empty string otherwise |
| Trigger | `HC - Text Fragment` | History Change: fires when URL fragment contains `:~:text=` (Google AI Overview click) |
| Trigger | `PV - AI Referral` | Page View: fires when `JS - AI Referrer` is non-empty |
| Tag | `GA4 - Event - ai_overview_click` | Fires on `HC - Text Fragment` |
| Tag | `GA4 - Event - ai_referral` | Fires on `PV - AI Referral`; sends `ai_source` parameter |

### CallRail Dynamic Number Insertion (DNI)

Only created if `callrail_account_id` and `callrail_company_id` are both set in Supabase.

| Type | Name |
|---|---|
| Variable | `C - CallRail Account ID` (constant = company_id) |
| Tag | `CallRail - DNI - Swap Script` |

The swap.js URL is fetched live from the CallRail API using the company_id. If the API call fails, the DNI tag is skipped with a warning.

### Social & Advertising Pixels

Placeholder constant variables and disabled base tags are created for future use. Pixel IDs are blank by default — fill them in GTM when the client has these pixels.

| Variable | Tag |
|---|---|
| `C - Meta Pixel ID` | `Meta - Pixel - Base` |
| `C - TikTok Pixel ID` | `TikTok - Pixel - Base` |
| `C - LinkedIn Partner ID` | `LinkedIn - Insight Tag - Base` |
| `C - Microsoft UET ID` | `Microsoft - UET - Base` |

---

After success, Supabase `gtm_container_status` is set to `configured`.

**Dry run:**
```bash
python setup_tags.py --gads-cid YOUR_CID --dry-run
```

**Re-run to fix wrong tags (deletes and recreates):**
```bash
python setup_tags.py --gads-cid YOUR_CID --force-recreate
```

**Shared CID — multiple locations with same GAds account:**
```bash
python setup_tags.py --gads-cid YOUR_CID --location-id SUPABASE_UUID
```

**Skip Supabase lookup entirely (override all fields via CLI):**
```bash
python setup_tags.py --gads-cid YOUR_CID \
  --gtm-id GTM-XXXXXXX \
  --ga4-id G-XXXXXXXXXX \
  --gads-conversion-id 123456789 \
  --appt-label LABEL_HERE \
  --name "Client Name" \
  --scheduler autoops \
  --phone 8005551234 \
  --phone-label PHONE_LABEL
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
  -d '{
    "url": "clientdomain.com",
    "ga4_measurement_id": "G-XXXXXXXXXX",
    "gads_conversion_id": "123456789",
    "gads_appt_label": "APPT_LABEL",
    "gads_phone_label": "PHONE_LABEL",
    "scheduler_type": "autoops",
    "phone_number": "8005551234",
    "callrail_account_id": "ACC123",
    "callrail_company_id": "COM456"
  }'

# 1. Launch Chrome logged in as analytics2@leadsnearme.com (once per session)
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --user-data-dir=/tmp/chrome_gtm \
  --no-first-run https://tagmanager.google.com/

# 2. Create GTM container
cd GTM-Automation
python create_container.py --gads-cid YOUR_CID

# 3. Set up tags + triggers (UTM attribution, AI tracking, CallRail DNI, pixels)
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
| `setup_tags.py` | Step 2 — GTM API tag/trigger/variable setup + Supabase status update |
| `inject_wordpress.py` | Step 4 — WordPress GTM injection + Supabase update |
| `wp_auth.py` | WP login + REST nonce helper |
| `wp_installer.py` | Ensures WPCode plugin installed + active |
| `wp_injector.py` | Injects GTM head/body scripts via WPCode or Code Snippets |
| `verify_gtm_live.py` | Checks if GTM snippet is live on client site |
| `gtm_id_cache.json` | Auto-generated cache: `GTM-XXXXX` → internal account/container IDs |
| `utils.py` | Shared GTM API helpers (ensure_tag, ensure_trigger, ensure_variable) |
| `.env` | WP credentials + Supabase config (`SUPABASE_SERVICE_KEY`, `CALLRAIL_API_KEY`) |
| `token.json` | OAuth token for `reports@leadsnearme.com` (GTM API reads) |
| `token_analytics.json` | OAuth token for `analytics@leadsnearme.com` (GTM API writes) |
| `get_alex_token.py` | Re-auth for `reports@` token |
| `get_analytics_token.py` | Re-auth for `analytics@` token |

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

**`Missing required fields in Supabase: gtm_id`** — Step 1 (`create_container.py`) didn't complete or didn't write back. Check `gtm_id` in Supabase. Can also pass `--gtm-id GTM-XXXXXXXX` to bypass.

**CallRail DNI tag skipped** — Either `callrail_account_id` / `callrail_company_id` missing in Supabase, or the CallRail API returned no `script_url`. Check the company record in CallRail UI; the swap.js URL must be set on the company.

**UTM attribution not capturing** — Verify `LNM - Attribution - Store` tag fires on All Pages. Check that no page caching plugin strips cookies before GTM loads. Cookie name is `lnm_attribution`; inspect it in DevTools → Application → Cookies after landing on a `?utm_source=...` URL.

**`generate_lead` event missing UTM parameters** — The attribution cookie must be set before the form fires. If a visitor lands directly on a contact page (no prior page load with UTM params), the cookie may not be set in time. This is expected for direct form-page entries without UTM params.

**Shared CID — wrong location picked** — Pass `--location-id SUPABASE_UUID` to target a specific row when multiple locations share the same `gads_cid`.

**Social pixel tags created but not firing** — By design. The `C - Meta Pixel ID` etc. variables are created blank. Fill in the pixel IDs in GTM and publish a new version when the client provides them.
