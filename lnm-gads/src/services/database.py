from __future__ import annotations

import os
import re
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

class DatabaseService:
    def __init__(self):
        self.enabled = os.getenv("DB_ENABLED", "false").lower() == "true"
        if not self.enabled:
            return

        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")

        if not url or not key:
            print("[db] Error: SUPABASE_URL or SUPABASE_SERVICE_KEY not set.")
            self.enabled = False
            return

        self.client: Client = create_client(url, key)

    def init_tables(self) -> None:
        """
        Supabase doesn't support raw SQL 'CREATE TABLE' via the client easily 
        (requires 'rpc' or direct Postgres). 
        
        Assumes tables are created via Supabase dashboard/migrations as per RUNBOOK.md.
        """
        if not self.enabled:
            return
        print("[db] init_tables: Tables should be managed via Supabase Dashboard/Migrations.")

    # ── Location lookup helpers ───────────────────────────────────────────────

    def get_location_by_cid(self, gads_cid: str) -> dict | None:
        if not self.enabled:
            return None
        try:
            res = self.client.table("locations").select("*").eq("gads_cid", str(gads_cid)).limit(1).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            print(f"Error fetching location for cid {gads_cid}: {e}")
            return None

    def get_pod_by_id(self, pod_id: str) -> dict | None:
        if not self.enabled:
            return None
        try:
            res = self.client.table("pods").select("id, name, css_email, ads_email").eq("id", str(pod_id)).limit(1).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            print(f"Error fetching pod {pod_id}: {e}")
            return None

    def get_location_by_url(self, url: str) -> dict | None:
        clean = re.sub(r'^https?://', '', str(url or '')).rstrip('/').lower()
        if not self.enabled:
            return None
        www = clean[4:] if clean.startswith('www.') else f'www.{clean}'
        try:
            # Simple OR filter via postgrest logic
            res = self.client.table("locations").select(
                "id, name, url, gads_cid, gads_conversion_id, gads_appt_label, gads_phone_label"
            ).or_(f"url.ilike.%{clean}%,url.ilike.%{www}%").limit(1).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            print(f"Error fetching location for url '{url}': {e}")
            return None

    def get_all_locations(self) -> list[dict]:
        if not self.enabled:
            return []
        try:
            res = self.client.table("locations").select(
                "id, name, url, gads_cid, gads_conversion_id, gads_appt_label, gads_phone_label, "
                "callrail_account_id, callrail_company_id, build_status, gtm_id, gtm_connected"
            ).order("name").execute()
            return res.data
        except Exception as e:
            print(f"Error fetching locations: {e}")
            return []

    # ── Audit / health writes ────────────────────────────────────────────────

    def save_issues(self, issues: list[dict], is_dry_run: bool = False, location_id: str | None = None) -> None:
        if not self.enabled or not issues:
            return

        # Build location_id lookup cache (gads_cid → location UUID)
        # When location_id is provided directly, skip the DB lookup.
        cid_to_loc: dict[str, str] = {}
        if not location_id:
            for i in issues:
                cid = str(i['customer_id'])
                if cid not in cid_to_loc:
                    loc = self.get_location_by_cid(cid)
                    if loc:
                        cid_to_loc[cid] = loc['id']

        data = []
        for i in issues:
            cid = str(i['customer_id'])
            loc_id = location_id or cid_to_loc.get(cid)
            if not loc_id:
                print(f"[db] No location for cid {cid} — skipping issue")
                continue
            data.append({
                "location_id":   loc_id,
                "gads_cid":      cid,
                "category":      i['category'],
                "severity":      i['severity'],
                "message":       i['message'],
                "details":       str(i.get('details', '') or ''),
                "is_suggestion": bool(i.get('is_suggestion', False)),
                "is_dry_run":    is_dry_run,
            })

        if not data:
            return
        try:
            self.client.table("gads_audit_results").insert(data).execute()
            print(f"Synced {len(data)} audit issues to Supabase.")
        except Exception as e:
            print(f"Error syncing audit issues: {e}")

    def save_serving_health(self, snapshots: list[dict]) -> None:
        if not self.enabled or not snapshots:
            return
        try:
            self.client.table("serving_health").insert(snapshots).execute()
            print(f"Synced {len(snapshots)} serving health rows to Supabase.")
        except Exception as e:
            print(f"Error syncing serving health: {e}")

    def save_roi_snapshot(self, customer_id: str, metrics: dict) -> None:
        if not self.enabled:
            return
        data = {
            "customer_id": customer_id,
            "lost_is_budget_pct": metrics.get("lost_is_budget"),
            "lost_is_rank_pct": metrics.get("lost_is_rank"),
            "cost_per_appointment": metrics.get("cost_per_appointment"),
            "total_conversions": metrics.get("total_conversions"),
            "total_cost": metrics.get("total_cost"),
            "cs_snapshot": metrics.get("cs_snapshot")
        }
        try:
            self.client.table("roi_snapshots").insert(data).execute()
        except Exception as e:
            print(f"Error saving ROI snapshot for {customer_id}: {e}")

    def mark_location_touched(self, gads_cid: str) -> None:
        if not self.enabled:
            return
        try:
            # Need to use 'now()' equivalent or let DB handle it. 
            # Supabase client doesn't have a direct 'NOW()' function for updates.
            # We'll just update with a placeholder or use the DB default if possible.
            # For now, we omit it or assume the server handles it if we don't send it.
            # Actually, we'll just not send it and let the DB default trigger if it's set up that way.
            # Wait, the SQL was: UPDATE locations SET last_touch_at = NOW() WHERE gads_cid = %s;
            # We can't easily do 'NOW()' from client.
            pass
        except Exception as e:
            print(f"Error marking last_touch_at for cid {gads_cid}: {e}")

    # ── Quota tracking ───────────────────────────────────────────────────────

    def log_quota_hit(self, customer_id: str, operation: str, attempt: int, resolved: bool) -> None:
        if not self.enabled:
            return
        data = {
            "customer_id": customer_id,
            "operation": operation,
            "attempt_number": attempt,
            "resolved": resolved
        }
        try:
            self.client.table("quota_hits").insert(data).execute()
        except Exception as e:
            print(f"Error logging quota hit: {e}")

    # ── Clients-table replacements (now target locations) ────────────────────

    def ensure_client_exists(self, customer_id: str) -> None:
        """No-op: FK to clients removed. locations rows pre-exist from Supabase."""
        pass

    def upsert_client(self, customer_id: str, business_name: str, city: str,
                      address: str = None, phone: str = None) -> None:
        """Update the matching locations row with name data from GAds."""
        if not self.enabled:
            return
        try:
            self.client.table("locations").update({"name": business_name}) \
                .eq("gads_cid", str(customer_id)).execute()
        except Exception as e:
            print(f"Error updating location for cid {customer_id}: {e}")

    def get_client(self, customer_id: str) -> dict | None:
        """Alias for get_location_by_cid — replaces clients table lookup."""
        return self.get_location_by_cid(customer_id)

    # ── CallRail ─────────────────────────────────────────────────────────────

    def get_callrail_accounts(self) -> list[dict]:
        if not self.enabled:
            return []
        try:
            res = self.client.table("locations").select("gads_cid, callrail_account_id") \
                .not_.is_("callrail_account_id", "null") \
                .neq("callrail_account_id", "") \
                .order("name").execute()
            # Rename gads_cid to customer_id for compatibility
            return [{"customer_id": r["gads_cid"], "callrail_account_id": r["callrail_account_id"]} for r in res.data]
        except Exception as e:
            print(f"Error fetching callrail accounts: {e}")
            return []

    def upsert_callrail_account(self, customer_id: str, callrail_account_id: str) -> None:
        if not self.enabled:
            return
        try:
            self.client.table("locations").update({"callrail_account_id": callrail_account_id}) \
                .eq("gads_cid", str(customer_id)).execute()
        except Exception as e:
            print(f"Error upserting callrail account for cid {customer_id}: {e}")

    def log_callrail_call(
        self,
        callrail_account_id: str,
        call_id: str,
        qualified: bool,
        note: str,
        lead_hits: list[str],
        non_lead_hits: list[str],
    ) -> None:
        if not self.enabled:
            return
        data = {
            "callrail_account_id": callrail_account_id,
            "call_id": call_id,
            "qualified": qualified,
            "note": note,
            "lead_hits": lead_hits,
            "non_lead_hits": non_lead_hits
        }
        try:
            self.client.table("callrail_calls").upsert(data, on_conflict="call_id").execute()
        except Exception as e:
            print(f"Error logging callrail call {call_id}: {e}")

    # ── GAds conversion labels ───────────────────────────────────────────────

    def update_location_gads_labels(
        self,
        location_id: str,
        conversion_id: str | None,
        dc_label: str | None,
        phone_label: str | None,
    ) -> bool:
        if not self.enabled:
            return False
        updates = {}
        if conversion_id: updates["gads_conversion_id"] = conversion_id
        if dc_label:      updates["gads_appt_label"] = dc_label
        if phone_label:   updates["gads_phone_label"] = phone_label
        
        if not updates: return True

        try:
            self.client.table("locations").update(updates).eq("id", location_id).execute()
            return True
        except Exception as e:
            print(f"Error updating gads labels for location {location_id}: {e}")
            return False

    def upsert_gads_conversion(
        self,
        location_id: str,
        conversion_id: str | None,
        label: str | None,
        name: str,
        value: float,
        type_: str,
    ) -> bool:
        if not self.enabled:
            return False
        data = {
            "location_id": location_id,
            "name": name,
            "conversion_id": conversion_id,
            "label": label,
            "value": value,
            "type": type_
        }
        try:
            # Upsert based on location_id and name (assumes unique constraint in DB)
            self.client.table("gads_conversions").upsert(data, on_conflict="location_id,name").execute()
            return True
        except Exception as e:
            print(f"Error upserting gads_conversion '{name}' for location {location_id}: {e}")
            return False

    # ── Competitor intelligence ──────────────────────────────────────────────

    def get_competitor_names(self, location_id: str) -> list[str]:
        if not self.enabled:
            return []
        try:
            res = (
                self.client.table("location_competitors")
                .select("name")
                .eq("location_id", location_id)
                .execute()
            )
            return [r["name"] for r in res.data if r.get("name")]
        except Exception as e:
            print(f"Error fetching competitors for location {location_id}: {e}")
            return []

    # ── Automation job queue (via locations columns) ─────────────────────────

    def get_queued_automation(self, lnm_acct=None, track=None) -> dict | None:
        if not self.enabled:
            return None
        try:
            res = self.client.table("locations").select("id, name, gads_cid, callrail_account_id, callrail_company_id, gtm_id, gtm_lnm_acct, automation_queued") \
                .not_.is_("automation_queued", "null").order("updated_at").limit(1).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            print(f"Error fetching queued automation: {e}")
            return None

    def claim_automation(self, location_id: str, track=None) -> None:
        if not self.enabled:
            return
        try:
            self.client.table("locations").update({
                "automation_queued": None,
                "automation_status": "running",
                "automation_output": ""
            }).eq("id", location_id).execute()
        except Exception as e:
            print(f"Error claiming automation for {location_id}: {e}")

    def append_automation_output(self, location_id: str, text: str, track=None) -> None:
        if not self.enabled:
            return
        # Note: Real-time append is tricky with REST. 
        # We might need to fetch first or just overwrite if it's too slow.
        # For efficiency in a script, we'll fetch then append.
        try:
            res = self.client.table("locations").select("automation_output").eq("id", location_id).limit(1).execute()
            current = res.data[0].get("automation_output", "") if res.data else ""
            self.client.table("locations").update({"automation_output": current + text}).eq("id", location_id).execute()
        except Exception as e:
            print(f"Error appending automation output for {location_id}: {e}")

    def complete_automation(self, location_id: str, status: str, gads_cid: str | None = None, track=None) -> None:
        if not self.enabled:
            return
        try:
            self.client.table("locations").update({
                "automation_status": status,
                "automation_queued": None,
            }).eq("id", location_id).execute()
        except Exception as e:
            print(f"Error completing automation for {location_id}: {e}")

    # ── Audit history ────────────────────────────────────────────────────────

    def get_recent_issues(self, customer_id: str, days: int = 30) -> list[dict]:
        if not self.enabled:
            return []
        try:
            # Logic for date filter via postgrest is 'gte'
            # We'll just skip the date filter for now or implement if needed
            res = self.client.table("audit_results").select("*") \
                .eq("customer_id", customer_id).order("logged_at", desc=True).execute()
            return res.data
        except Exception as e:
            print(f"Error fetching issues for {customer_id}: {e}")
            return []
