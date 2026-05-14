import json
import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import pandas as pd

from src.services.database import DatabaseService


class ReportingService:
    def __init__(self, output_dir="reports"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.issues = []
        self.cs_snapshot = ""
        self.db = DatabaseService()

    def log_issue(self, cid, category, severity, message, details=None):
        """Log a specific issue found during an audit."""
        self.issues.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "customer_id": cid,
            "category": category,
            "severity": severity,  # INFO, WARNING, CRITICAL
            "message": message,
            "details": details,
        })

    def _build_email_body(self, client_name: str, gads_cid: str, dry_run: bool) -> str:
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        mode = "DRY RUN" if dry_run else "LIVE"

        criticals = [i for i in self.issues if i["severity"] == "CRITICAL"]
        warnings  = [i for i in self.issues if i["severity"] == "WARNING"]
        infos     = [i for i in self.issues if i["severity"] == "INFO"]

        lines = [
            f"GAds Optimization Report — {client_name} (CID {gads_cid})",
            f"Run: {date_str} [{mode}]",
            f"Issues: {len(criticals)} critical · {len(warnings)} warnings · {len(infos)} info",
            "",
        ]

        for label, group in [("CRITICAL", criticals), ("WARNING", warnings), ("INFO", infos)]:
            if not group:
                continue
            lines.append(f"── {label} ({'%d' % len(group)}) ──────────────────────")
            for i in group:
                detail = f" — {i['details']}" if i.get("details") else ""
                lines.append(f"  [{i['category']}] {i['message']}{detail}")
            lines.append("")

        if not self.issues:
            lines.append("No issues found — account looks healthy.")

        lines += [
            "──────────────────────────────────────",
            "LeadsNearMe GAds Automation",
        ]
        return "\n".join(lines)

    def _build_email_html(self, client_name: str, gads_cid: str, dry_run: bool) -> str:  # noqa: C901
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        mode = "DRY RUN" if dry_run else "LIVE"

        # Snapshot issues rendered as structured sections, not issue rows
        kpi_issue = next((i for i in self.issues if i["message"] == "30-day KPI snapshot"), None)
        kw_issue  = next((i for i in self.issues if i["message"] == "Keyword inventory snapshot"), None)
        snapshot_ids = {id(i) for i in [kpi_issue, kw_issue] if i}
        display = [i for i in self.issues if id(i) not in snapshot_ids]

        criticals = [i for i in display if i["severity"] == "CRITICAL"]
        warnings  = [i for i in display if i["severity"] == "WARNING"]
        infos     = [i for i in display if i["severity"] == "INFO"]

        all_c = sum(1 for i in self.issues if i["severity"] == "CRITICAL")
        all_w = sum(1 for i in self.issues if i["severity"] == "WARNING")
        all_i = sum(1 for i in self.issues if i["severity"] == "INFO")

        # High-contrast color palette (solid only — no rgba)
        T = "#f0f6fc"   # headline / primary text
        B = "#e6edf3"   # body text
        S = "#c9d1d9"   # secondary text
        M = "#adbac7"   # muted labels
        D = "#768390"   # very muted / dividers

        SEV = {
            "CRITICAL": {"label": "#f47067", "bg": "#200d0d", "border": "#6e2020", "tag_bg": "#3a1515"},
            "WARNING":  {"label": "#e3b341", "bg": "#1e1a0d", "border": "#6e5510", "tag_bg": "#3a2c0e"},
            "INFO":     {"label": "#6cb6ff", "bg": "#0d1420", "border": "#1e4080", "tag_bg": "#0f2040"},
        }

        def _num(s: str) -> float:
            try:
                return float(re.sub(r"[^\d.]", "", s or "0"))
            except Exception:
                return 0.0

        def _sc(val: str, warn: float, crit: float = None,
                higher_is_better: bool = False) -> str:
            v = _num(val)
            if higher_is_better:
                if crit is not None and v < crit:
                    return "#f47067"
                return "#e3b341" if v < warn else "#3fb950"
            else:
                if crit is not None and v >= crit:
                    return "#f47067"
                return "#e3b341" if v >= warn else "#3fb950"

        def _parse(detail: str) -> dict:
            out: dict = {}
            for part in re.split(r"\s{2,}", (detail or "").strip()):
                if ": " in part:
                    k, v = part.split(": ", 1)
                    out[k.strip()] = v.strip()
            return out

        def _badge(count: int, color: str, bg: str) -> str:
            return (
                f'<span style="display:inline-block;background:{bg};color:{color};'
                f'border:1px solid {color};border-radius:10px;padding:1px 9px;'
                f'font-size:11px;font-weight:700;line-height:20px;">{count}</span>'
            )

        def _delta_color(d: str) -> str:
            return "#3fb950" if d.startswith("+") else "#f47067"

        def _metric_cell(label: str, value: str, color: str = "", last: bool = False,
                         delta_30: str = "", delta_yoy: str = "") -> str:
            val_color = color or T
            border = "" if last else "border-right:1px solid #21262d;"
            delta_html = ""
            if delta_30 or delta_yoy:
                parts = []
                if delta_30:
                    parts.append(
                        f'<span style="color:{_delta_color(delta_30)};">{delta_30}</span>'
                        f'<span style="color:{D};"> MoM</span>'
                    )
                if delta_yoy:
                    parts.append(
                        f'<span style="color:{_delta_color(delta_yoy)};">{delta_yoy}</span>'
                        f'<span style="color:{D};"> YoY</span>'
                    )
                sep = f'<span style="color:{D};"> &nbsp;·&nbsp; </span>'
                delta_html = (
                    f'<div style="font-size:9px;margin-top:6px;line-height:1.6;">'
                    + sep.join(parts)
                    + f'</div>'
                )
            return (
                f'<td style="padding:14px 6px;text-align:center;{border}">'
                f'<div style="font-size:9px;font-weight:700;letter-spacing:0.07em;color:{M};'
                f'text-transform:uppercase;margin-bottom:8px;">{label}</div>'
                f'<div style="font-size:20px;font-weight:700;color:{val_color};'
                f'font-variant-numeric:tabular-nums;">{value}</div>'
                f'{delta_html}'
                f'</td>'
            )

        def _legend_table(rows: list) -> str:
            hdr = (
                f'<tr>'
                f'<td style="padding:6px 10px;font-size:10px;font-weight:700;letter-spacing:0.06em;'
                f'color:{M};text-transform:uppercase;border-bottom:1px solid #30363d;">Metric</td>'
                f'<td style="padding:6px 10px;font-size:10px;font-weight:700;color:#3fb950;'
                f'border-bottom:1px solid #30363d;">● Good</td>'
                f'<td style="padding:6px 10px;font-size:10px;font-weight:700;color:#e3b341;'
                f'border-bottom:1px solid #30363d;">● Warning</td>'
                f'<td style="padding:6px 10px;font-size:10px;font-weight:700;color:#f47067;'
                f'border-bottom:1px solid #30363d;">● Critical</td>'
                f'</tr>'
            )
            data = []
            for idx, (metric, good, warn, crit) in enumerate(rows):
                rb = "#0f1218" if idx % 2 == 0 else "#161b22"
                data.append(
                    f'<tr style="background:{rb};">'
                    f'<td style="padding:5px 10px;font-size:11px;color:{S};'
                    f'border-bottom:1px solid #21262d;">{metric}</td>'
                    f'<td style="padding:5px 10px;font-size:11px;color:#3fb950;">{good}</td>'
                    f'<td style="padding:5px 10px;font-size:11px;color:#e3b341;">{warn}</td>'
                    f'<td style="padding:5px 10px;font-size:11px;color:#f47067;">{crit}</td>'
                    f'</tr>'
                )
            return (
                f'<div style="margin-top:14px;">'
                f'<div style="font-size:9px;font-weight:700;letter-spacing:0.1em;color:{M};'
                f'text-transform:uppercase;margin-bottom:6px;">Color Guide</div>'
                f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                f'style="border:1px solid #30363d;border-radius:4px;border-collapse:collapse;'
                f'background:#161b22;">{hdr}{"".join(data)}</table>'
                f'</div>'
            )

        def _metric_section(icon: str, title: str, metrics_html: str, legend_html: str) -> str:
            return (
                f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                f'style="border:1px solid #30363d;border-radius:6px;'
                f'margin-bottom:16px;border-collapse:collapse;">'
                f'<tr style="background:#0d1117;">'
                f'<td style="padding:10px 14px;border-bottom:1px solid #30363d;">'
                f'<span style="font-size:10px;font-weight:700;letter-spacing:0.1em;'
                f'color:{M};text-transform:uppercase;">{icon} {title}</span>'
                f'</td></tr>'
                f'<tr><td style="background:#161b22;padding:0;">'
                f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                f'style="border-collapse:collapse;">{metrics_html}</table>'
                f'</td></tr>'
                f'<tr><td style="background:#161b22;padding:12px 14px;'
                f'border-top:1px solid #21262d;">{legend_html}</td></tr>'
                f'</table>'
            )

        def _row(icon_html: str, content_html: str, last: bool = False) -> str:
            bb = "" if last else "border-bottom:1px solid #21262d;"
            return (
                f'<table width="100%" cellpadding="0" cellspacing="0" border="0"'
                f' style="margin-bottom:0;{bb}"><tr>'
                f'<td style="padding:9px 0;width:18px;vertical-align:top;">{icon_html}</td>'
                f'<td style="padding:9px 0 9px 8px;font-size:13px;color:{B};'
                f'line-height:1.5;vertical-align:top;">{content_html}</td>'
                f'</tr></table>'
            )

        # ── Parse shared data ────────────────────────────────────────────────
        kpi_data: dict = _parse(kpi_issue.get("details", "")) if kpi_issue else {}
        kw_data: dict  = _parse(kw_issue.get("details", "")) if kw_issue else {}

        conv_str     = kpi_data.get("Conv", "")
        cpl_str      = kpi_data.get("CPL", "")
        spend_str    = kpi_data.get("Spend", "")
        lost_bud_str = kpi_data.get("Lost IS (budget)", "")
        lost_rnk_str = kpi_data.get("Lost IS (rank)", "")
        ctr_str      = kpi_data.get("CTR", "")

        conv_mom_str   = kpi_data.get("Conv30", "")
        conv_yoy_str   = kpi_data.get("ConvYoY", "")
        cpl_mom_str    = kpi_data.get("CPL30", "")
        cpl_yoy_str    = kpi_data.get("CPLYoY", "")
        spend_mom_str  = kpi_data.get("Spend30", "")
        spend_yoy_str  = kpi_data.get("SpendYoY", "")
        clicks_mom_str = kpi_data.get("Clicks30", "")
        clicks_yoy_str = kpi_data.get("ClicksYoY", "")
        impr_mom_str   = kpi_data.get("Impr30", "")
        impr_yoy_str   = kpi_data.get("ImprYoY", "")

        neg_str    = kw_data.get("Negatives", "")
        avg_qs_str = kw_data.get("Avg QS", "")
        low_qs_str = kw_data.get("Low QS (≤4)", kw_data.get("Low QS (<=4)", ""))

        lost_bud_n  = _num(lost_bud_str)
        conv_n      = _num(conv_str)

        neg_added = next((i for i in self.issues if i["category"] == "NEGATIVE_ADDED"), None)
        comp_negs = next((i for i in self.issues if i["category"] == "COMPETITOR_NEGATIVES"), None)

        # ── CSM Card 1: Client Call Script ────────────────────────────────
        call_rows = []

        if kpi_data:
            lead_line = (
                f'<b style="color:{T};">{conv_str or "—"} MQLs</b>'
                f'<span style="color:{S};"> this month &nbsp;·&nbsp; </span>'
                f'<b style="color:{T};">{cpl_str or "—"}</b>'
                f'<span style="color:{S};"> avg CPL &nbsp;·&nbsp; {spend_str or "—"} total spend</span>'
            )
            call_rows.append(_row(f'<span style="color:#6cb6ff;font-weight:700;">›</span>', lead_line))

            if lost_bud_n < 20:
                bud_line = (
                    f'<b style="color:#3fb950;">Budget capturing ~{100 - int(lost_bud_n)}% of local search demand</b>'
                    f'<span style="color:{S};"> ({int(lost_bud_n)}% lost to cap)</span>'
                )
            elif lost_bud_n < 50:
                bud_line = (
                    f'<b style="color:#e3b341;">Missing ~{int(lost_bud_n)}% of searchers to budget cap</b>'
                    f'<span style="color:{S};"> — budget recommendation below</span>'
                )
            else:
                bud_line = (
                    f'<b style="color:#f47067;">Budget-capped — losing {int(lost_bud_n)}% of search traffic</b>'
                    f'<span style="color:{S};"> — escalate to client immediately</span>'
                )
            call_rows.append(_row(f'<span style="color:#6cb6ff;font-weight:700;">›</span>', bud_line))

        auto_parts = []
        if neg_added:
            m = re.search(r"(\d+) search terms", neg_added["message"])
            if m:
                verb = "Pruned" if "Pruned" in neg_added["message"] else "Would prune"
                auto_parts.append(f"{verb.lower()} {m.group(1)} junk search terms")
        if comp_negs:
            m = re.search(r"(\d+) competitor", comp_negs["message"])
            if m:
                verb = "Added" if "Added" in comp_negs["message"] else "Would add"
                auto_parts.append(f"{verb.lower()} {m.group(1)} competitor negatives")
        if auto_parts:
            auto_line = (
                f'<span style="color:{M};">Automation: </span>'
                f'<span style="color:{S};">{"; ".join(auto_parts)}</span>'
            )
            call_rows.append(_row(f'<span style="color:{D};">›</span>', auto_line))

        if self.cs_snapshot:
            snap_line = f'<span style="color:{M};font-style:italic;">{self.cs_snapshot}</span>'
            call_rows.append(_row(f'<span style="color:{D};">›</span>', snap_line, last=True))
        elif call_rows:
            # Mark last row
            call_rows[-1] = call_rows[-1].replace(
                "border-bottom:1px solid #21262d;", ""
            )

        talk_track = ""
        if kpi_data and conv_n > 0 and cpl_str and spend_str:
            if lost_bud_n < 20:
                budget_phrase = "Your budget is fully covering your local search area."
            else:
                budget_phrase = (
                    f"We are currently missing {int(lost_bud_n)}% of local searchers "
                    f"due to budget — I'll have a recommendation shortly."
                )
            talk_track = (
                f'<div style="background:#0f1218;border-left:3px solid #1e4080;'
                f'border-radius:0 4px 4px 0;padding:10px 12px;margin-top:12px;">'
                f'<div style="font-size:9px;font-weight:700;letter-spacing:0.1em;'
                f'color:{M};text-transform:uppercase;margin-bottom:6px;">Suggested Talk Track</div>'
                f'<div style="font-size:12px;color:{S};line-height:1.6;font-style:italic;">'
                f'"We generated <b style="color:{T};">{conv_str} leads</b> this month at '
                f'<b style="color:{T};">{cpl_str}</b> each ({spend_str} total spend). '
                f'{budget_phrase}"</div>'
                f'</div>'
            )

        csm_call_card = ""
        if call_rows:
            csm_call_card = (
                f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                f'style="border:1px solid #1e4080;border-radius:6px;'
                f'margin-bottom:12px;border-collapse:collapse;">'
                f'<tr style="background:#0d1420;">'
                f'<td style="padding:10px 14px;border-bottom:1px solid #1e4080;">'
                f'<span style="font-size:10px;font-weight:700;letter-spacing:0.1em;'
                f'color:#6cb6ff;text-transform:uppercase;">🎯 For Your Client Call</span>'
                f'</td></tr>'
                f'<tr><td style="background:#161b22;padding:14px;">'
                f'{"".join(call_rows)}{talk_track}'
                f'</td></tr>'
                f'</table>'
            )

        # ── CSM Card 2: Budget Opportunity ────────────────────────────────
        budget_recs = [i for i in self.issues if i["category"] == "BUDGET_REC"]
        csm_budget_card = ""
        if budget_recs:
            rec_blocks = []
            for issue in budget_recs:
                m = re.search(
                    r"(.+?): losing (\d+)% to budget — recommend \$(\d+)/day "
                    r"\(currently \$(\d+)/day\)",
                    issue["message"],
                )
                if not m:
                    continue
                camp     = m.group(1)
                lost_pct = int(m.group(2))
                rec_bud  = int(m.group(3))
                cur_bud  = int(m.group(4))

                addl_html = ""
                if conv_n > 0 and lost_pct > 0:
                    full = conv_n / max(0.01, 1 - lost_pct / 100)
                    addl = int(full - conv_n)
                    addl_html = (
                        f'<span style="color:{S};">Est. </span>'
                        f'<b style="color:#3fb950;">+{addl} additional leads/month</b>'
                        f'<span style="color:{S};"> if approved</span>'
                    )

                rec_blocks.append(
                    f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                    f'style="background:#1a1208;border:1px solid #6e5510;border-radius:4px;'
                    f'margin-bottom:8px;border-collapse:collapse;">'
                    f'<tr><td style="padding:12px 14px;">'
                    f'<div style="font-size:13px;font-weight:700;color:{T};margin-bottom:6px;">{camp}</div>'
                    f'<div style="font-size:13px;margin-bottom:4px;">'
                    f'<span style="color:{M};">Current: </span>'
                    f'<b style="color:#f47067;">${cur_bud}/day</b>'
                    f'<span style="color:{D};"> &nbsp;→&nbsp; </span>'
                    f'<span style="color:{M};">Recommended: </span>'
                    f'<b style="color:#3fb950;">${rec_bud}/day</b>'
                    f'<span style="color:{D};">&nbsp; &nbsp;</span>'
                    f'<span style="color:{M};">Losing </span>'
                    f'<b style="color:#e3b341;">{lost_pct}%</b>'
                    f'<span style="color:{M};"> of impressions to cap</span>'
                    f'</div>'
                )
                addl_div = (
                    '<div style="font-size:12px;margin-top:4px;">' + addl_html + '</div>'
                    if addl_html else ""
                )
                rec_blocks.append(
                    f'{addl_div}'
                    f'</td></tr></table>'
                )

            if rec_blocks:
                action = (
                    f'<div style="font-size:12px;color:#e3b341;font-weight:700;margin-top:4px;">'
                    f'→ Discuss with client and get approval before the next run</div>'
                )
                csm_budget_card = (
                    f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                    f'style="border:1px solid #6e5510;border-radius:6px;'
                    f'margin-bottom:12px;border-collapse:collapse;">'
                    f'<tr style="background:#1e1a0d;">'
                    f'<td style="padding:10px 14px;border-bottom:1px solid #6e5510;">'
                    f'<span style="font-size:10px;font-weight:700;letter-spacing:0.1em;'
                    f'color:#e3b341;text-transform:uppercase;">⚡ Budget Opportunity — Approval Needed</span>'
                    f'</td></tr>'
                    f'<tr><td style="background:#161b22;padding:14px;">'
                    f'{"".join(rec_blocks)}{action}'
                    f'</td></tr>'
                    f'</table>'
                )

        # ── CSM Card 3: Pre-Call Checklist ────────────────────────────────
        STATUS_ICON  = {"GOOD": "✓", "WARN": "⚠", "CRIT": "✗", "NA": "·"}
        STATUS_COLOR = {"GOOD": "#3fb950", "WARN": "#e3b341", "CRIT": "#f47067", "NA": D}

        def _check_row(label: str, status: str, detail: str, last: bool = False) -> str:
            ic   = STATUS_ICON[status]
            col  = STATUS_COLOR[status]
            bb   = "" if last else "border-bottom:1px solid #21262d;"
            return (
                f'<tr>'
                f'<td style="padding:8px 14px;width:38%;{bb}vertical-align:top;">'
                f'<span style="font-size:12px;color:{S};font-weight:600;">{label}</span></td>'
                f'<td style="padding:8px 14px;{bb}vertical-align:top;">'
                f'<span style="color:{col};font-weight:700;margin-right:6px;">{ic}</span>'
                f'<span style="font-size:12px;color:{B};">{detail}</span></td>'
                f'</tr>'
            )

        checklist_rows = []

        # Conversion tracking
        conv_crit_issue = next(
            (i for i in self.issues if i["category"] == "CONV_TRACKING" and i["severity"] == "CRITICAL"),
            None,
        )
        conv_info_issue = next(
            (i for i in self.issues if i["category"] == "CONV_TRACKING" and i["severity"] == "INFO"),
            None,
        )
        if conv_crit_issue:
            checklist_rows.append(("Conversion Tracking", "CRIT", conv_crit_issue["message"]))
        elif conv_info_issue:
            checklist_rows.append(("Conversion Tracking", "GOOD", conv_info_issue["message"]))
        else:
            checklist_rows.append(("Conversion Tracking", "NA", "No data"))

        # Ad serving
        serving_crits = [i for i in self.issues if i["category"] == "SERVING" and i["severity"] == "CRITICAL"]
        if serving_crits:
            checklist_rows.append(("Ad Serving", "CRIT", serving_crits[0]["message"]))
        else:
            checklist_rows.append(("Ad Serving", "GOOD", "All campaigns serving normally"))

        # Keyword quality
        kw_qs_warn = next(
            (i for i in self.issues
             if i["category"] == "KEYWORDS" and "Quality Score" in i["message"]
             and i["severity"] == "WARNING"),
            None,
        )
        if kw_qs_warn:
            checklist_rows.append(("Keyword Quality", "WARN", kw_qs_warn["message"]))
        else:
            qs_detail = f"Avg QS {avg_qs_str}" if avg_qs_str else "No QS issues"
            checklist_rows.append(("Keyword Quality", "GOOD", qs_detail))

        # Budget coverage
        if kpi_data:
            if lost_bud_n >= 50:
                checklist_rows.append(("Budget Coverage", "CRIT",
                                        f"{int(lost_bud_n)}% of searches lost — severely capped"))
            elif lost_bud_n >= 20:
                checklist_rows.append(("Budget Coverage", "WARN",
                                        f"{int(lost_bud_n)}% of searches lost to budget cap"))
            else:
                checklist_rows.append(("Budget Coverage", "GOOD",
                                        f"{100 - int(lost_bud_n)}% of demand captured"))

        # Search hygiene
        if kw_data:
            neg_n = _num(neg_str)
            if neg_n < 20:
                checklist_rows.append(("Search Hygiene", "CRIT",
                                        f"Only {neg_str} negatives — under-filtered"))
            elif neg_n < 50:
                checklist_rows.append(("Search Hygiene", "WARN",
                                        f"{neg_str} negatives — below 50 threshold"))
            else:
                checklist_rows.append(("Search Hygiene", "GOOD",
                                        f"{neg_str} negative keywords active"))

        csm_checklist_card = ""
        if checklist_rows:
            rows_html = "".join(
                _check_row(label, status, detail, last=(idx == len(checklist_rows) - 1))
                for idx, (label, status, detail) in enumerate(checklist_rows)
            )
            csm_checklist_card = (
                f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                f'style="border:1px solid #2a5c3a;border-radius:6px;'
                f'margin-bottom:16px;border-collapse:collapse;">'
                f'<tr style="background:#0f2018;">'
                f'<td style="padding:10px 14px;border-bottom:1px solid #2a5c3a;">'
                f'<span style="font-size:10px;font-weight:700;letter-spacing:0.1em;'
                f'color:#3fb950;text-transform:uppercase;">✅ Pre-Call Checklist</span>'
                f'</td></tr>'
                f'<tr><td style="background:#161b22;padding:0;">'
                f'<table width="100%" cellpadding="0" cellspacing="0" border="0">{rows_html}</table>'
                f'</td></tr>'
                f'</table>'
            )

        csm_section = csm_call_card + csm_budget_card + csm_checklist_card

        # ── 30-Day Performance section ──────────────────────────────────────
        kpi_section = ""
        if kpi_issue:
            ctr_c = _sc(ctr_str, warn=2.0, higher_is_better=True)
            bud_c = _sc(lost_bud_str, warn=20.0, crit=50.0)
            rnk_c = _sc(lost_rnk_str, warn=35.0)
            metrics = (
                f'<tr>'
                f'{_metric_cell("Clicks", kpi_data.get("Clicks","—"), delta_30=clicks_mom_str, delta_yoy=clicks_yoy_str)}'
                f'{_metric_cell("Impr", kpi_data.get("Impr","—"), delta_30=impr_mom_str, delta_yoy=impr_yoy_str)}'
                f'{_metric_cell("CTR", ctr_str or "—", ctr_c)}'
                f'{_metric_cell("Conv", conv_str or "—", delta_30=conv_mom_str, delta_yoy=conv_yoy_str)}'
                f'{_metric_cell("CPL", cpl_str or "—", delta_30=cpl_mom_str, delta_yoy=cpl_yoy_str)}'
                f'{_metric_cell("Spend", spend_str or "—", delta_30=spend_mom_str, delta_yoy=spend_yoy_str)}'
                f'{_metric_cell("Lost IS Bud", lost_bud_str or "—", bud_c)}'
                f'{_metric_cell("Lost IS Rank", lost_rnk_str or "—", rnk_c, last=True)}'
                f'</tr>'
            )
            legend = _legend_table([
                ("CTR",              "≥2%",  "1–2%",   "<1%"),
                ("Conv Rate",        "≥7%",  "3–7%",   "<3%"),
                ("Lost IS (Budget)", "<20%", "20–50%", "≥50%"),
                ("Lost IS (Rank)",   "<35%", "≥35%",   "—"),
            ])
            kpi_section = _metric_section("📊", "30-Day Performance", metrics, legend)

        # ── Keyword Inventory section ───────────────────────────────────────
        kw_section = ""
        if kw_issue:
            qs_c  = _sc(avg_qs_str, warn=6.0, crit=5.0, higher_is_better=True)
            neg_c = _sc(neg_str, warn=50.0, crit=20.0, higher_is_better=True)
            lq_v  = _num(low_qs_str)
            lqs_c = "#f47067" if lq_v > 3 else ("#e3b341" if lq_v > 0 else "#3fb950")
            metrics = (
                f'<tr>'
                f'{_metric_cell("Total KWs", kw_data.get("Total KWs","—"))}'
                f'{_metric_cell("Exact", kw_data.get("Exact","—"))}'
                f'{_metric_cell("Phrase", kw_data.get("Phrase","—"))}'
                f'{_metric_cell("Broad", kw_data.get("Broad","—"))}'
                f'{_metric_cell("Negatives", neg_str or "—", neg_c)}'
                f'{_metric_cell("Avg QS", avg_qs_str or "—", qs_c)}'
                f'{_metric_cell("Low QS ≤4", low_qs_str or "—", lqs_c, last=True)}'
                f'</tr>'
            )
            legend = _legend_table([
                ("Avg QS",      "≥7",  "5–6",   "≤4"),
                ("Low QS (≤4)", "0",   "1–3",   ">3"),
                ("Negatives",   "≥50", "20–49", "<20"),
            ])
            kw_section = _metric_section("🔑", "Keyword Inventory", metrics, legend)

        # ── Issue rows ──────────────────────────────────────────────────────
        def _issue_rows(group, sev: str) -> str:
            s = SEV[sev]
            rows = []
            for issue in group:
                detail_html = (
                    f'<div style="color:{S};font-size:12px;margin-top:5px;line-height:1.5;">'
                    f'{issue["details"]}</div>'
                    if issue.get("details") else ""
                )
                tag = (
                    f'<span style="display:inline-block;font-size:9px;font-weight:700;'
                    f'letter-spacing:0.06em;color:{s["label"]};background:{s["tag_bg"]};'
                    f'border:1px solid {s["border"]};border-radius:3px;padding:1px 5px;'
                    f'margin-right:7px;vertical-align:middle;">'
                    f'{issue["category"].upper()}</span>'
                )
                rows.append(
                    f'<tr><td style="padding:11px 14px;border-bottom:1px solid #21262d;'
                    f'vertical-align:top;">'
                    f'<div style="color:{B};font-size:13px;line-height:1.5;">'
                    f'{tag}{issue["message"]}</div>'
                    f'{detail_html}'
                    f'</td></tr>'
                )
            return "".join(rows)

        def _section(label: str, group, sev: str) -> str:
            if not group:
                return ""
            s = SEV[sev]
            b = _badge(len(group), s["label"], s["tag_bg"])
            return (
                f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                f'style="border:1px solid {s["border"]};border-radius:6px;'
                f'margin-bottom:12px;border-collapse:collapse;">'
                f'<tr style="background:{s["bg"]};"><td style="padding:10px 14px;">'
                f'<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
                f'<td><span style="font-size:11px;font-weight:700;letter-spacing:0.08em;'
                f'color:{s["label"]};">● {label}</span></td>'
                f'<td align="right">{b}</td>'
                f'</tr></table>'
                f'</td></tr>'
                f'{_issue_rows(group, sev)}'
                f'</table>'
            )

        # ── Assembly ────────────────────────────────────────────────────────
        mode_pill = (
            f'<span style="font-size:10px;font-weight:700;background:#21262d;color:{M};'
            f'border:1px solid #30363d;border-radius:4px;padding:2px 8px;margin-left:8px;'
            f'letter-spacing:0.06em;">{mode}</span>'
        )

        summary_bar = (
            f'<table cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td style="padding:4px 14px 4px 0;">'
            f'{_badge(all_c, "#f47067", "#3a1515")}'
            f'<span style="color:{S};font-size:11px;margin-left:5px;">CRITICAL</span></td>'
            f'<td style="padding:4px 14px;">'
            f'{_badge(all_w, "#e3b341", "#3a2c0e")}'
            f'<span style="color:{S};font-size:11px;margin-left:5px;">WARNING</span></td>'
            f'<td style="padding:4px 0 4px 14px;">'
            f'{_badge(all_i, "#6cb6ff", "#0f2040")}'
            f'<span style="color:{S};font-size:11px;margin-left:5px;">INFO</span></td>'
            f'</tr></table>'
        )

        issue_sections = (
            _section("CRITICAL", criticals, "CRITICAL") +
            _section("WARNING", warnings, "WARNING") +
            _section("INFO", infos, "INFO")
        )

        if not self.issues:
            issue_sections = (
                f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                f'style="background:#0f2018;border:1px solid #2a5c3a;border-radius:6px;'
                f'margin-bottom:12px;border-collapse:collapse;">'
                f'<tr><td style="padding:16px;color:#3fb950;font-size:14px;font-weight:700;">'
                f'✓ No issues found — account looks healthy.</td></tr>'
                f'</table>'
            )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>LNM GAds Report</title>
</head>
<body style="margin:0;padding:0;background:#0d1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#0d1117;">
<tr><td align="center" style="padding:24px 16px;">
<table width="620" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;width:100%;">

  <!-- Header -->
  <tr><td style="background:#161b22;border:1px solid #30363d;border-radius:8px 8px 0 0;padding:22px 24px;">
    <div style="font-size:10px;font-weight:700;letter-spacing:0.12em;color:{M};margin-bottom:6px;text-transform:uppercase;">LeadsNearMe · GAds Optimization</div>
    <div style="font-size:22px;font-weight:700;color:{T};line-height:1.2;">{client_name} {mode_pill}</div>
    <div style="font-size:12px;color:{M};margin-top:6px;">CID {gads_cid} · {date_str}</div>
  </td></tr>

  <!-- Summary bar -->
  <tr><td style="background:#161b22;border-left:1px solid #30363d;border-right:1px solid #30363d;border-bottom:1px solid #21262d;padding:10px 24px;">
    {summary_bar}
  </td></tr>

  <!-- Body -->
  <tr><td style="background:#0d1117;border:1px solid #30363d;border-top:none;border-radius:0 0 8px 8px;padding:20px 24px;">
    {csm_section}{kpi_section}{kw_section}{issue_sections}
    <table width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr><td style="padding-top:20px;border-top:1px solid #21262d;text-align:center;">
        <span style="font-size:11px;color:{D};">LeadsNearMe GAds Automation</span>
      </td></tr>
    </table>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>"""

    def send_report_email(self, gads_cid: str, dry_run: bool = False, location_id: Optional[str] = None) -> None:
        smtp_user = os.environ.get("SMTP_USER")
        smtp_pass = os.environ.get("SMTP_PASS")
        if not smtp_user or not smtp_pass:
            print("  [email] SMTP_USER/SMTP_PASS not set — skipping email.")
            return

        smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        to_addr   = os.environ.get("REPORT_EMAIL_TO", "achiu@leadsnearme.com")

        # Append pod-specific recipient if configured
        pod_emails_raw = os.environ.get("POD_EMAILS", "{}")
        try:
            pod_emails = json.loads(pod_emails_raw)
        except Exception:
            pod_emails = {}


        loc = self.db.get_location_by_cid(gads_cid)
        client_name = loc["name"] if loc and loc.get("name") else gads_cid

        if loc and loc.get("pod_id") and pod_emails and self.db.enabled:
            try:
                pod_res = self.db.client.table("pods").select("name").eq("id", loc["pod_id"]).limit(1).execute()
                pod_name = pod_res.data[0]["name"] if pod_res.data else None
                if pod_name and pod_name in pod_emails:
                    pod_email = pod_emails[pod_name]
                    if pod_email not in to_addr:
                        to_addr = f"{to_addr},{pod_email}"
            except Exception as e:
                print(f"  [email] Could not look up pod email: {e}")

        criticals = sum(1 for i in self.issues if i["severity"] == "CRITICAL")
        warnings  = sum(1 for i in self.issues if i["severity"] == "WARNING")
        date_str  = datetime.now().strftime("%b %d")
        mode_tag  = " [DRY]" if dry_run else ""
        subject   = (
            f"[LNM Optimization{mode_tag}] {client_name} — "
            f"{criticals}C {warnings}W — {date_str}"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = smtp_user
        msg["To"]      = to_addr
        msg.attach(MIMEText(self._build_email_body(client_name, gads_cid, dry_run), "plain"))
        msg.attach(MIMEText(self._build_email_html(client_name, gads_cid, dry_run), "html"))

        try:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, [to_addr], msg.as_string())
            print(f"  [email] Report sent to {to_addr}")
        except Exception as e:
            print(f"  [email] Failed to send: {e}")

    def generate_report(self, filename_prefix="audit_report", dry_run: bool = False,
                        location_id: Optional[str] = None, gads_cid: Optional[str] = None):
        """Save logged issues to CSV, sync with PostgreSQL, and email report."""
        self.db.init_tables()
        if not self.issues:
            print("No issues found.")
            self.db.save_issues(
                [{"customer_id": gads_cid or "unknown", "category": "info", "severity": "INFO",
                  "message": "No issues found — account looks healthy.", "details": ""}],
                is_dry_run=dry_run, location_id=location_id,
            )
            if gads_cid and not dry_run:
                self.send_report_email(gads_cid, dry_run=dry_run, location_id=location_id)
            return None

        self.db.save_issues(self.issues, is_dry_run=dry_run, location_id=location_id)

        if gads_cid and not dry_run:
            self.send_report_email(gads_cid, dry_run=dry_run, location_id=location_id)

        # Local CSV fallback
        df = pd.DataFrame(self.issues)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"{filename_prefix}_{timestamp}.csv"
        filepath = os.path.join(self.output_dir, filename)
        df.to_csv(filepath, index=False)
        print(f"Report generated: {filepath}")
        return filepath
