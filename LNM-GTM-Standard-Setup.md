# LNM Standard GTM Setup — Tags, Triggers & GAds Conversion Actions

> **What is GTM?** Google Tag Manager is a tool that sits between a client's website and their marketing platforms (Google Ads, GA4, Meta, etc.). Instead of asking a developer to add tracking code directly to the website every time, GTM lets us deploy and manage all tracking from one place. When something happens on the site (page load, button click, form submit), GTM fires the right tracking code automatically.

---

## Schedulers

Each client uses a booking/scheduling platform. GTM listens for that platform's "booking confirmed" signal and fires the appointment conversion. Different platforms fire different signals.

### Scheduler → Event Mapping

| `scheduler_type` in Supabase | GTM Trigger Label | Signal GTM Listens For | Notes |
|---|---|---|---|
| `OktoRocket`, `OktoRocket/DC`, `dcbookings` | OktoRocket | Custom Event: `dc-service-booked` | Default. OktoRocket widget pushes this to the page when booking completes. |
| `Shop Genie`, `ShopGenie` | Shop Genie | Custom Event: `appointment_booked` | ShopGenie widget pushes this on booking confirmation. |
| `AutoOps`, `autoops` | AutoOps | Custom Event: `ao-appointment-booked` | AutoOps fires this via its JS event API; a bridge script relays it to GTM. Also creates a catch-all `CE - AutoOps - All Events` trigger for all `ao-*` events. |
| `SteerCRM`, `steercrm` | SteerCRM | Custom Event: `ao-appointment-booked` | SteerCRM's booking tool runs on the AutoOps platform — same event, same bridge script. |
| `Shopmonkey` | Shopmonkey | Custom Event: `sm_work_request_form_event` | Shopmonkey has native GTM support. Pushes `sm_work_request_form_event` to the dataLayer when the work request form submits. Trigger filters on `action = work_request_form_submitted` via a dataLayer variable. |
| `TekMetric`, `Tekmetric`, `tekmetric` | TekMetric | postMessage: `bookingTool:closeModal` | TekMetric uses an iframe with no native dataLayer. A listener tag on the page catches the `bookingTool:closeModal` postMessage event and pushes `tekmetric-booking-closed` to the dataLayer. ⚠ This fires on both confirmed bookings and exits — secondary signals (form visible → close) disambiguate. |
| `Protractor` | — | Generic Form Submit | Protractor's booking widget is a legacy cross-origin iframe with no analytics code. No appointment-specific event is available. Falls back to `FS - Generic Form Submit` for lead tracking only. |
| `Form Submit`, `Leads Near Me`, `N/A`, `null` | — | Generic Form Submit | No scheduler detected or not applicable. Falls back to form submit for lead tracking only. |

---

## Triggers

> **What is a trigger?** A trigger is the "when" — it tells GTM what event on the website should cause a tag to fire. Without a trigger, a tag never runs.

| Trigger Name | Type | Fires When | Plain English |
|---|---|---|---|
| `All Pages` | Pageview | Every page load | Runs on every single page of the site. Used for base tags like GA4, Google Ads config, and attribution. |
| `CE - {Scheduler} - Appointment Booked` | Custom Event | Booking platform fires its confirmation event | Fires the moment a customer completes an appointment booking. The exact event name depends on the scheduler (see table above). |
| `CE - AutoOps - All Events` | Custom Event | Any event starting with `ao-` | Catches every AutoOps step (opened, service selected, etc.) for GA4 engagement tracking. AutoOps/SteerCRM only. |
| `CL - Phone Click - {number}` | Link Click | User clicks a `tel:` link containing the phone number | Fires when someone taps or clicks the phone number on the site to call the shop. One trigger per phone number. |
| `HC - Text Fragment` | History Change | URL fragment contains `:~:text=` | Fires when a visitor arrives via an AI Overview link in Google Search (these links have a `#:~:text=` fragment). Used to track AI-driven traffic. |
| `PV - AI Referral` | Pageview | `JS - AI Referrer` variable returns a value | Fires on any pageview where the referring site is an AI platform (ChatGPT, Perplexity, Gemini, Claude, etc.). |
| `CE - CF7 - Form Submitted` | Custom Event | `wpcf7mailsent` event | Fires when a Contact Form 7 (WordPress plugin) form is successfully submitted. |
| `CE - WPForms - Form Submitted` | Custom Event | `wpforms_successful_submit` event | Fires when a WPForms (WordPress plugin) form is successfully submitted. Requires `WP Forms Listner` HTML tag on All Pages to push this event to dataLayer. |
| `FS - Generic Form Submit` | Form Submission | Any form submission on the site | Broad fallback that catches any HTML form submission. Used for schedulers with no dedicated event. |

---

## Tags

> **What is a tag?** A tag is the "what" — it's the actual code that runs when a trigger fires. Each tag talks to a specific platform (Google Ads, GA4, Meta, etc.) and tells it something happened.

---

### Google Infrastructure Tags

These lay the foundation. Everything else depends on them being present.

---

#### `Conversion Linker`
**Fires on:** All Pages (once per page load)

**What it does:** Reads the `gclid` (Google Click ID) from the URL when someone arrives from a Google ad and stores it in a first-party cookie. Without this, Google Ads can't connect a conversion (phone call, booking) back to the ad that brought the visitor.

**Layman:** *When someone clicks your Google ad and lands on the site, this tag saves a record of that click. That record is what lets us later tell Google Ads "this phone call came from that specific ad."*

---

#### `Google Tag - AW Config`
**Fires on:** All Pages (once per page load)

**What it does:** Loads the Google Ads base script tied to the client's Google Ads account (`AW-{conversion_id}`). This is the account-level handshake — all Google Ads conversion tags on the page report up through this tag.

**Layman:** *This is the "front door" to the client's Google Ads account. It must be open before any conversion data can flow in.*

---

#### `GA4 - Configuration`
**Fires on:** All Pages (once per event)

**What it does:** Loads Google Analytics 4 and begins tracking pageviews, sessions, and traffic sources for the site. All GA4 event tags reference this tag as their parent.

**Layman:** *This is the master switch that turns on Google Analytics for the site. Once it's on, Google starts recording who visits, where they came from, and what pages they view.*

---

### GA4 Event Tags

These send specific events to Google Analytics so you can see what actions people took.

---

#### `GA4 - Event - {appt_event}`
**Fires on:** Appointment Booked trigger
*(event name = `dc-service-booked`, `appointment_booked`, `ao-appointment-booked`, or `sm_work_request_form_event` depending on scheduler)*

**What it does:** Sends a named event to GA4 the moment a booking is confirmed. This populates the "Events" report in GA4 and can be used to create GA4 conversions for attribution reporting.

**Layman:** *Every time someone books an appointment, this tag tells Google Analytics "a booking just happened." You can then see how many bookings came from which traffic sources.*

---

#### `GA4 - Event - AutoOps Events` *(AutoOps / SteerCRM only)*
**Fires on:** CE - AutoOps - All Events

**What it does:** Sends every step of the AutoOps booking flow to GA4 (widget opened, service selected, date picked, etc.) using the actual event name from AutoOps (e.g. `ao-location-selected`).

**Layman:** *This lets you see in Google Analytics how far customers get through the booking process — do they open it and quit, or do they make it all the way to confirmation?*

---

#### `GA4 - Event - phone_click`
**Fires on:** All phone click triggers combined (every phone number)

**What it does:** Sends a `phone_click` event to GA4 whenever anyone clicks a phone number on the site. If the client has multiple numbers, one tag covers all of them.

**Layman:** *Every phone tap on the site gets recorded in Google Analytics. You can see how many people chose to call instead of book online.*

---

#### `GA4 - Event - ai_overview_click`
**Fires on:** HC - Text Fragment trigger

**What it does:** Sends an `ai_overview_click` event to GA4 when a visitor arrives via an AI Overview result in Google Search. Google's AI Overviews append a `#:~:text=` fragment to the URL, which this trigger detects.

**Layman:** *When Google shows an AI-generated answer in search results and someone clicks through to the client's site from that answer, this tag records it. Helps quantify how much traffic is coming from AI search features.*

---

#### `GA4 - Event - ai_referral`
**Fires on:** PV - AI Referral trigger

**What it does:** Sends an `ai_referral` event to GA4 — including which AI platform referred the visitor (e.g. `perplexity.ai`, `chatgpt.com`) — when someone arrives directly from an AI tool's website.

**Layman:** *If someone asks ChatGPT or Perplexity "best auto shop near me" and clicks through to the client's site, this tag records that visit and which AI sent them.*

---

#### `GA4 - Event - generate_lead`
**Fires on:** CF7 Form Submitted + WPForms Form Submitted + Generic Form Submit

**What it does:** Sends a `generate_lead` event to GA4 when any contact/inquiry form on the site is submitted. Also attaches UTM parameters and the gclid from the attribution cookie so you can see which campaign drove the form submission.

**Layman:** *Every time someone fills out a contact form, this tag tells Google Analytics a lead came in — and includes where that person originally came from (which Google ad, which search term, etc.).*

---

### Google Ads Conversion Tags

These are the tags that actually register conversions in Google Ads and affect bidding/reporting.

---

#### `GAds - {store} - Booked_Appointment`
**Fires on:** Appointment Booked trigger
**Conversion value:** $65

**What it does:** Sends a conversion event to Google Ads with a $65 value every time a booking is confirmed. Uses the client's specific appointment conversion label so it reports to the right conversion action in their account. This is the **primary conversion** — Google's bidding algorithm optimizes toward this signal.

**Layman:** *When someone books an appointment, this tag tells Google Ads "we got a booking worth $65 from this campaign." Google uses this to figure out which ads, keywords, and audiences are actually producing bookings — and adjusts spending accordingly.*

---

#### `GAds - {store} - Phone_Click - {number}`
**Fires on:** CL - Phone Click - {number} trigger (one tag per phone number)
**Conversion value:** $10

**What it does:** Sends a conversion event to Google Ads with a $10 value when someone clicks a phone number. Separate tag per number so you can see which location's number is getting the most ad-driven calls.

**Layman:** *When someone clicks to call, this tag tells Google Ads "we got a call lead worth $10." It's secondary to booking — less valuable because not every call turns into an appointment — but still signals that the ad is working.*

---

### Lead Attribution Tag

---

#### `LNM - Attribution - Store`
**Fires on:** All Pages (once per page load)

**What it does:** On the visitor's first pageview, reads any UTM parameters or gclid from the URL and saves them to a first-party cookie (`lnm_attribution`) that lasts 30 days. When a form is submitted later, the attribution variables read from this cookie and include the original source in the GA4 event.

**Layman:** *Someone clicks a Google ad → lands on the site → browses for 10 minutes → fills out a contact form. This tag remembers that original click so when the form is submitted, we still know it came from Google Ads, even though the gclid was no longer in the URL.*

---

### CallRail Tag *(conditional — requires CallRail setup in Supabase)*

---

#### `CallRail - DNI - Swap Script`
**Fires on:** All Pages (once per page load)

**What it does:** Loads CallRail's Dynamic Number Insertion (DNI) script, which swaps the phone number displayed on the site with a unique tracking number for each visitor. This lets CallRail record which ad/keyword/source caused the call.

**Layman:** *CallRail gives each website visitor a unique phone number. When they call that number, CallRail knows exactly which ad or search term sent them. This tag loads the script that does the swapping.*

---

### Social & Advertising Pixel Tags

These run ad platforms' base tracking scripts. Pixel IDs are placeholders and must be filled in per client.

---

#### `Meta - Pixel - Base`
**Fires on:** All Pages (once per page load)
**Variable:** `{{C - Meta Pixel ID}}`

**What it does:** Loads the Meta (Facebook/Instagram) Pixel on every page. Enables Meta to build remarketing audiences from site visitors and measure ad performance.

**Layman:** *This tag tells Meta (Facebook/Instagram) "someone visited this site." Meta uses this to show follow-up ads to people who visited but didn't book, and to measure how many people who saw an ad actually came to the site.*

---

#### `TikTok - Pixel - Base`
**Fires on:** All Pages (once per page load)
**Variable:** `{{C - TikTok Pixel ID}}`

**What it does:** Loads the TikTok Pixel on every page. Enables TikTok to build remarketing audiences and measure ad performance.

**Layman:** *Same concept as Meta Pixel, but for TikTok ads.*

---

#### `LinkedIn - Insight Tag - Base`
**Fires on:** All Pages (once per page load)
**Variable:** `{{C - LinkedIn Partner ID}}`

**What it does:** Loads LinkedIn's Insight Tag, which enables remarketing and conversion tracking for LinkedIn ad campaigns.

**Layman:** *Same concept as Meta Pixel, but for LinkedIn ads.*

---

#### `Microsoft - UET - Base`
**Fires on:** All Pages (once per page load)
**Variable:** `{{C - Microsoft UET ID}}`

**What it does:** Loads Microsoft's Universal Event Tracking (UET) tag for Bing/Microsoft Ads. Enables remarketing and conversion tracking.

**Layman:** *Same concept as Meta Pixel, but for Bing/Microsoft ads.*

---

## Variables

> **What is a variable?** A variable is a value GTM looks up at the moment a tag fires. Instead of hardcoding a phone number or UTM source into a tag, you reference a variable that reads it from the page dynamically.

### Custom JavaScript Variables

| Variable Name | What It Returns | Plain English |
|---|---|---|
| `JS - AI Referrer` | The AI platform domain if the visitor came from one (e.g. `chatgpt.com`), otherwise empty | Checks where the visitor came from. If it was an AI tool like ChatGPT or Perplexity, returns that site's name. |
| `JS - Attribution - utm_source` | `utm_source` value from the `lnm_attribution` cookie | The traffic source saved on first visit (e.g. `google`). |
| `JS - Attribution - utm_medium` | `utm_medium` from cookie | The channel (e.g. `cpc` for paid search). |
| `JS - Attribution - utm_campaign` | `utm_campaign` from cookie | The campaign name. |
| `JS - Attribution - utm_term` | `utm_term` from cookie | The search keyword. |
| `JS - Attribution - utm_content` | `utm_content` from cookie | The ad variant. |
| `JS - Attribution - gclid` | `gclid` from cookie | Google's click ID — ties back to a specific ad click. |
| `JS - Attribution - msclkid` | `msclkid` from cookie | Microsoft's click ID — same concept for Bing ads. |

### Constant Variables (fill in per client)

| Variable Name | Value | Used By |
|---|---|---|
| `C - CallRail Account ID` | CallRail company ID | CallRail DNI tag |
| `C - Meta Pixel ID` | `PLACEHOLDER` | Meta Pixel tag |
| `C - TikTok Pixel ID` | `PLACEHOLDER` | TikTok Pixel tag |
| `C - LinkedIn Partner ID` | `PLACEHOLDER` | LinkedIn Insight tag |
| `C - Microsoft UET ID` | `PLACEHOLDER` | Microsoft UET tag |

### Built-in Variables Enabled

| Variable | Used By |
|---|---|
| `Click URL` | Phone click triggers — reads the `href` of what was clicked |
| `Click Text` | Enabled alongside Click URL |
| `New History Fragment` | HC - Text Fragment trigger — reads the `#fragment` of the URL |

---

## GAds Conversion Action → GTM Tag Chain

```
Google Ads Account: AW-{conversion_id}
│
├── Conversion: Booked Appointment  ($65)
│     Label: {gads_appt_label}
│     GTM Tag: GAds - {store} - Booked_Appointment
│     │
│     └── Fires when trigger fires:
│           CE - {Scheduler} - Appointment Booked
│             │
│             └── Listens for dataLayer event:
│                   OktoRocket  → dc-service-booked
│                   Shop Genie  → appointment_booked
│                   AutoOps     → ao-appointment-booked
│                   SteerCRM    → ao-appointment-booked (same platform)
│                   Shopmonkey  → sm_work_request_form_event
│                   TekMetric   → tekmetric-booking-closed (postMessage bridge)
│                   Protractor  → (none — uses form submit fallback)
│
└── Conversion: Phone Click  ($10)
      Label: {gads_phone_label}
      GTM Tag: GAds - {store} - Phone_Click - {number}
      │
      └── Fires when trigger fires:
            CL - Phone Click - {number}
              │
              └── Listens for: Click URL contains {phone digits}
```

---

## Per-Client Data Required (Supabase → script)

| Field | Where It Comes From | What It Powers |
|---|---|---|
| `gtm_id` | GTM UI / client setup | Container lookup |
| `gtm_account_id` | GTM UI | Skips full account scan |
| `gtm_container_id` | GTM UI | Skips full account scan |
| `ga4_measurement_id` | GA4 Admin → Data Streams | GA4 Configuration tag |
| `gads_conversion_id` | GAds UI / GAds API | `conversionId` on all GAds tags |
| `gads_appt_label` | GAds UI / GAds API | GAds Booked_Appointment tag |
| `gads_phone_label` | GAds UI / GAds API | GAds Phone_Click tag |
| `phone_number` | Client onboarding | Phone click trigger + Phone_Click tag |
| `scheduler_type` | Client onboarding / fetch_ga4_id.py auto-detect | Appointment trigger event name |
| `callrail_account_id` | CallRail UI | CallRail DNI tag |
| `callrail_company_id` | CallRail UI | CallRail DNI tag + swap.js URL |

---

## Setup Script

```bash
# Standard run — reads all data from Supabase, enriches from GAds API
cd /llmprojects/lnm-gtm
source venv/bin/activate
python3 setup_tags.py --gads-cid {GAds_CID}

# When Supabase record is missing or incomplete — pass all fields as flags
python3 setup_tags.py \
  --gads-cid      {GAds_CID} \
  --gtm-id        GTM-XXXXXXX \
  --ga4-id        G-XXXXXXXXXX \
  --gads-conversion-id  123456789 \
  --appt-label    AbCdEfGhIjK \
  --name          "Client Name" \
  --scheduler     oktorocket     # oktorocket | shopgenie | autoops | steercrm | shopmonkey | tekmetric | protractor

# Useful flags
--dry-run              # preview everything, no API calls made
--force-recreate       # delete existing items and replace them (clean slate)
--location-id UUID     # when a GAds CID matches multiple Supabase rows, target a specific one
--account-id NUM       # provide GTM account ID directly, skips full account scan
```
