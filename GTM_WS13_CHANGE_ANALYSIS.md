# GTM Workspace 13 — Change Analysis
*Pulled via API: 2026-05-20 | Account 6342687162 / Container 245447291 / Workspace 13*

---

## What's in WS13 (Master Template)

### Triggers (10 total)

| ID | Name | Type | Fires On |
|----|------|------|----------|
| 5 | All Pages | pageview | every page load |
| 3 | CE - OktoRocket - Appointment Booked | customEvent | `dc-service-booked` |
| 4 | CL - Phone Click - 7703530849 | linkClick | Click URL contains number |
| 15 | CL - Phone Click - 7706964189 | linkClick | Click URL contains number |
| 16 | HC - Text Fragment | historyChange | `{{JS - New Fragment}}` contains `:~:text=` |
| 17 | PV - AI Referral | pageview | `{{JS - AI Referrer}}` matches `.+` |
| 31 | CE - CF7 - Form Submitted | customEvent | `wpcf7mailsent` |
| 32 | CE - WPForms - Form Submitted | customEvent | `wpforms_successful_submit` |
| 33 | FS - Generic Form Submit | formSubmission | any form |
| 47 | Wp Forms Trigger | elementVisibility | `.wpforms-confirmation-container-full` |

### Tags (19 total)

| ID | Name | Type | Fires On (trigger IDs) |
|----|------|------|------------------------|
| 5 | All Pages | pageview | — |
| 6 | GA4 - Configuration | googtag | 5 |
| 7 | GA4 - Event - dc-service-booked | gaawe | 3 |
| 8 | GA4 - Event - phone_click | gaawe | 4 |
| 9 | GAds - Premier HVAC - Booked_Appointment | awct | 3 |
| 10 | GAds - Premier HVAC - Phone_Click | awct | 4 |
| 12 | CallRail - DNI - Swap Script | html | 5 |
| 18 | Conversion Linker | gclidw | 5 |
| 19 | Google Tag - AW Config | googtag | 5 |
| 20 | GAds - Premier HVAC - Phone_Click - 7706964189 | awct | 15 |
| 21 | GA4 - Event - ai_overview_click | gaawe | 16 |
| 22 | GA4 - Event - ai_referral | gaawe | 17 |
| 23 | LNM - Attribution - Store | html | 5 |
| 34 | GA4 - Event - generate_lead | gaawe | 31, 32, 33 |
| 39 | Meta - Pixel - Base | html | 5 |
| 41 | LinkedIn - Insight Tag - Base | html | 5 |
| 42 | Microsoft - UET - Base | html | 5 |
| 43 | GAds - Premier HVAC - Contact_Form - DC_Conversion | awct | 47 |
| 44 | HTML - WPForms - Listener - Form 5394 | html | 5 |
| 46 | WP Forms Listner | html | 5 |

### Variables (14 total)

| ID | Name | Type |
|----|------|------|
| 11 | C - CallRail Account ID | constant |
| 13 | JS - New Fragment | jsm |
| 14 | JS - AI Referrer | jsm |
| 24–30 | JS - Attribution - utm_source/medium/campaign/term/content/gclid/msclkid | jsm |
| 35 | C - Meta Pixel ID | constant |
| 36 | C - TikTok Pixel ID | constant |
| 37 | C - LinkedIn Partner ID | constant |
| 38 | C - Microsoft UET ID | constant |

---

## Key Changes vs Client Exports

### 1. WPForms event name changed

| | Event Name |
|--|--|
| **Old** (client exports, setup scripts, docs) | `wpformsAjaxSubmitActionSuccess` |
| **New** (WS13 master) | `wpforms_successful_submit` |

Clients set up with the old event name will **not fire `generate_lead`** on WPForms submits.

Files that had the stale event name and were fixed:
- `setup_tags.py:896`
- `push_lead_attribution.py:251`
- `LNM-GTM-Standard-Setup.md:39`
- `GTM_SETUP_GUIDE.md:158`

### 2. New trigger: Wp Forms Trigger [47] — element visibility (backup path)

- Type: `elementVisibility`
- Selector: `.wpforms-confirmation-container-full`
- Config: DOM change listener enabled, fires once
- Connected tag: `GAds - Premier HVAC - Contact_Form - DC_Conversion` [43]
- Not in any existing client export — new in this workspace

### 3. New HTML listener tags (fire on All Pages)

- `WP Forms Listner` [46] — pushes `wpforms_successful_submit` to dataLayer; this is what makes trigger [32] work
- `HTML - WPForms - Listener - Form 5394` [44] — form-specific variant for a specific WPForms form ID

### 4. TikTok variable exists, tag missing

- `C - TikTok Pixel ID` variable [36] exists in WS13
- No `TikTok - Pixel - Base` tag in WS13 (TNXVDH3G client export has one)
- Either intentionally removed from template or never added — verify before pushing to new clients

---

## WPForms Data Flow (updated architecture)

```
WP Forms Listner tag [46]                HTML - WPForms - Listener - Form 5394 [44]
  fires on: All Pages [5]                  fires on: All Pages [5]
  → pushes wpforms_successful_submit → dataLayer

                     ↓
  CE - WPForms - Form Submitted [32]   listens for wpforms_successful_submit
                     ↓
  GA4 - Event - generate_lead [34]     (+ CF7 [31] + Generic [33])

  PARALLEL PATH (DOM-based backup):
  .wpforms-confirmation-container-full visible in DOM
  → Wp Forms Trigger [47] (elementVisibility, DOM change listener)
  → GAds - Contact_Form - DC_Conversion [43]
```

---

## Clients at Risk

Any client container created before this change that uses WPForms will have the old trigger `wpformsAjaxSubmitActionSuccess`. Run `push_lead_attribution.py` against those containers to update the trigger event name.

To find affected containers: look for GTM containers where `CE - WPForms - Form Submitted` trigger has `arg1 = wpformsAjaxSubmitActionSuccess`.
