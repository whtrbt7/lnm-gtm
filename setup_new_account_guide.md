# setup_new_account.py — Usage Guide

Sets up the full LNM standard tag and trigger configuration inside a single GTM container via the GTM API. No spreadsheet required — you pass everything as command-line arguments.

---

## Authentication

The script authenticates to the GTM API using an OAuth 2.0 token file stored locally. There are two token files in the project, each tied to a different Google account:

| File | Google Account | Use when |
|---|---|---|
| `token.json` | reports@leadsnearme.com | Default |
| `token_analytics.json` | analytics@leadsnearme.com | Analytics-only pushes |

### Generating a token for the first time

If a token file doesn't exist yet or needs to be refreshed, run the corresponding token script:

```bash
# For analytics@leadsnearme.com
python get_analytics_token.py
```

The script will open a browser window and ask you to log in to the correct Google account and grant GTM permissions. The token is saved locally and auto-refreshes on future runs — you only need to do this once per account.

### Testing authentication

To confirm a token is working and see which GTM accounts it can access:

```bash
python auth.py
```

---

## How the script works

1. **Looks up the container** — scans all GTM accounts accessible to the token file to find the container matching the GTM ID you provide.
2. **Reads existing items** — fetches the container's current triggers and tags so nothing is created twice (idempotent).
3. **Creates triggers** in this order:
   - `CE - {Scheduler} - Appointment Booked` — Custom Event trigger that listens for the scheduler's booking event
   - `CL - Phone Click - {number}` — Link Click trigger per phone number
   - `All Pages` — Page View trigger
4. **Creates tags** in this order:
   - `Conversion Linker` — fires on All Pages; must exist before any GAds tag fires
   - `Google Tag - AW Config` — fires on All Pages; establishes AW account-level connection
   - `GA4 - Configuration` — fires on All Pages
   - `GA4 - Event - {appt_event}` — fires on appointment trigger
   - `GA4 - Event - phone_click` — fires on all phone CL triggers combined *(only if phones provided)*
   - `GAds - {store} - Booked_Appointment` — fires on appointment trigger
   - `GAds - {store} - Phone_Click - {number}` — one per phone, each with its own conversion label *(only if phones provided)*
   - `JS - AI Referrer` (variable) — detects referrals from Perplexity, ChatGPT, Gemini, Copilot, Claude, etc.
   - `HC - Text Fragment` trigger — fires on History Change when URL fragment contains `:~:text=` (Google AI Overview clicks)
   - `PV - AI Referral` trigger — fires on Page View when AI referrer variable is non-empty
   - `GA4 - Event - ai_overview_click` — fires on text fragment trigger; enables AI Overview click tracking
   - `GA4 - Event - ai_referral` — fires on AI referral trigger; sends `ai_source` param to GA4 for Custom Channel Group segmentation

Items that already exist are skipped (shown with `·`). Items that are newly created are shown with `✓`.

### Scheduler event mapping

| `--scheduler` value | GTM event name | Trigger label |
|---|---|---|
| `oktorocket` | `dc-service-booked` | OktoRocket |
| `shopgenie` | `appointment_booked` | Shop Genie |
| `autoops` | `ao-appointment-booked` | AutoOps |

### Store name derivation

The store name is extracted from `--name` and used in Google Ads tag names (e.g. `GAds - Parker - Booked_Appointment`). The script strips common words like "Automotive", "Repair", "LLC", etc. and takes the last part after ` - ` if present.

Examples:
- `"Parker Automotive - Dallas"` → `Dallas`
- `"Parker Automotive"` → `Parker`

---

## Arguments

### Required

| Argument | Description | Example |
|---|---|---|
| `--gtm-id` | GTM Container public ID | `GTM-ABC1234` |
| `--name` | Client/store display name | `"Parker Automotive"` |
| `--ga4-id` | GA4 Measurement ID | `G-XXXXXXXXXX` |
| `--gads-id` | Google Ads Conversion ID (integer) | `123456789` |
| `--appt-label` | GAds appointment booking conversion label | `abc123XYZ` |
| `--scheduler` | Scheduler type (see table above) | `oktorocket` |

### Optional

| Argument | Description | Example |
|---|---|---|
| `--phone NUMBER LABEL` | Phone number + its GAds conversion label. Repeat for each phone. | `--phone 5551234567 abc123XYZ` |
| `--token-file` | Token file to use (default: `token.json`) | `token_analytics.json` |
| `--dry-run` | Preview what would be created without making any API calls | *(flag)* |
| `--force-recreate` | Delete and replace any existing tags/triggers with the same name | *(flag)* |

---

## Commands

### Preview before running (always do this first)

```bash
python setup_new_account.py \
  --gtm-id GTM-ABC1234 \
  --name "Parker Automotive" \
  --ga4-id G-XXXXXXXXXX \
  --gads-id 123456789 \
  --appt-label abc123XYZ \
  --scheduler oktorocket \
  --dry-run
```

### Basic setup — no phone tracking

```bash
python setup_new_account.py \
  --gtm-id GTM-ABC1234 \
  --name "Parker Automotive" \
  --ga4-id G-XXXXXXXXXX \
  --gads-id 123456789 \
  --appt-label abc123XYZ \
  --scheduler oktorocket
```

### Setup with one phone number

```bash
python setup_new_account.py \
  --gtm-id GTM-ABC1234 \
  --name "Parker Automotive" \
  --ga4-id G-XXXXXXXXXX \
  --gads-id 123456789 \
  --appt-label abc123XYZ \
  --scheduler oktorocket \
  --phone 5551234567 phoneLabel123
```

### Setup with multiple phone numbers (each with its own label)

```bash
python setup_new_account.py \
  --gtm-id GTM-ABC1234 \
  --name "Parker Automotive" \
  --ga4-id G-XXXXXXXXXX \
  --gads-id 123456789 \
  --appt-label abc123XYZ \
  --scheduler oktorocket \
  --phone 5551234567 phoneLabel123 \
  --phone 5559876543 phoneLabel456 \
  --phone 5550001111 phoneLabel789
```

### Using the analytics token

```bash
python setup_new_account.py \
  --gtm-id GTM-ABC1234 \
  --name "Parker Automotive" \
  --ga4-id G-XXXXXXXXXX \
  --gads-id 123456789 \
  --appt-label abc123XYZ \
  --scheduler oktorocket \
  --token-file token_analytics.json
```

### Re-run to fix/replace existing tags

If tags were already created but need to be replaced (e.g. wrong conversion label):

```bash
python setup_new_account.py \
  --gtm-id GTM-ABC1234 \
  --name "Parker Automotive" \
  --ga4-id G-XXXXXXXXXX \
  --gads-id 123456789 \
  --appt-label abc123XYZ \
  --scheduler shopgenie \
  --phone 5551234567 phoneLabel123 \
  --force-recreate
```

---

## Where to find the required values

| Value | Where to find it |
|---|---|
| **GTM Container ID** (`GTM-XXXXXX`) | GTM UI → top of the container workspace, or the XLSX column AC |
| **GA4 Measurement ID** (`G-XXXXXXXX`) | Google Analytics → Admin → Data Streams → your stream |
| **Google Ads Conversion ID** | Google Ads → Tools → Conversions → select a conversion → Tag setup → the number in `AW-XXXXXXXXX` |
| **Appointment conversion label** | Same Ads conversion page → the string after the `/` in the tag snippet |
| **Phone click conversion label** | Same location, for the phone click conversion action |

---

## Output example

```
=== LNM GTM Setup: GTM-ABC1234 ===
  Client    : Parker Automotive
  Store name: Parker
  GA4 ID    : G-XXXXXXXXXX
  GAds ID   : 123456789
  Scheduler : OktoRocket (event=dc-service-booked)
  Appt label: abc123XYZ
  Phone     : 5551234567  label=phoneLabel123
  Phone     : 5559876543  label=phoneLabel456

Searching for container GTM-ABC1234 across all accounts...
  Found 42 GTM account(s) — scanning...
  Found: account=123456, container=789012

Workspace ID: 3
Existing: 0 trigger(s), 0 tag(s)

  ✓ Trigger: CE - OktoRocket - Appointment Booked (new)
  ✓ Trigger: CL - Phone Click - 5551234567 (new)
  ✓ Trigger: CL - Phone Click - 5559876543 (new)
  ✓ Trigger: All Pages (new)
  ✓ Tag: GA4 - Configuration (new)
  ✓ Tag: GA4 - Event - dc-service-booked (new)
  ✓ Tag: GA4 - Event - phone_click (new)
  ✓ Tag: GAds - Parker - Booked_Appointment (new)
  ✓ Tag: GAds - Parker - Phone_Click - 5551234567 (new)
  ✓ Tag: GAds - Parker - Phone_Click - 5559876543 (new)

=== Done ===
```

Icons: `✓` = created, `·` = already existed (skipped)
