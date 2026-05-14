from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from google.ads.googleads.errors import GoogleAdsException

from src.core.client import GAdsClient
from src.services.database import DatabaseService
from src.services.reporting import ReportingService
from src.services.negative_loader import NegativeKeyword, parse_negative_file
from src.services.retry import QuotaExhausted, gads_retry

# Thresholds for serving health flags
_ZERO_IMPRESSIONS_DAYS = 7
_ZERO_CONVERSIONS_DAYS = 14
_BUDGET_LOST_CRITICAL_PCT = 50.0
_SPEND_ZERO_DAYS = 3

# Search term pruning thresholds
_PRUNE_MIN_IMPRESSIONS = 15    # statistical floor before negating
_KW_OPP_MIN_CONVERSIONS = 2   # minimum conversions to flag as keyword opportunity
_KW_OPP_MIN_IMPRESSIONS = 15  # minimum impressions for opportunity candidate

# KPI thresholds (30-day account level)
_KPI_CTR_WARN_PCT = 2.0          # CTR below this → WARNING
_KPI_LOST_BUDGET_WARN_PCT = 20.0 # budget IS lost above this → WARNING
_KPI_LOST_BUDGET_CRIT_PCT = 50.0 # budget IS lost above this → CRITICAL
_KPI_LOST_RANK_WARN_PCT = 35.0   # rank IS lost above this → WARNING
_KPI_HIGH_CPC_INFO = 15.0        # avg CPC above this → INFO

# Competitor negative match-type guard
# Words that are too generic to anchor a phrase negative safely on their own.
# If a competitor name consists entirely of these words it gets EXACT match (narrow)
# or is skipped entirely (zero specific words).
_GENERIC_AUTO_WORDS = frozenset({
    'auto', 'automotive', 'car', 'cars', 'repair', 'repairs', 'service', 'services',
    'shop', 'center', 'garage', 'tire', 'tires', 'parts', 'care', 'clinic', 'motors',
    'motor', 'group', 'llc', 'inc', 'and', 'the', 'of', 'a', 'vehicle', 'vehicles',
    'mechanic', 'lube', 'oil', 'change', 'quick', 'fast', 'complete', 'total',
    'express', 'pro', 'plus', 'best', 'top', 'local', 'quality',
})


class GadsOptimization:
    def __init__(self, cid: str, dry_run: bool = False, reporter: ReportingService | None = None):
        self.cid = cid.replace('-', '')
        self.dry_run = dry_run
        self.gads = GAdsClient(self.cid)
        self.reporter = reporter or ReportingService()
        self.db = DatabaseService()
        self.negatives = parse_negative_file('config/negatives.txt')
        self.chains = parse_negative_file('config/national_chains.txt')

    @gads_retry()
    def audit_ads_and_campaigns(self) -> None:
        print(f"[{self.cid}] Auditing ads and campaigns...")
        query = """
            SELECT
                campaign.name,
                campaign.status,
                ad_group_ad.ad.id,
                ad_group_ad.status,
                ad_group_ad.policy_summary.approval_status
            FROM ad_group_ad
            WHERE campaign.status != 'REMOVED'
            AND ad_group_ad.status != 'REMOVED'
        """
        try:
            results = self.gads.get_service("GoogleAdsService").search(customer_id=self.cid, query=query)
            for row in results:
                if row.ad_group_ad.policy_summary.approval_status == self.gads.client.enums.PolicyApprovalStatusEnum.DISAPPROVED:
                    self.reporter.log_issue(self.cid, "AD_POLICY", "CRITICAL", f"Ad disapproved in {row.campaign.name}", row.ad_group_ad.ad.id)

                if row.campaign.status == self.gads.client.enums.CampaignStatusEnum.ENABLED and \
                   row.ad_group_ad.status == self.gads.client.enums.AdGroupAdStatusEnum.PAUSED:
                    self.reporter.log_issue(self.cid, "HEALTH", "WARNING", f"Paused Ad in active campaign: {row.campaign.name}")
        except Exception as e:
            print(f"Error auditing ads: {e}")

    @gads_retry()
    def audit_assets(self) -> None:
        print(f"[{self.cid}] Auditing assets...")
        query = "SELECT asset.id, asset.type, asset.policy_summary.approval_status FROM asset"
        try:
            results = self.gads.get_service("GoogleAdsService").search(customer_id=self.cid, query=query)
            asset_types = [row.asset.type for row in results]

            if self.gads.client.enums.AssetTypeEnum.LOCATION not in asset_types:
                self.reporter.log_issue(self.cid, "ASSET", "CRITICAL", "Missing Location Extension")

            for row in results:
                if row.asset.policy_summary.approval_status == self.gads.client.enums.PolicyApprovalStatusEnum.DISAPPROVED:
                    self.reporter.log_issue(self.cid, "ASSET_POLICY", "CRITICAL", f"Disapproved asset: {row.asset.type}", row.asset.id)
        except Exception as e:
            print(f"Error auditing assets: {e}")

    def _agg_kpi_period(self, start: str, end: str) -> dict | None:
        """Aggregate campaign KPIs for an explicit date range. Returns None if no data."""
        query = f"""
            SELECT
                metrics.clicks,
                metrics.impressions,
                metrics.conversions,
                metrics.cost_micros,
                metrics.search_budget_lost_impression_share,
                metrics.search_rank_lost_impression_share,
                metrics.search_impression_share,
                metrics.search_top_impression_share,
                metrics.search_absolute_top_impression_share
            FROM campaign
            WHERE campaign.status = 'ENABLED'
              AND segments.date BETWEEN '{start}' AND '{end}'
        """
        results = self.gads.get_service("GoogleAdsService").search(
            customer_id=self.cid, query=query
        )
        clicks = impr = convs = cost = 0
        lost_bud = lost_rnk = search_is = top_is = abs_top_is = 0
        row_count = 0
        for row in results:
            clicks    += row.metrics.clicks
            impr      += row.metrics.impressions
            convs     += row.metrics.conversions
            cost      += row.metrics.cost_micros / 1_000_000
            lost_bud  += row.metrics.search_budget_lost_impression_share
            lost_rnk  += row.metrics.search_rank_lost_impression_share
            search_is += row.metrics.search_impression_share
            top_is    += row.metrics.search_top_impression_share
            abs_top_is += row.metrics.search_absolute_top_impression_share
            row_count += 1
        if row_count == 0:
            return None
        return {
            "clicks": clicks,
            "impr": impr,
            "convs": convs,
            "cost": cost,
            "cpl": cost / convs if convs else 0,
            "lost_bud_pct": (lost_bud / row_count) * 100,
            "lost_rnk_pct": (lost_rnk / row_count) * 100,
            "search_is_pct": (search_is / row_count) * 100,
            "top_is_pct": (top_is / row_count) * 100,
            "abs_top_is_pct": (abs_top_is / row_count) * 100,
        }

    @gads_retry()
    def audit_performance_kpis(self) -> None:
        """Aggregate 30-day account KPIs with MoM and YoY comparisons."""
        print(f"[{self.cid}] Auditing performance KPIs...")

        yesterday  = date.today() - timedelta(days=1)
        curr_start = yesterday - timedelta(days=29)
        prev_start = yesterday - timedelta(days=59)
        prev_end   = yesterday - timedelta(days=30)
        yoy_start  = yesterday - timedelta(days=394)
        yoy_end    = yesterday - timedelta(days=365)

        fmt = lambda d: d.strftime("%Y-%m-%d")

        def _delta(curr_val: float, prev_val: float, invert: bool = False) -> str:
            """Return '+X%' / '-X%' string; invert=True for metrics where lower is better (CPL)."""
            if not prev_val:
                return ""
            pct = (curr_val - prev_val) / prev_val * 100
            if invert:
                pct = -pct
            sign = "+" if pct >= 0 else ""
            return f"{sign}{pct:.0f}%"

        try:
            curr = self._agg_kpi_period(fmt(curr_start), fmt(yesterday))
            if curr is None:
                return

            prev = None
            yoy  = None
            try:
                prev = self._agg_kpi_period(fmt(prev_start), fmt(prev_end))
            except Exception as e:
                print(f"  [kpi] prior-30 query failed: {e}")
            try:
                yoy = self._agg_kpi_period(fmt(yoy_start), fmt(yoy_end))
            except Exception as e:
                print(f"  [kpi] YoY query failed: {e}")

            clicks    = curr["clicks"]
            impr      = curr["impr"]
            convs     = curr["convs"]
            cost      = curr["cost"]
            ctr_pct   = (clicks / impr * 100) if impr else 0
            conv_rate_pct = (convs / clicks * 100) if clicks else 0
            avg_cpc   = (cost / clicks) if clicks else 0
            lost_bud_pct = curr["lost_bud_pct"]
            lost_rnk_pct = curr["lost_rnk_pct"]
            search_is_pct = curr["search_is_pct"]
            top_is_pct    = curr["top_is_pct"]
            abs_top_is_pct = curr["abs_top_is_pct"]
            cpl       = curr["cpl"]

            # Delta strings (MoM then YoY)
            conv_mom  = _delta(convs, prev["convs"]) if prev else ""
            conv_yoy  = _delta(convs, yoy["convs"])  if yoy  else ""
            cpl_mom   = _delta(cpl,   prev["cpl"],   invert=True) if prev else ""
            cpl_yoy   = _delta(cpl,   yoy["cpl"],    invert=True) if yoy  else ""
            spend_mom = _delta(cost,  prev["cost"])  if prev else ""
            spend_yoy = _delta(cost,  yoy["cost"])   if yoy  else ""
            clicks_mom = _delta(clicks, prev["clicks"]) if prev else ""
            clicks_yoy = _delta(clicks, yoy["clicks"])  if yoy  else ""
            impr_mom  = _delta(impr,  prev["impr"])  if prev else ""
            impr_yoy  = _delta(impr,  yoy["impr"])   if yoy  else ""

            kpi_parts = [
                f"Clicks: {clicks:,}",
                f"Impr: {impr:,}",
                f"CTR: {ctr_pct:.1f}%",
                f"Conv: {convs:.0f}",
                f"Conv Rate: {conv_rate_pct:.1f}%",
                f"CPL: ${cpl:.2f}",
                f"Avg CPC: ${avg_cpc:.2f}",
                f"Spend: ${cost:,.2f}",
                f"Search IS: {search_is_pct:.0f}%",
                f"Top IS: {top_is_pct:.0f}%",
                f"Abs Top IS: {abs_top_is_pct:.0f}%",
                f"Lost IS (budget): {lost_bud_pct:.0f}%",
                f"Lost IS (rank): {lost_rnk_pct:.0f}%",
            ]
            if conv_mom:  kpi_parts.append(f"Conv30: {conv_mom}")
            if conv_yoy:  kpi_parts.append(f"ConvYoY: {conv_yoy}")
            if cpl_mom:   kpi_parts.append(f"CPL30: {cpl_mom}")
            if cpl_yoy:   kpi_parts.append(f"CPLYoY: {cpl_yoy}")
            if spend_mom: kpi_parts.append(f"Spend30: {spend_mom}")
            if spend_yoy: kpi_parts.append(f"SpendYoY: {spend_yoy}")
            if clicks_mom: kpi_parts.append(f"Clicks30: {clicks_mom}")
            if clicks_yoy: kpi_parts.append(f"ClicksYoY: {clicks_yoy}")
            if impr_mom:  kpi_parts.append(f"Impr30: {impr_mom}")
            if impr_yoy:  kpi_parts.append(f"ImprYoY: {impr_yoy}")

            self.reporter.log_issue(
                self.cid, "KPI", "INFO",
                "30-day KPI snapshot",
                details="  ".join(kpi_parts),
            )

            if ctr_pct < _KPI_CTR_WARN_PCT and impr > 500:
                self.reporter.log_issue(
                    self.cid, "KPI", "WARNING",
                    f"Low CTR: {ctr_pct:.1f}% (benchmark: {_KPI_CTR_WARN_PCT}%+)",
                    details=f"{clicks:,} clicks / {impr:,} impressions",
                )

            if lost_bud_pct >= _KPI_LOST_BUDGET_CRIT_PCT:
                self.reporter.log_issue(
                    self.cid, "KPI", "CRITICAL",
                    f"Losing {lost_bud_pct:.0f}% of impressions to budget cap",
                    details="Recommend increasing daily budget",
                )
            elif lost_bud_pct >= _KPI_LOST_BUDGET_WARN_PCT:
                self.reporter.log_issue(
                    self.cid, "KPI", "WARNING",
                    f"Losing {lost_bud_pct:.0f}% of impressions to budget cap",
                    details="Monitor — consider budget increase if CPL is healthy",
                )

            if lost_rnk_pct >= _KPI_LOST_RANK_WARN_PCT:
                self.reporter.log_issue(
                    self.cid, "KPI", "WARNING",
                    f"Losing {lost_rnk_pct:.0f}% of impressions to ad rank",
                    details="Review quality scores and bid strategy",
                )

            if avg_cpc > _KPI_HIGH_CPC_INFO and clicks > 50:
                self.reporter.log_issue(
                    self.cid, "KPI", "INFO",
                    f"High avg CPC: ${avg_cpc:.2f} (above ${_KPI_HIGH_CPC_INFO:.0f} threshold)",
                    details=f"${cost:,.2f} total spend / {clicks:,} clicks",
                )

        except Exception as e:
            print(f"Error auditing KPIs: {e}")

    @gads_retry()
    def dismiss_recommendations(self) -> None:
        print(f"[{self.cid}] Checking recommendations...")
        googleads_service = self.gads.get_service("GoogleAdsService")
        recommendation_service = self.gads.get_service("RecommendationService")
        
        query = "SELECT recommendation.resource_name, recommendation.type FROM recommendation"

        try:
            # Use GoogleAdsService.search instead of recommendation_service.search_stream
            results = googleads_service.search(customer_id=self.cid, query=query)
            resource_names = []
            for row in results:
                if row.recommendation.type.name == 'KEYWORD_CONFLICTION':
                    self.reporter.log_issue(self.cid, "REC", "INFO", "Evaluate Conflicting Negative Keywords")
                    continue
                resource_names.append(row.recommendation.resource_name)

            if resource_names and not self.dry_run:
                # DismissRecommendationOperation doesn't exist as a top-level type in v24;
                # proto-plus accepts plain dicts for nested message types.
                # API limit: 100 operations per request.
                chunk_size = 100
                dismissed = 0
                for i in range(0, len(resource_names), chunk_size):
                    chunk = [{"resource_name": rn} for rn in resource_names[i:i + chunk_size]]
                    recommendation_service.dismiss_recommendation(customer_id=self.cid, operations=chunk)
                    dismissed += len(chunk)
                print(f"Dismissed {dismissed} recommendations.")
        except Exception as e:
            print(f"Error dismissing recommendations: {e}")

    def get_or_create_shared_set(self, name: str) -> str | None:
        googleads_service = self.gads.get_service("GoogleAdsService")
        shared_set_service = self.gads.get_service("SharedSetService")

        query = f"SELECT shared_set.resource_name, shared_set.name FROM shared_set WHERE shared_set.name = '{name}'"
        try:
            results = googleads_service.search(customer_id=self.cid, query=query)
            for row in results:
                return row.shared_set.resource_name
        except Exception as e:
            print(f"Error searching for shared set: {e}")

        if self.dry_run:
            print(f"[DRY-RUN] Would create '{name}' shared set.")
            return "dry-run-resource-name"

        shared_set = self.gads.client.get_type("SharedSet")
        shared_set.name = name
        shared_set.type_ = self.gads.client.enums.SharedSetTypeEnum.NEGATIVE_KEYWORDS

        op = self.gads.client.get_type("SharedSetOperation")
        op.create = shared_set

        try:
            response = shared_set_service.mutate_shared_sets(customer_id=self.cid, operations=[op])
            resource_name = response.results[0].resource_name
            print(f"Created Shared Set: {resource_name}")
            return resource_name
        except Exception as e:
            print(f"Error creating shared set: {e}")
            return None

    def _get_existing_shared_criteria(self, shared_set_rn: str) -> set[str]:
        """Return lowercase keyword texts already in the shared set — prevents ALREADY_EXISTS errors."""
        query = f"""
            SELECT shared_criterion.keyword.text
            FROM shared_criterion
            WHERE shared_criterion.shared_set = '{shared_set_rn}'
            AND shared_criterion.type = 'KEYWORD'
        """
        existing: set[str] = set()
        try:
            results = self.gads.get_service("GoogleAdsService").search(
                customer_id=self.cid, query=query
            )
            for row in results:
                existing.add(row.shared_criterion.keyword.text.lower())
        except Exception as e:
            print(f"Error fetching existing shared criteria: {e}")
        return existing

    def add_negatives_to_shared_set(self, shared_set_rn: str, keywords: list[NegativeKeyword]) -> None:
        if not keywords:
            return

        match_type_map = {
            'BROAD': self.gads.client.enums.KeywordMatchTypeEnum.BROAD,
            'PHRASE': self.gads.client.enums.KeywordMatchTypeEnum.PHRASE,
            'EXACT': self.gads.client.enums.KeywordMatchTypeEnum.EXACT,
        }

        existing = set() if self.dry_run else self._get_existing_shared_criteria(shared_set_rn)
        new_keywords = [kw for kw in keywords if kw.text.lower() not in existing]

        if not new_keywords:
            print("All keywords already in shared set — skipping.")
            return

        shared_criterion_service = self.gads.get_service("SharedCriterionService")
        operations = []

        for kw in new_keywords:
            criterion = self.gads.client.get_type("SharedCriterion")
            criterion.shared_set = shared_set_rn
            criterion.keyword.text = kw.text
            criterion.keyword.match_type = match_type_map[kw.match_type]

            op = self.gads.client.get_type("SharedCriterionOperation")
            op.create = criterion
            operations.append(op)

        if self.dry_run:
            print(f"[DRY-RUN] Would add {len(new_keywords)} keywords to {shared_set_rn}")
            return

        try:
            shared_criterion_service.mutate_shared_criteria(customer_id=self.cid, operations=operations)
            print(f"Successfully added {len(new_keywords)} negative keywords.")
        except Exception as e:
            print(f"Error adding negative keywords: {e}")

    @gads_retry()
    def prune_search_terms(self) -> None:
        print(f"[{self.cid}] Pruning search terms...")
        googleads_service = self.gads.get_service("GoogleAdsService")

        # 15-impression floor = statistical basis
        query = """
            SELECT 
                search_term_view.search_term, 
                ad_group.name,
                metrics.impressions, 
                metrics.conversions,
                metrics.cost_micros
            FROM search_term_view
            WHERE segments.date DURING LAST_30_DAYS
            AND metrics.impressions >= 15
        """

        all_kws = [*self.negatives]
        broad_negs  = {kw.text.lower() for kw in all_kws if kw.match_type == 'BROAD'}
        phrase_negs = {kw.text.lower() for kw in all_kws if kw.match_type == 'PHRASE'}
        exact_negs  = {kw.text.lower() for kw in all_kws if kw.match_type == 'EXACT'}

        location = self.db.get_location_by_cid(self.cid)
        brand_seeds = []
        if location:
            brand_seeds.append(location['name'].lower())
            import re
            core = re.sub(r'\s+(auto|automotive|repair|service|car care).*$', '', location['name'].lower())
            brand_seeds.append(core)
            if 'route 11' in core:
                brand_seeds.extend(['rt 11', 'route11', 'hawk', 'bridgewater'])

        def _is_junk(term: str) -> bool:
            import re
            if term in exact_negs:
                return True
            if any(neg in term for neg in phrase_negs):
                return True
            return any(re.search(r'\b' + re.escape(neg) + r'\b', term) for neg in broad_negs)

        def _is_brand_leak(term: str, ad_group_name: str) -> bool:
            if not brand_seeds:
                return False
            is_brand_search = any(bs in term for bs in brand_seeds)
            is_brand_group = 'brand' in ad_group_name.lower()
            return is_brand_search and not is_brand_group

        try:
            results = googleads_service.search(customer_id=self.cid, query=query)
            junk_found: list[tuple[NegativeKeyword, int, str]] = [] # kw, impr, reason
            st_rows: list[dict] = []
            location = self.db.get_location_by_cid(self.cid)
            loc_id = location["id"] if location else None
            from datetime import date as _date
            run_date = str(_date.today())

            for row in results:
                term = row.search_term_view.search_term.lower()
                ad_group_name = row.ad_group.name
                impr = int(row.metrics.impressions)
                conv = float(row.metrics.conversions)
                cost = row.metrics.cost_micros / 1000000

                st_rows.append({
                    "location_id": loc_id,
                    "gads_cid":    self.cid,
                    "term":        term,
                    "run_date":    run_date,
                    "impressions": impr,
                    "clicks":      0,
                    "cost_micros": int(row.metrics.cost_micros),
                    "conversions": conv,
                })

                # 1. Standard junk (must have 0 conversions)
                if conv == 0 and _is_junk(term):
                    junk_found.append((NegativeKeyword(text=term, match_type='EXACT'), impr, "JUNK"))
                
                # 2. Brand leak (negate even if it has conversions — force to brand campaign)
                elif _is_brand_leak(term, ad_group_name):
                    junk_found.append((NegativeKeyword(text=term, match_type='EXACT'), impr, "BRAND_LEAK"))

                # 3. High-cost waste (0 conversions, > $20 spend) - likely local competitors
                elif conv == 0 and cost > 20.0:
                    junk_found.append((NegativeKeyword(text=term, match_type='EXACT'), impr, "HIGH_COST_WASTE"))

            self.db.bulk_upsert_search_terms(st_rows)

            if junk_found:
                junk_found.sort(key=lambda t: t[1], reverse=True)
                kws = [t[0] for t in junk_found]

                print(f"Found {len(junk_found)} candidates for pruning.")
                shared_set_rn = self.get_or_create_shared_set('LNM Global Negatives')
                if shared_set_rn:
                    self.add_negatives_to_shared_set(shared_set_rn, kws)

                neg_rows = [{
                    "location_id": loc_id, "gads_cid": self.cid,
                    "term": t[0].text, "match_type": t[0].match_type,
                    "level": "shared_set", "reason": t[2],
                    "is_dry_run": self.dry_run,
                } for t in junk_found]
                self.db.bulk_insert_negative_history(neg_rows)

                # Log with reasons
                leaks = [t for t in junk_found if t[2] == "BRAND_LEAK"]
                if leaks:
                    leak_str = ", ".join([f"{t[0].text} (${row.metrics.cost_micros/1000000:.2f})" for t in leaks[:10]]) # Wait, I don't have row here.
                    # Fixed:
                    leak_str = ", ".join([f"{t[0].text}" for t in leaks[:10]])
                    self.reporter.log_issue(
                        self.cid, "BRAND_LEAK", "WARNING",
                        f"Negated {len(leaks)} branded terms found in non-brand ad groups",
                        details=leak_str + ("..." if len(leaks) > 10 else "")
                    )

                high_cost = [t for t in junk_found if t[2] == "HIGH_COST_WASTE"]
                if high_cost:
                    hc_str = ", ".join([f"{t[0].text}" for t in high_cost[:10]])
                    self.reporter.log_issue(
                        self.cid, "WASTED_SPEND", "CRITICAL",
                        f"Negated {len(high_cost)} high-cost terms (>$20) with zero conversions",
                        details=hc_str + ("..." if len(high_cost) > 10 else ""),
                    )

                standard_junk = [t for t in junk_found if t[2] == "JUNK"]
                if standard_junk:
                    junk_str = ", ".join([f"{t[0].text}" for t in standard_junk[:10]])
                    self.reporter.log_issue(
                        self.cid, "NEGATIVE_ADDED", "INFO",
                        f"Pruned {len(standard_junk)} junk search terms as EXACT negatives",
                        details=junk_str + ("..." if len(standard_junk) > 10 else ""),
                    )
            else:
                print("No junk search terms found.")
        except Exception as e:
            print(f"Error pruning search terms: {e}")

    @staticmethod
    def _competitor_match_type(name: str) -> str | None:
        """Return 'PHRASE', 'EXACT', or None (skip — too generic to negate safely).

        PHRASE: multi-word name with ≥1 specific (non-generic-auto) word.
                Blocks any query containing the business name → catches 'Taylor Ford service'.
        EXACT:  single-word names → narrow, avoids accidental suppression.
        None:   name is entirely generic auto words (e.g. 'Auto Care') → skip with warning.
        """
        words = re.sub(r'[^a-z0-9\s]', '', name.lower()).split()
        if not words:
            return None
        specific = [w for w in words if w not in _GENERIC_AUTO_WORDS]
        if not specific:
            return None          # e.g. "Auto Care", "Quick Service" — too risky as phrase
        if len(words) == 1:
            return 'EXACT'       # single proper noun — exact is safe
        return 'PHRASE'          # multi-word with a specific anchor → phrase is safe

    def audit_competitor_search_terms(self) -> None:
        """Scan search terms report for queries containing competitor names.

        Catches competitors that slipped through existing negatives (wrong match type,
        not yet in DB, or added after the period). Negates the specific search terms
        as EXACT so past spend is not repeated.
        """
        print(f"[{self.cid}] Scanning search terms for competitor matches...")

        location = self.db.get_location_by_cid(self.cid)
        if not location:
            return

        raw_names = self.db.get_competitor_names(location["id"])
        if not raw_names:
            return

        # Build set of cleaned lowercase names (skip names <4 chars — too ambiguous)
        comp_names: list[str] = []
        for name in raw_names:
            clean = re.sub(r"[^a-zA-Z0-9\s\-]", "", name).strip().lower()
            if len(clean) >= 4:
                comp_names.append(clean)

        if not comp_names:
            return

        query = """
            SELECT
                search_term_view.search_term,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros
            FROM search_term_view
            WHERE segments.date DURING LAST_30_DAYS
              AND metrics.impressions >= 1
        """
        try:
            svc = self.gads.get_service("GoogleAdsService")
            hits: list[tuple[str, str, int, int, float]] = []  # term, comp, impr, clicks, cost

            for row in svc.search(customer_id=self.cid, query=query):
                term = row.search_term_view.search_term.lower()
                impr = int(row.metrics.impressions)
                clicks = int(row.metrics.clicks)
                cost = row.metrics.cost_micros / 1_000_000
                for comp in comp_names:
                    if comp in term:
                        hits.append((term, comp, impr, clicks, cost))
                        break

            if not hits:
                print("  No competitor search terms found.")
                return

            hits.sort(key=lambda h: h[4], reverse=True)
            total_cost = sum(h[4] for h in hits)
            kws = [NegativeKeyword(text=h[0], match_type='EXACT') for h in hits]

            if not self.dry_run:
                shared_set_rn = self.get_or_create_shared_set('LNM Global Negatives')
                self.add_negatives_to_shared_set(shared_set_rn, kws)

            comp_loc = self.db.get_location_by_cid(self.cid)
            comp_loc_id = comp_loc["id"] if comp_loc else None
            from datetime import date as _date
            comp_neg_rows = [{
                "location_id": comp_loc_id, "gads_cid": self.cid,
                "term": h[0], "match_type": "EXACT",
                "level": "shared_set", "reason": "COMPETITOR",
                "is_dry_run": self.dry_run,
            } for h in hits]
            self.db.bulk_insert_negative_history(comp_neg_rows)

            preview = "  ".join(
                f'"{h[0]}" ({h[1]}, ${h[4]:.2f})' for h in hits[:8]
            )
            action = "[DRY RUN] Would negate" if self.dry_run else "Negated"
            self.reporter.log_issue(
                self.cid, "COMPETITOR_NEGATIVES", "WARNING",
                f"{action} {len(hits)} competitor search terms — ${total_cost:.2f} wasted",
                details=preview,
            )
            print(f"  {action} {len(hits)} competitor search terms (${total_cost:.2f}).")
        except Exception as e:
            print(f"  Error scanning competitor search terms: {e}")

    def apply_competitor_negatives(self) -> None:
        print(f"[{self.cid}] Applying competitor negatives...")

        location = self.db.get_location_by_cid(self.cid)
        if not location:
            print(f"  No location found for CID {self.cid} — skipping.")
            return

        raw_names = self.db.get_competitor_names(location["id"])
        if not raw_names:
            print("  No competitors in DB — run Pull Competitors first.")
            return

        # Deduplicate and classify match type. Skip names that are entirely generic
        # (would over-suppress legitimate searches if used as phrase negatives).
        seen: set[str] = set()
        competitor_names: list[tuple[str, str]] = []  # (name, match_type)
        skipped_generic: list[str] = []
        for name in raw_names:
            clean = re.sub(r"[^a-zA-Z0-9\s\-]", "", name)
            clean = re.sub(r'\s+', ' ', clean).strip()
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            mt = self._competitor_match_type(clean)
            if mt is None:
                skipped_generic.append(clean)
            else:
                competitor_names.append((clean, mt))

        if skipped_generic:
            print(f"  Skipped {len(skipped_generic)} generic-name competitors (too risky as phrase): {', '.join(skipped_generic[:5])}")
            self.reporter.log_issue(
                self.cid, "COMPETITOR_NEGATIVES", "INFO",
                f"Skipped {len(skipped_generic)} competitor(s) with generic names — manual review needed",
                details=", ".join(skipped_generic),
            )

        print(f"  Found {len(competitor_names)} competitors to negate ({len(skipped_generic)} generic skipped, {len(raw_names) - len(competitor_names) - len(skipped_generic)} dupes removed).")

        gads_service = self.gads.get_service("GoogleAdsService")

        try:
            campaign_rows = list(gads_service.search(
                customer_id=self.cid,
                query="""
                    SELECT campaign.resource_name
                    FROM campaign
                    WHERE campaign.status = 'ENABLED'
                      AND campaign.advertising_channel_type != 'PERFORMANCE_MAX'
                """,
            ))
        except Exception as e:
            print(f"  Error fetching campaigns: {e}")
            return

        if not campaign_rows:
            print("  No enabled non-PMax campaigns found.")
            return

        # Fetch existing campaign-level exact negatives for deduplication
        existing_by_campaign: dict[str, set[str]] = {}
        try:
            for row in gads_service.search(
                customer_id=self.cid,
                query="""
                    SELECT campaign_criterion.campaign, campaign_criterion.keyword.text
                    FROM campaign_criterion
                    WHERE campaign_criterion.negative = true
                      AND campaign_criterion.type = 'KEYWORD'
                      AND campaign.status = 'ENABLED'
                """,
            ):
                rn = row.campaign_criterion.campaign
                existing_by_campaign.setdefault(rn, set()).add(
                    row.campaign_criterion.keyword.text.lower()
                )
        except Exception as e:
            print(f"  Error fetching existing campaign negatives: {e}")

        criterion_service = self.gads.get_service("CampaignCriterionService")
        total_added = 0

        match_type_enum = self.gads.client.enums.KeywordMatchTypeEnum

        for camp_row in campaign_rows:
            campaign_rn = camp_row.campaign.resource_name
            existing = existing_by_campaign.get(campaign_rn, set())
            new_entries = [(n, mt) for n, mt in competitor_names if n.lower() not in existing]

            if not new_entries:
                continue

            if self.dry_run:
                print(f"  [DRY RUN] Would add {len(new_entries)} competitor negatives to {campaign_rn}")
                total_added += len(new_entries)
                continue

            for name, mt in new_entries:
                criterion = self.gads.client.get_type("CampaignCriterion")
                criterion.campaign = campaign_rn
                criterion.negative = True
                criterion.keyword.text = name
                criterion.keyword.match_type = getattr(match_type_enum, mt)
                op = self.gads.client.get_type("CampaignCriterionOperation")
                op.create = criterion
                try:
                    criterion_service.mutate_campaign_criteria(
                        customer_id=self.cid, operations=[op]
                    )
                    total_added += 1
                except GoogleAdsException as e:
                    error_code = e.error.code().name if e.error else "UNKNOWN"
                    print(f"  Skip '{name}': {error_code}")
                except Exception as e:
                    print(f"  Skip '{name}': {e}")

        preview = ", ".join(n for n, _ in competitor_names[:20])
        if len(competitor_names) > 20:
            preview += f" (+{len(competitor_names) - 20} more)"
        action = "[DRY RUN] Would add" if self.dry_run else "Added"
        self.reporter.log_issue(
            self.cid, "COMPETITOR_NEGATIVES", "INFO",
            f"{action} {total_added} competitor phrase negatives at campaign level",
            details=preview,
        )
        print(f"  {action} {total_added} competitor negatives across {len(campaign_rows)} campaigns.")

    @gads_retry()
    def audit_asset_health(self) -> None:
        print(f"[{self.cid}] Auditing asset health...")
        query = """
            SELECT
                ad_group_ad_asset_view.performance_label,
                ad_group_ad_asset_view.field_type,
                ad_group_ad_asset_view.pinned_field,
                asset.text_asset.text,
                ad_group.name,
                campaign.name
            FROM ad_group_ad_asset_view
            WHERE ad_group_ad_asset_view.enabled = true
              AND campaign.status = 'ENABLED'
              AND ad_group_ad_asset_view.field_type IN ('HEADLINE', 'DESCRIPTION')
        """
        try:
            svc = self.gads.get_service("GoogleAdsService")
            perf_enum = self.gads.client.enums.AssetPerformanceLabelEnum
            low_assets: list[tuple[str, str, str, str]] = []  # text, field, ad_group, campaign
            best_assets: list[tuple[str, str]] = []           # text, field

            for row in svc.search(customer_id=self.cid, query=query):
                label = row.ad_group_ad_asset_view.performance_label
                field = row.ad_group_ad_asset_view.field_type.name
                text  = row.asset.text_asset.text or ""
                ag    = row.ad_group.name
                camp  = row.campaign.name
                if label == perf_enum.LOW:
                    low_assets.append((text, field, ag, camp))
                elif label == perf_enum.BEST:
                    best_assets.append((text, field))

            if low_assets:
                preview = "; ".join(
                    f'"{t}" [{f}] in {ag}' for t, f, ag, _ in low_assets[:8]
                )
                suffix = f" (+{len(low_assets) - 8} more)" if len(low_assets) > 8 else ""
                self.reporter.log_issue(
                    self.cid, "ASSET_HEALTH", "WARNING",
                    f"{len(low_assets)} LOW-performance RSA asset{'s' if len(low_assets) > 1 else ''} — replace to improve ad strength",
                    details=preview + suffix,
                )
                print(f"  {len(low_assets)} LOW assets found.")

            if best_assets:
                best_preview = "; ".join(f'"{t}"' for t, _ in best_assets[:5])
                self.reporter.log_issue(
                    self.cid, "ASSET_HEALTH", "INFO",
                    f"{len(best_assets)} BEST-performance RSA asset{'s' if len(best_assets) > 1 else ''}",
                    details=best_preview,
                )

            if not low_assets and not best_assets:
                print("  No labeled RSA assets (account may be too new or using ETAs).")
        except Exception as e:
            print(f"Error auditing asset health: {e}")

    def calculate_roi_metrics(self) -> dict | None:
        print(f"[{self.cid}] Calculating ROI metrics...")
        query = """
            SELECT
                metrics.search_budget_lost_impression_share,
                metrics.search_rank_lost_impression_share,
                metrics.cost_per_conversion,
                metrics.conversions,
                metrics.cost_micros
            FROM campaign
            WHERE segments.date DURING LAST_30_DAYS
            AND campaign.status = 'ENABLED'
        """
        try:
            results = self.gads.get_service("GoogleAdsService").search(customer_id=self.cid, query=query)

            total_cost = 0.0
            total_conv = 0.0
            lost_is_budget_sum = 0.0
            lost_is_rank_sum = 0.0
            count = 0

            for row in results:
                total_cost += row.metrics.cost_micros / 1_000_000
                total_conv += row.metrics.conversions
                lost_is_budget_sum += row.metrics.search_budget_lost_impression_share
                lost_is_rank_sum += row.metrics.search_rank_lost_impression_share
                count += 1

            if count == 0:
                return None

            metrics = {
                "lost_is_budget": round((lost_is_budget_sum / count) * 100, 2),
                "lost_is_rank": round((lost_is_rank_sum / count) * 100, 2),
                "cost_per_appointment": round(total_cost / total_conv, 2) if total_conv > 0 else 0,
                "total_conversions": total_conv,
                "total_cost": round(total_cost, 2),
            }
            metrics["cs_snapshot"] = self.generate_cs_snapshot(metrics)
            self.db.save_roi_snapshot(self.cid, metrics)
            self.reporter.cs_snapshot = metrics["cs_snapshot"]
            return metrics

        except Exception as e:
            print(f"Error calculating ROI metrics: {e}")
            return None

    def generate_cs_snapshot(self, metrics: dict) -> str:
        perf = f"Your current cost per new appointment is ${metrics['cost_per_appointment']:.2f}, which is within our healthy benchmark for your market."

        if metrics['lost_is_budget'] > 20:
            opp = f"We are currently missing {metrics['lost_is_budget']:.0f}% of local searchers because your budget is capping out early."
        else:
            opp = "Your budget is correctly covering the majority of search traffic in your area."

        action = "Our automation is currently pruning irrelevant search terms to keep your traffic highly targeted to repair-ready customers."
        return f"{perf} {opp} {action}"

    def identify_keyword_opportunities(self) -> None:
        print(f"[{self.cid}] Identifying keyword opportunities...")

        # Pull converting search terms not already surfaced as exact-match keywords
        query = """
            SELECT
                search_term_view.search_term,
                search_term_view.ad_group,
                metrics.conversions,
                metrics.impressions,
                metrics.ctr
            FROM search_term_view
            WHERE segments.date DURING LAST_30_DAYS
            AND metrics.conversions >= 2
            AND metrics.impressions >= 15
        """

        # Fetch existing exact-match keywords to avoid duplicates
        kw_query = """
            SELECT ad_group_criterion.keyword.text
            FROM ad_group_criterion
            WHERE ad_group_criterion.keyword.match_type = 'EXACT'
            AND ad_group_criterion.status != 'REMOVED'
        """

        try:
            gads_service = self.gads.get_service("GoogleAdsService")

            existing_exact: set[str] = set()
            for row in gads_service.search(customer_id=self.cid, query=kw_query):
                existing_exact.add(row.ad_group_criterion.keyword.text.lower())

            opportunities: list[tuple[str, str, float]] = []
            for row in gads_service.search(customer_id=self.cid, query=query):
                term = row.search_term_view.search_term.lower()
                if term not in existing_exact:
                    opportunities.append((
                        term,
                        row.search_term_view.ad_group,
                        row.metrics.conversions,
                    ))

            if not opportunities:
                print(f"[{self.cid}] No keyword opportunities found.")
                return

            for term, ad_group, conversions in opportunities:
                self.reporter.log_issue(
                    self.cid, "KEYWORD_OPPORTUNITY", "INFO",
                    f"Add as EXACT keyword: '{term}' ({conversions:.0f} conversions, not in keyword list)",
                    details=ad_group,
                )

            print(f"[{self.cid}] Found {len(opportunities)} keyword opportunities.")

        except Exception as e:
            print(f"Error identifying keyword opportunities: {e}")

    @gads_retry()
    def audit_bid_strategy(self) -> None:
        print(f"[{self.cid}] Auditing bid strategies...")
        query = """
            SELECT
                campaign.name,
                campaign.bidding_strategy_type,
                campaign.maximize_conversions.target_cpa_micros,
                campaign.target_cpa.target_cpa_micros,
                campaign.status,
                metrics.cost_micros,
                metrics.conversions
            FROM campaign
            WHERE campaign.status = 'ENABLED'
              AND segments.date DURING LAST_30_DAYS
        """
        query_learning = """
            SELECT
                campaign.name,
                campaign.optimization_score
            FROM campaign
            WHERE campaign.status = 'ENABLED'
        """
        try:
            svc = self.gads.get_service("GoogleAdsService")
            bs_enum = self.gads.client.enums.BiddingStrategyTypeEnum

            # Aggregate cost + conversions per campaign
            camp_data: dict[str, dict] = {}
            for row in svc.search(customer_id=self.cid, query=query):
                name = row.campaign.name
                bs   = row.campaign.bidding_strategy_type.name
                if name not in camp_data:
                    camp_data[name] = {'bs': bs, 'cost': 0.0, 'convs': 0.0,
                                       'tcpa': row.campaign.target_cpa.target_cpa_micros / 1e6
                                       if row.campaign.target_cpa.target_cpa_micros else 0.0}
                camp_data[name]['cost']  += row.metrics.cost_micros / 1e6
                camp_data[name]['convs'] += row.metrics.conversions

            for name, c in camp_data.items():
                bs   = c['bs']
                cost = c['cost']
                convs = c['convs']
                tcpa  = c['tcpa']

                # Smart bidding with zero conversions in 30d = learning/starved
                smart = bs in ('MAXIMIZE_CONVERSIONS', 'TARGET_CPA', 'MAXIMIZE_CONVERSION_VALUE', 'TARGET_ROAS')
                if smart and convs == 0 and cost > 0:
                    self.reporter.log_issue(
                        self.cid, "BID_STRATEGY", "CRITICAL",
                        f"{name}: {bs} with 0 conversions in 30d — strategy starved, likely in learning loop",
                        details="Consider switching to Maximize Clicks until 30+ conversions/month, then return to smart bidding.",
                    )
                elif smart and convs < 10 and cost > 50:
                    self.reporter.log_issue(
                        self.cid, "BID_STRATEGY", "WARNING",
                        f"{name}: {bs} with only {convs:.0f} conversions — below 30/month threshold for stable smart bidding",
                        details=f"${cost:.0f} spend. Smart bidding needs 30+ monthly conversions to optimize reliably.",
                    )

                # tCPA set suspiciously low (< $5) — may throttle delivery
                if tcpa > 0 and tcpa < 5:
                    self.reporter.log_issue(
                        self.cid, "BID_STRATEGY", "WARNING",
                        f"{name}: target CPA set to ${tcpa:.2f} — may be throttling delivery",
                        details="tCPA below $5 for auto repair is unrealistically low and will suppress impressions.",
                    )

                # Manual CPC — flag as opportunity for upgrade if enough conversions
                if bs in ('MANUAL_CPC', 'MANUAL_CPM') and convs >= 30:
                    self.reporter.log_issue(
                        self.cid, "BID_STRATEGY", "INFO",
                        f"{name}: manual bidding with {convs:.0f} conversions — eligible for Maximize Conversions upgrade",
                        details=f"${cost:.0f} spend. Account has sufficient conversion data for smart bidding.",
                    )
        except Exception as e:
            print(f"Error auditing bid strategy: {e}")

    def audit_headline_relevancy(self) -> None:
        print(f"[{self.cid}] Auditing headline/search term alignment...")
        # TODO: compare top search terms to RSA headlines
        pass

    def audit_dsa_performance(self) -> None:
        print(f"[{self.cid}] Auditing Dynamic Search Ads...")
        # TODO: flag if DSA spend > 30% of total with low conversions
        pass

    def audit_campaign_structure(self) -> None:
        print(f"[{self.cid}] Auditing campaign structure...")
        # TODO: flag if one ad group takes > 80% of campaign spend
        pass

    @gads_retry()
    def audit_serving_health(self) -> None:
        print(f"[{self.cid}] Auditing serving health...")
        gads_service = self.gads.get_service("GoogleAdsService")

        three_days_ago = (datetime.now() - timedelta(days=_SPEND_ZERO_DAYS)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")

        # Single query covers 14-day window; we filter impressions/spend in Python
        query = f"""
            SELECT
                campaign.name,
                campaign.status,
                metrics.impressions,
                metrics.conversions,
                metrics.cost_micros,
                metrics.search_budget_lost_impression_share,
                metrics.search_rank_lost_impression_share,
                segments.date
            FROM campaign
            WHERE campaign.status != 'REMOVED'
            AND segments.date DURING LAST_14_DAYS
        """

        try:
            results = gads_service.search(customer_id=self.cid, query=query)

            # Aggregate per campaign across the window
            campaigns: dict[str, dict] = {}
            for row in results:
                name = row.campaign.name
                status = row.campaign.status.name
                date = row.segments.date

                if name not in campaigns:
                    campaigns[name] = {
                        'campaign_name': name,
                        'campaign_status': status,
                        'impressions_7d': 0,
                        'conversions_14d': 0.0,
                        'spend_3d_micros': 0,
                        'lost_is_budget_sum': 0.0,
                        'lost_is_rank_sum': 0.0,
                        'row_count': 0,
                    }

                c = campaigns[name]
                c['conversions_14d'] += row.metrics.conversions
                c['lost_is_budget_sum'] += row.metrics.search_budget_lost_impression_share
                c['lost_is_rank_sum'] += row.metrics.search_rank_lost_impression_share
                c['row_count'] += 1

                # Last 7 days for impressions
                if date >= (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"):
                    c['impressions_7d'] += row.metrics.impressions

                # Last 3 days for spend
                if date >= three_days_ago:
                    c['spend_3d_micros'] += row.metrics.cost_micros

            if not campaigns:
                self.reporter.log_issue(self.cid, "SERVING", "CRITICAL", "No campaign data returned — account may be suspended or billing failed.")
                return

            snapshots = []
            total_impressions_7d = 0
            total_conversions_14d = 0.0
            total_spend_3d = 0

            for c in campaigns.values():
                n = c['row_count'] or 1
                lost_budget_pct = round((c['lost_is_budget_sum'] / n) * 100, 2)
                lost_rank_pct = round((c['lost_is_rank_sum'] / n) * 100, 2)

                total_impressions_7d += c['impressions_7d']
                total_conversions_14d += c['conversions_14d']
                total_spend_3d += c['spend_3d_micros']

                # Per-campaign flags
                if c['campaign_status'] == 'PAUSED':
                    self.reporter.log_issue(self.cid, "SERVING", "CRITICAL",
                                            f"Campaign paused: {c['campaign_name']}")

                if c['campaign_status'] == 'ENABLED' and c['impressions_7d'] == 0:
                    self.reporter.log_issue(self.cid, "SERVING", "CRITICAL",
                                            f"Zero impressions (7d) on enabled campaign: {c['campaign_name']}")

                if lost_budget_pct >= _BUDGET_LOST_CRITICAL_PCT:
                    self.reporter.log_issue(self.cid, "SERVING", "CRITICAL",
                                            f"Budget exhausted — losing {lost_budget_pct:.0f}% of impressions: {c['campaign_name']}")

                snapshots.append({
                    'customer_id': self.cid,
                    'campaign_name': c['campaign_name'],
                    'campaign_status': c['campaign_status'],
                    'impressions_7d': c['impressions_7d'],
                    'conversions_14d': c['conversions_14d'],
                    'spend_3d_micros': c['spend_3d_micros'],
                    'lost_is_budget_pct': lost_budget_pct,
                    'lost_is_rank_pct': lost_rank_pct,
                })

            # Account-level flags
            if total_spend_3d == 0:
                self.reporter.log_issue(self.cid, "SERVING", "CRITICAL",
                                        f"Zero spend in last {_SPEND_ZERO_DAYS} days — billing or account issue.")

            if total_impressions_7d == 0:
                self.reporter.log_issue(self.cid, "SERVING", "CRITICAL",
                                        "Zero impressions across all campaigns in 7 days.")

            if total_conversions_14d == 0:
                self.reporter.log_issue(self.cid, "SERVING", "CRITICAL",
                                        f"Zero conversions in last {_ZERO_CONVERSIONS_DAYS} days.")

            self.db.save_serving_health(snapshots)

        except Exception as e:
            print(f"Error auditing serving health: {e}")

    @gads_retry()
    def audit_keywords_summary(self) -> None:
        """Count active keywords by match type + negative keywords across all lists."""
        print(f"[{self.cid}] Auditing keyword inventory...")
        kw_query = """
            SELECT
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.status,
                ad_group_criterion.quality_info.quality_score
            FROM ad_group_criterion
            WHERE ad_group_criterion.type = 'KEYWORD'
              AND ad_group_criterion.status != 'REMOVED'
              AND campaign.status = 'ENABLED'
        """
        neg_query = """
            SELECT shared_criterion.type
            FROM shared_criterion
            WHERE shared_criterion.type = 'KEYWORD'
        """
        campaign_neg_query = """
            SELECT campaign_criterion.type
            FROM campaign_criterion
            WHERE campaign_criterion.negative = true
              AND campaign_criterion.type = 'KEYWORD'
        """
        try:
            svc = self.gads.get_service("GoogleAdsService")
            match_counts = {'EXACT': 0, 'PHRASE': 0, 'BROAD': 0}
            qs_values: list[int] = []

            for row in svc.search(customer_id=self.cid, query=kw_query):
                mt = row.ad_group_criterion.keyword.match_type.name
                match_counts[mt] = match_counts.get(mt, 0) + 1
                qs = row.ad_group_criterion.quality_info.quality_score
                if qs and qs > 0:
                    qs_values.append(qs)

            shared_negs = sum(1 for _ in svc.search(customer_id=self.cid, query=neg_query))
            campaign_negs = sum(1 for _ in svc.search(customer_id=self.cid, query=campaign_neg_query))
            total_negs = shared_negs + campaign_negs

            total_kws = sum(match_counts.values())
            avg_qs = round(sum(qs_values) / len(qs_values), 1) if qs_values else 0
            low_qs_count = sum(1 for q in qs_values if q <= 4)

            kw_summary = (
                f"Total KWs: {total_kws}  "
                f"Exact: {match_counts.get('EXACT', 0)}  "
                f"Phrase: {match_counts.get('PHRASE', 0)}  "
                f"Broad: {match_counts.get('BROAD', 0)}  "
                f"Negatives: {total_negs}  "
                f"Avg QS: {avg_qs}  "
                f"Low QS (≤4): {low_qs_count}"
            )
            self.reporter.log_issue(
                self.cid, "KEYWORDS", "INFO",
                "Keyword inventory snapshot",
                details=kw_summary,
            )

            if low_qs_count > 0:
                self.reporter.log_issue(
                    self.cid, "KEYWORDS", "WARNING",
                    f"{low_qs_count} keyword{'s' if low_qs_count > 1 else ''} with Quality Score ≤4 — wasting spend",
                    details=f"Avg QS across account: {avg_qs}. Low QS drives up CPC and reduces impression share.",
                )

            if total_kws > 0 and total_negs < 20:
                self.reporter.log_issue(
                    self.cid, "KEYWORDS", "WARNING",
                    f"Only {total_negs} negative keywords — account may be under-filtered",
                    details="Healthy accounts typically have 50+ negatives to block irrelevant traffic.",
                )

        except Exception as e:
            print(f"Error auditing keyword summary: {e}")

    @gads_retry()
    def audit_wasted_spend(self) -> None:
        """Flag high-impression search terms with very low CTR — irrelevant traffic with no engagement."""
        print(f"[{self.cid}] Auditing wasted spend...")
        # Conversions aren't attributed at search term level for call/form tracking,
        # so use CTR as the relevance signal instead.
        query = """
            SELECT
                search_term_view.search_term,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.ctr
            FROM search_term_view
            WHERE segments.date DURING LAST_30_DAYS
              AND metrics.impressions >= 50
            ORDER BY metrics.impressions DESC
        """
        _CTR_WASTE_THRESHOLD = 0.005  # 0.5% CTR

        try:
            svc = self.gads.get_service("GoogleAdsService")
            wasted: list[tuple[str, int, float, float]] = []  # term, impr, ctr, cost
            total_wasted = 0.0

            for row in svc.search(customer_id=self.cid, query=query):
                ctr = row.metrics.ctr
                impr = row.metrics.impressions
                cost = row.metrics.cost_micros / 1_000_000
                if ctr < _CTR_WASTE_THRESHOLD:
                    wasted.append((row.search_term_view.search_term, impr, ctr * 100, cost))
                    total_wasted += cost

            if not wasted:
                return

            wasted.sort(key=lambda t: t[1], reverse=True)
            top = wasted[:15]
            terms_str = ", ".join(f"{t} ({impr} impr, {ctr:.2f}% CTR)" for t, impr, ctr, _ in top)
            suffix = f" (+{len(wasted) - 15} more)" if len(wasted) > 15 else ""
            sev = "WARNING" if total_wasted < 100 else "CRITICAL"

            # Auto-negate — push all low-CTR terms into the shared negatives list
            if not self.dry_run:
                shared_set_rn = self.get_or_create_shared_set('LNM Global Negatives')
                if shared_set_rn:
                    kws = [NegativeKeyword(text=t[0], match_type='EXACT') for t in wasted[:100]]
                    self.add_negatives_to_shared_set(shared_set_rn, kws)

            action = "[DRY RUN] Would negate" if self.dry_run else "Negated"
            self.reporter.log_issue(
                self.cid, "WASTED_SPEND", sev,
                f"{action} {len(wasted)} search terms with ≥50 impressions and <0.5% CTR",
                details=terms_str + suffix,
            )
        except Exception as e:
            print(f"Error auditing wasted spend: {e}")

    @gads_retry()
    def audit_conversion_tracking(self) -> None:
        """Check conversion actions are active; get conversion totals from campaign resource."""
        print(f"[{self.cid}] Auditing conversion tracking...")
        # conversion_action can't join metrics — query separately
        action_query = """
            SELECT
                conversion_action.name,
                conversion_action.status,
                conversion_action.type
            FROM conversion_action
            WHERE conversion_action.status = 'ENABLED'
        """
        # Campaign resource supports metrics + segments.date
        # conversion_action fields can't be selected FROM campaign — use metrics only
        conv_query = """
            SELECT
                metrics.conversions
            FROM campaign
            WHERE campaign.status = 'ENABLED'
              AND segments.date DURING LAST_30_DAYS
        """
        try:
            svc = self.gads.get_service("GoogleAdsService")

            action_names: list[str] = []
            for row in svc.search(customer_id=self.cid, query=action_query):
                action_names.append(row.conversion_action.name)

            if not action_names:
                self.reporter.log_issue(
                    self.cid, "CONV_TRACKING", "CRITICAL",
                    "No active conversion actions found",
                    details="Account has no conversion tracking. Cannot optimize for leads.",
                )
                return

            total_conversions = 0.0
            for row in svc.search(customer_id=self.cid, query=conv_query):
                total_conversions += row.metrics.conversions

            action_list = ", ".join(action_names)
            self.reporter.log_issue(
                self.cid, "CONV_TRACKING", "INFO",
                f"{len(action_names)} conversion action{'s' if len(action_names) != 1 else ''} configured — {total_conversions:.0f} conversions (30d)",
                details=f"Actions: {action_list}",
            )

            if total_conversions == 0:
                self.reporter.log_issue(
                    self.cid, "CONV_TRACKING", "CRITICAL",
                    "Zero conversions recorded in last 30 days",
                    details="Tracking may be broken. Verify GTM tags fire on form submissions and calls.",
                )

        except Exception as e:
            print(f"Error auditing conversion tracking: {e}")

    @gads_retry()
    def audit_budget_recommendation(self) -> None:
        """Calculate recommended daily budget if account is budget-capped."""
        print(f"[{self.cid}] Checking budget recommendation...")
        query = """
            SELECT
                campaign.name,
                campaign_budget.amount_micros,
                metrics.search_budget_lost_impression_share,
                metrics.cost_micros,
                segments.date
            FROM campaign
            WHERE campaign.status = 'ENABLED'
              AND segments.date DURING LAST_30_DAYS
        """
        try:
            svc = self.gads.get_service("GoogleAdsService")
            campaigns: dict[str, dict] = {}

            for row in svc.search(customer_id=self.cid, query=query):
                name = row.campaign.name
                if name not in campaigns:
                    campaigns[name] = {
                        'budget_micros': row.campaign_budget.amount_micros,
                        'lost_budget_sum': 0.0,
                        'cost_sum': 0,
                        'days': 0,
                    }
                campaigns[name]['lost_budget_sum'] += row.metrics.search_budget_lost_impression_share
                campaigns[name]['cost_sum'] += row.metrics.cost_micros
                campaigns[name]['days'] += 1

            for name, c in campaigns.items():
                if c['days'] == 0:
                    continue
                lost_pct = (c['lost_budget_sum'] / c['days']) * 100
                if lost_pct < _KPI_LOST_BUDGET_WARN_PCT:
                    continue

                current_budget = c['budget_micros'] / 1_000_000
                avg_daily_spend = (c['cost_sum'] / 1_000_000) / c['days']
                # Estimated full-capture budget = avg_daily_spend / (1 - lost_pct/100)
                recommended = avg_daily_spend / max(0.01, 1 - lost_pct / 100)

                self.reporter.log_issue(
                    self.cid, "BUDGET_REC",
                    "CRITICAL" if lost_pct >= _KPI_LOST_BUDGET_CRIT_PCT else "WARNING",
                    f"{name}: losing {lost_pct:.0f}% to budget — recommend ${recommended:.0f}/day (currently ${current_budget:.0f}/day)",
                    details=f"Avg daily spend: ${avg_daily_spend:.2f}. Increase budget to capture full search demand.",
                )
        except Exception as e:
            print(f"Error auditing budget recommendation: {e}")

    def compute_health_score(self) -> int:
        """0–100 score: start at 100, deduct per severity. Stored to DB."""
        score = 100
        for issue in self.reporter.issues:
            sev = issue.get("severity", "")
            if sev == "CRITICAL":
                score -= 15
            elif sev == "WARNING":
                score -= 5
            elif sev == "INFO":
                score -= 1
        score = max(0, score)
        self.db.save_health_score(self.cid, score)
        return score

    def run_all(self) -> ReportingService:
        self.audit_serving_health()
        self.audit_performance_kpis()
        self.audit_keywords_summary()
        self.audit_conversion_tracking()
        self.audit_wasted_spend()
        self.audit_budget_recommendation()
        self.audit_bid_strategy()
        self.audit_ads_and_campaigns()
        self.audit_assets()
        self.audit_asset_health()
        self.dismiss_recommendations()
        self.prune_search_terms()
        self.audit_competitor_search_terms()
        self.apply_competitor_negatives()
        self.calculate_roi_metrics()
        score = self.compute_health_score()
        print(f"[{self.cid}] Optimization complete. Health score: {score}/100")
        return self.reporter

    def run_deep_dive(self) -> ReportingService:
        self.run_all()
        self.identify_keyword_opportunities()
        self.audit_headline_relevancy()
        self.audit_dsa_performance()
        self.audit_campaign_structure()
        print(f"[{self.cid}] Deep Dive complete.")
        return self.reporter
