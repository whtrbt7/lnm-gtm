# GTM Agency Standards (V3.0 - Enterprise Multi-Client)

## 1. Container Organization & Governance
*Objective: Ensure 600+ containers are identical in structure for automated auditing and bulk updates.*

### **Folder Structure (Mandatory)**
All items must be assigned to one of these four folders:
1.  **10 - Infrastructure:** Base tags (GA4 Config, Conversion Linker, CallRail DNI).
2.  **20 - Conversions:** GAds/GA4/Meta conversion tags.
3.  **30 - Variables:** All user-defined constant variables.
4.  **40 - Triggers:** All event, click, and pageview triggers.

### **Naming Convention**
- **Tags:** `[Vendor] - [Type] - [Description]` (e.g., `GAds - Conv - Appointment Booked`)
- **Triggers:** `[Event Type] - [Description]` (e.g., `CE - AutoOps - Appointment Booked` or `CLK - Phone - 5551234567`)
- **Variables:** `[Type] - [Description]` (e.g., `C - GAds ID` or `DLV - Appointment ID`)

---

## 2. Standardized Variables (The "Engine")
*Objective: Remove hardcoded IDs from tags to allow for rapid cloning via API.*

Every container **must** include these Constant variables:
- `C - GAds ID`: The 9-digit Google Ads Conversion ID.
- `C - GA4 ID`: The `G-XXXXXXXX` Measurement ID.
- `C - CallRail Account ID`: The CallRail account number.
- `C - Shop Name`: The specific location name used for dynamic tagging.

---

## 3. Robust Conversion Tracking
*Objective: Maximize data quality and attribution recovery.*

### **Enhanced Conversions (Requirement)**
- All Lead Form tags must enable **"Include user-provided data from your website."**
- A `User Provided Data` variable must be configured to automatically capture:
    - `Email` (captured from form field `input[type="email"]`)
    - `Phone Number` (captured from form field `input[type="tel"]`)

### **The Automotive Conversion Stack**
1.  **GA4 Base:** Fire the Google Tag on `All Pages`.
2.  **Conversion Linker:** Fire on `All Pages` (Enable across all domains).
3.  **CallRail DNI:** The CallRail snippet must fire on `All Pages` with the `swap_target` set to the agency standard CSS selector.
4. **Scheduler Events:**
    - Listen for `ao-appointment-booked` (AutoOps), `dc-service-booked` (OktoRocket), or `appointment_booked` (Shop Genie).
    - Map these to both **GA4 Events** and **GAds Conversions**.

### **Multi-Pixel Integration (Meta, LinkedIn, etc.)**
To ensure full-funnel remarketing and cross-channel attribution, every container must include:
1.  **Meta Pixel (Base Tag):** Fire on `All Pages`.
2.  **Meta Conversions API (CAPI):** Must be configured via SSGTM to send redundant server-side events for `Lead` and `Schedule`.
3.  **LinkedIn Insight Tag:** Fire on `All Pages` for high-ticket/commercial-focused repair shops.
4.  **Microsoft Advertising (UET):** Fire on `All Pages` for clients targeting the 55+ demographic (high Bing usage).
5.  **Standardized Event Mapping:** Vendor-specific events must mirror the Google stack:
    - `Schedule` (Meta) = `ao-appointment-booked`
    - `Lead` (Meta) = `Form Submission`


---

## 4. Trigger Logic Standards
*Objective: Eliminate "Junk" conversions.*

- **Phone Clicks:** Link click triggers must filter for `tel:` and specifically the shop's tracking number.
- **Form Submissions:** Prefer "Custom Event" triggers (fired by the form vendor) over GTM's "Form Submission" trigger to avoid capturing partial or failed entries.
- **Visibility Triggers:** Use for "Thank You" message confirmation if no redirect or custom event is available.

---

## 5. Automated Deployment (API Standards)
*Objective: All updates must be pushed via the `setup_new_account.py` framework.*

- **Idempotency:** Scripts must check if a tag/trigger exists before creating a duplicate.
- **Environment:** Containers should ideally have a `LIVE` and `STAGING` environment to test new vendor integrations before rolling out to all 600 clients.

---

## 6. V3.1 - World-Class "High-Performance" Upgrades
*Objective: Maximize data durability, bypass ad-blockers, and enable Value-Based Bidding.*

### **A. Server-Side Tagging (SSGTM)**
- **Requirement:** Deploy a Server-Side GTM container on a first-party subdomain (e.g., `metrics.victoryauto.com`).
- **Benefits:** 
    - Extends cookie life from 7 days (ITP) to 1-2 years.
    - Removes 3rd-party scripts from the browser, increasing PageSpeed scores.
    - Bypasses most browser-based ad-blockers for 15-20% more accurate data.

### **B. Advanced Consent Mode (V2)**
- **Standard:** Every container must use a Consent Management Platform (CMP).
- **Logic:** Enable "Advanced Consent Mode" to allow Google Ads to use **Conversion Modeling** for users who decline cookies, recovering up to 60% of lost conversion data.

### **C. Value-Based Bidding (VBB)**
- **Implementation:** Use a Lookup Table variable in GTM to assign an **Estimated Conversion Value** based on the lead type:
    - `Oil Change Inquiry`: $50
    - `Brake Repair inquiry`: $450
    - `Engine/Transmission Inquiry`: $2,500
    - `Appointment Booked`: $150 (Base)
- **Outcome:** Google’s "tROAS" bidding will focus on finding the high-ticket repair leads rather than just "cheap" oil change clicks.

### **D. Automated Health Monitoring**
- **Dead-Man’s Switch:** Implement a "Tag Monitoring" script. If the `Primary Conversion` count drops by more than 50% week-over-week, an automated alert is sent to the Account Manager.

### **E. First-Party Data Enrichment (Hashed)**
- **Beyond Email:** Capture `First Name`, `Last Name`, and `Zip Code` from the AutoOps/Scheduler data layer.
- **Hashing:** All data must be SHA-256 hashed before transmission to GAds/Meta for 100% privacy compliance.
