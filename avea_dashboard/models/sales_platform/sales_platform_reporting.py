# -*- coding: utf-8 -*-
"""Sales platform metrics for Avea Business Overview / Performance (shared source of truth)."""

from collections import defaultdict

from odoo import api, models
class AveaSalesPlatformReporting(models.AbstractModel):
    _name = "avea.sales.platform.reporting.mixin"
    _description = "Sales Platform Reporting Helpers"

    def _avea_commission_from_revenue_ex_tax(self, revenue_ex_tax):
        """Platform fee from actual selling price (ex tax), aligned with platform % settings."""
        self.ensure_one()
        rate = (self.commission_percent or 0.0) / 100.0
        fee = float(revenue_ex_tax or 0.0) * rate
        if self.commission_vat:
            fee *= 1.0 + self._avea_default_commission_vat_rate(self.company_id)
        currency = self.company_id.currency_id
        return currency.round(fee)

    @api.model
    def _avea_reporting_active_platforms(self, company=None):
        company = company or self.env.company
        return (
            self.env["avea.sales.platform"]
            .sudo()
            .search([("company_id", "=", company.id), ("active", "=", True)])
        )

    @api.model
    def _avea_reporting_platform_for_order(self, order, pricelist_map, platforms):
        pricelist = order.pricelist_id
        if pricelist and pricelist.id in pricelist_map:
            return pricelist_map[pricelist.id]
        partner = order.partner_id
        if not partner:
            return False
        Partner = self.env["res.partner"]
        for platform in platforms:
            root = platform.partner_id
            if not root:
                continue
            if partner.id == root.id:
                return platform
            if Partner.search_count([("id", "=", partner.id), ("id", "child_of", root.id)]):
                return platform
        return False

    @api.model
    def _avea_reporting_summarize_orders(self, orders):
        """Aggregate platform sales for paid POS orders in the reporting period."""
        Platform = self.env["avea.sales.platform"]
        Line = self.env["pos.order.line"]
        platforms = Platform._avea_reporting_active_platforms()
        pricelist_map = {
            platform.pricelist_id.id: platform
            for platform in platforms
            if platform.pricelist_id
        }
        empty_totals = {
            "sales_ex_tax": 0.0,
            "cost_total": 0.0,
            "gross_profit": 0.0,
            "commission": 0.0,
            "contribution": 0.0,
            "line_count": 0,
        }
        if not platforms or not orders:
            return {"has_activity": False, "platforms": [], "totals": empty_totals}

        product_lines = Line._avea_performance_lines_for_orders(orders)
        revenue_lines = Line._avea_performance_revenue_lines_for_orders(orders)
        Line._avea_performance_ensure_line_costs(product_lines)

        buckets = defaultdict(
            lambda: {
                "sales_ex_tax": 0.0,
                "cost_total": 0.0,
                "gross_profit": 0.0,
                "commission": 0.0,
                "line_count": 0,
                "products": defaultdict(lambda: {"label": "", "revenue": 0.0}),
            }
        )

        for line in revenue_lines:
            platform = Platform._avea_reporting_platform_for_order(
                line.order_id, pricelist_map, platforms
            )
            if not platform:
                continue
            metrics = Line._avea_performance_line_metrics(line)
            revenue_ex = metrics["revenue_ex_tax"]
            bucket = buckets[platform.id]
            bucket["sales_ex_tax"] += revenue_ex
            bucket["line_count"] += 1
            if line in product_lines:
                bucket["cost_total"] += metrics["cost_total"]
                bucket["gross_profit"] += metrics["gross_profit"]
            bucket["commission"] += platform._avea_commission_from_revenue_ex_tax(revenue_ex)
            if line.product_id:
                key = line.product_id.id
                entry = bucket["products"][key]
                entry["label"] = (
                    line.avea_product_display
                    or line.product_id.display_name
                    or line.product_id.name
                )
                entry["revenue"] += abs(revenue_ex)

        currency = self.env.company.currency_id
        platform_rows = []
        totals = dict(empty_totals)
        platform_records = {p.id: p for p in platforms}
        for platform_id, bucket in buckets.items():
            if not bucket["line_count"]:
                continue
            sales_ex = currency.round(bucket["sales_ex_tax"])
            if currency.is_zero(sales_ex) and not bucket["line_count"]:
                continue
            commission = currency.round(bucket["commission"])
            gross_profit = currency.round(bucket["gross_profit"])
            cost_total = currency.round(bucket["cost_total"])
            contribution = currency.round(gross_profit - commission)
            top_product = ""
            if bucket["products"]:
                top = max(bucket["products"].values(), key=lambda row: row["revenue"])
                top_product = top["label"] or ""
            platform = platform_records.get(platform_id)
            if not platform:
                continue
            row = {
                "platform_id": platform_id,
                "name": platform.name,
                "sales_ex_tax": sales_ex,
                "cost_total": cost_total,
                "gross_profit": gross_profit,
                "commission": commission,
                "contribution": contribution,
                "line_count": bucket["line_count"],
                "top_product_name": top_product,
            }
            platform_rows.append(row)
            for key in ("sales_ex_tax", "cost_total", "gross_profit", "commission", "contribution"):
                totals[key] += row[key]
            totals["line_count"] += row["line_count"]

        for key in totals:
            if key != "line_count":
                totals[key] = currency.round(totals[key])

        has_activity = bool(platform_rows)
        platform_rows.sort(key=lambda row: (-abs(row["sales_ex_tax"]), row["name"]))
        return {
            "has_activity": has_activity,
            "platforms": platform_rows,
            "totals": totals,
        }
