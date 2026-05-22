# Premier HVAC — Account Setup Model
*Source: GAds API + GTM API | Pulled 2026-05-20 | Use as reference for new account setup*

---

## Account Identifiers

| Field | Value |
|-------|-------|
| **Account Name** | Premier HVAC - EST - West |
| **GAds Customer ID (CID)** | `4366508893` (displayed: `436-650-8893`) |
| **GAds AW Tag ID** | `AW-17611611682` ← use in `Google Tag - AW Config` GTM tag |
| **GA4 Measurement ID** | `G-DH58VHXK64` |
| **CallRail Company ID** | `907088356` |
| **CallRail Script Hash** | `50ef623ef0f21e5d490f` |
| **Website** | `premierhvaccorp.com` |
| **Scheduler** | OktoRocket (`dc-service-booked`) |
| **Currency** | USD |
| **Time Zone** | America/New_York (EST) |

---

## Google Ads Campaign Structure

### Campaign: `Heating & Air`

| Field | Value |
|-------|-------|
| Campaign ID | `23071187182` |
| Type | SEARCH |
| Bidding | MANUAL_CPC |
| Daily Budget | $125.00 |
| Status | ENABLED |

### Ad Groups

| Ad Group | ID | Status | Landing Page |
|----------|----|--------|--------------|
| Air Conditioning Installation | 187806718522 | ENABLED | `/air-conditioner-installation-northeast-metro-atlanta/` |
| Air Conditioning Repair | 187806718682 | ENABLED | `/air-conditioning-repair-northeast-metro-atlanta/` |
| Branded | 187806718722 | ENABLED | `/` |
| Heating and Air | 187853648638 | ENABLED | `/` |
| HVAC | 187806719002 | ENABLED | `/hvac-maintenance-northeast-metro-atlanta/` |
| Furnace Repair | 187806718762 | **PAUSED** | `/furnace-repair-northeast-metro-atlanta/` |
| Heating Installation | 187806718922 | **PAUSED** | `/heater-installation-northeast-metro-atlanta/` |
| Heating Repair | 187806718962 | **PAUSED** | `/heating-repair-northeast-metro-atlanta/` |

---

## Conversion Actions

### Primary Conversions (bid optimization targets)

| GAds Name | GAds ID | GTM Tag | GTM Label | Value | Counting |
|-----------|---------|---------|-----------|-------|----------|
| Premier HVAC - GTM - Booked_Appointment | 7522933385 | `GAds - Premier HVAC - Booked_Appointment` | `aA-7CIm1m4McEKK8781B` | **$65** | ONE_PER_CLICK |
| Premier HVAC - GTM - Phone_Click | 7522933658 | `GAds - Premier HVAC - Phone_Click` | `-Jn3CJq3m4McEKK8781B` | **$10** | ONE_PER_CLICK |
| Phone - 7706964189 | 7604432521 | `GAds - Premier HVAC - Phone_Click - 7706964189` | `-Jn3CJq3m4McEKK8781B` | **$10** | ONE_PER_CLICK |

### Secondary Conversions (signal/reporting only)

| GAds Name | GAds ID | GTM Trigger | Value | Counting | Category |
|-----------|---------|-------------|-------|----------|----------|
| AI Overview Click | 7604432302 | HC - Text Fragment | $1 | MANY_PER_CLICK | ENGAGEMENT |
| AI Referral | 7604432305 | PV - AI Referral | $1 | MANY_PER_CLICK | SUBMIT_LEAD_FORM |
| Lead Form Submission | 7604432308 | WPForms triggers | $1 | ONE_PER_CLICK | SUBMIT_LEAD_FORM |
| Call Extension | 7325205788 | — (ad-level call) | $0 | ONE_PER_CLICK | PHONE_CALL_LEAD |
| First Time Phone Call | 7617746819 | — (CallRail upload) | $0 | ONE_PER_CLICK | DEFAULT |
| Repeat Phone Call | 7617746822 | — (CallRail upload) | $1 | ONE_PER_CLICK | DEFAULT |
| Text Message | — | — (CallRail upload) | $1 | MANY_PER_CLICK | DEFAULT |

### WPForms Contact Form Conversion (new — WS13 element visibility path)

| GAds Name | GTM Tag | GTM Trigger | GTM Label | Value |
|-----------|---------|-------------|-----------|-------|
| *(maps to Lead Form Submission)* | `GAds - Premier HVAC - Contact_Form - DC_Conversion` | `Wp Forms Trigger` (elementVisibility) | `Nj7mCLTbiaocEKK8781B` | $0 |

> This fires when `.wpforms-confirmation-container-full` appears in the DOM — a DOM-based backup path independent of the JS event listener.

---

## GTM Setup (WS13 master, account-specific tags)

### Tags wired to Premier HVAC

| Tag | Type | Fires On | Key Config |
|-----|------|----------|------------|
| `GA4 - Configuration` | googtag | All Pages | measurementId=`G-DH58VHXK64` |
| `Google Tag - AW Config` | googtag | All Pages | tagId=`AW-17611611682` |
| `CallRail - DNI - Swap Script` | html | All Pages | company=`907088356`, hash=`50ef623ef0f21e5d490f` |
| `GAds - Premier HVAC - Booked_Appointment` | awct | CE - OktoRocket [3] | convId=`17611611682`, label=`aA-7CIm1m4McEKK8781B`, value=$65 |
| `GAds - Premier HVAC - Phone_Click` | awct | CL - Phone Click - 7703530849 [4] | convId=`17611611682`, label=`-Jn3CJq3m4McEKK8781B`, value=$10 |
| `GAds - Premier HVAC - Phone_Click - 7706964189` | awct | CL - Phone Click - 7706964189 [15] | convId=`17611611682`, label=`-Jn3CJq3m4McEKK8781B`, value=$10 |
| `GAds - Premier HVAC - Contact_Form - DC_Conversion` | awct | Wp Forms Trigger [47] | convId=`17611611682`, label=`Nj7mCLTbiaocEKK8781B`, value=$0 |

### Shared tags (fire for all accounts)

| Tag | Fires On | Notes |
|-----|----------|-------|
| `LNM - Attribution - Store` | All Pages | writes `lnm_attribution` cookie |
| `Conversion Linker` | All Pages | preserves gclid |
| `GA4 - Event - dc-service-booked` | CE - OktoRocket | appointment event |
| `GA4 - Event - phone_click` | Phone click triggers | |
| `GA4 - Event - generate_lead` | CF7 + WPForms + Generic Form | |
| `GA4 - Event - ai_overview_click` | HC - Text Fragment | |
| `GA4 - Event - ai_referral` | PV - AI Referral | |
| `Meta - Pixel - Base` | All Pages | uses `{{C - Meta Pixel ID}}` |
| `LinkedIn - Insight Tag - Base` | All Pages | uses `{{C - LinkedIn Partner ID}}` |
| `Microsoft - UET - Base` | All Pages | uses `{{C - Microsoft UET ID}}` |
| `WP Forms Listner` | All Pages | pushes `wpforms_successful_submit` to dataLayer |
| `HTML - WPForms - Listener - Form 5394` | All Pages | form-specific variant (form ID 5394) |

---

## RSA Ad Copy Patterns (reference for new HVAC accounts)

These headlines/descriptions appear across ad groups — reuse as starting point:

**Recurring USP headlines:**
- `10 Yr Warranty On Parts`
- `1 Year No Breakdown Guarantee` / `No Breakdown Guarantee`
- `Fast Response Time`
- `24/7 Emergency Service`
- `Schedule An Appointment Today`
- `100% Satisfaction`
- `Experienced HVAC Technicians`
- `Family Owned Heating & Cooling`

**Recurring USP descriptions:**
- `100% Satisfaction, 1 Year No Breakdown Guarantee, Get Help On The Way!`
- `We Treat Your Home Like It's Our Home, Experience The Difference With Premier HVAC`
- `Fast Response Time, Transparent Estimates & Repairs, Call To Get Help On The Way`

**Promotion (pinned):**
- `$50 Off Repairs Over $300` — pinned to HEADLINE_2 in `Heating and Air` group

**KeyWord insertion used:**
- `{KeyWord:New Air Conditioner Install}` (AC Install group)
- `{KeyWord:AC Repair Near Me}` (AC Repair group)
- `{KeyWord:HVAC Service Near Me}` (HVAC group)
- `{KeyWord:Heating & Air Near Me}` (Heating and Air group)

---

## New Account Checklist (based on this model)

When setting up a new HVAC account, replicate this pattern:

- [ ] Create GAds conversion actions: `Booked_Appointment` ($65, BOOK_APPOINTMENT), `Phone_Click` ($10, PHONE_CALL_LEAD) per phone number
- [ ] Create secondary conversions: `AI Overview Click` ($1), `AI Referral` ($1), `Lead Form Submission` ($1), `Call Extension` ($0)
- [ ] Run `setup_tags.py` to wire GTM — pass `--scheduler oktorocket` for OktoRocket clients
- [ ] Set `C - CallRail Account ID` constant in client GTM container
- [ ] Set pixel constants: `C - Meta Pixel ID`, `C - LinkedIn Partner ID`, `C - Microsoft UET ID`, `C - TikTok Pixel ID`
- [ ] Campaign structure: one SEARCH campaign, ad groups per service line, ENABLED groups = high-intent (repair, install, branded); PAUSED groups = lower-priority until budget permits
- [ ] Daily budget: $125 baseline; adjust by market size
- [ ] Bidding: start MANUAL_CPC; graduate to tCPA once 30+ conversions/month
- [ ] RSA: 14-15 headlines, 4 descriptions per ad group; pin promotion to HEADLINE_2 if applicable; use keyword insertion on primary keyword
- [ ] WPForms clients: confirm `WP Forms Listner` tag is deployed + `Wp Forms Trigger` (elementVisibility) fires `Contact_Form` conversion

---

## Data Flow Summary

```
User visits site
  → All Pages fires: GA4 Config, AW Config, Conversion Linker, Attribution Store,
                     CallRail DNI, Meta Pixel, LinkedIn, Microsoft UET,
                     WP Forms Listner (pushes listener to page)

User books (OktoRocket widget)
  → dc-service-booked → CE - OktoRocket trigger
  → GA4 Event: dc-service-booked
  → GAds: Booked_Appointment ($65) ← primary conversion

User clicks phone
  → tel: link click → CL - Phone Click trigger (per number)
  → GA4 Event: phone_click
  → GAds: Phone_Click ($10) ← secondary conversion

User submits WPForms
  → wpforms_successful_submit event → CE - WPForms trigger
  → GA4 Event: generate_lead
  → .wpforms-confirmation-container-full visible → Wp Forms Trigger
  → GAds: Contact_Form - DC_Conversion ($0)

User arrives via AI Overview (Google #:~:text= link)
  → HC - Text Fragment trigger
  → GA4 Event: ai_overview_click
  → GAds: AI Overview Click ($1)

User arrives from AI platform (ChatGPT, Perplexity, etc.)
  → PV - AI Referral trigger
  → GA4 Event: ai_referral
  → GAds: AI Referral ($1)
```
