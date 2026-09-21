"""Performance analytics for Avea Business Performance workspace.

Ranking methodology and gross-profit cost basis are defined in ADR-010
(docs/decisions.md).
"""
import math

from odoo import _, api, models

PERFORMANCE_RANK_LIMIT = 8


class PosOrderLinePerformanceAnalytics(models.AbstractModel):
    _name = "avea.performance.analytics.mixin"
    _description = "Avea Performance Analytics Helpers"

    @api.model
    def _avea_performance_line_domain(self, order_ids):
        if not order_ids:
            return [("id", "=", 0)]
        return [
            ("order_id", "in", order_ids),
            ("product_id", "!=", False),
            ("product_id.type", "not in", ("service", "combo")),
            ("combo_line_ids", "=", False),
            ("qty", "!=", 0.0),
        ]

    @api.model
    def _avea_performance_lines_for_orders(self, orders):
        if not orders:
            return self.env["pos.order.line"].browse()
        return self.env["pos.order.line"].search(
            self._avea_performance_line_domain(orders.ids)
        )

    @api.model
    def _avea_performance_ensure_line_costs(self, lines):
        """Ensure Odoo has computed historical POS line costs before reporting."""
        for order in lines.order_id:
            pending = order.lines.filtered(
                lambda line: line.product_id and not line.is_total_cost_computed
            )
            if pending:
                order._compute_total_cost_in_real_time()

    @api.model
    def _avea_performance_discount_lines_for_orders(self, orders):
        """Lines that can contribute to Discounts Given for the selected orders."""
        if not orders:
            return self.env["pos.order.line"].browse()
        return orders.lines.filtered(
            lambda line: (
                line.avea_combo_program_id
                or line.is_reward_line
                or (
                    line.product_id
                    and line.product_id.type not in ("service", "combo")
                    and not line.combo_line_ids
                    and line.qty
                )
            )
        )

    @api.model
    def _avea_performance_discount_given(self, line):
        return float(line._avea_discount_given_ex_tax())

    @api.model
    def _avea_performance_gross_margin_percent(self, revenue_ex_tax, gross_profit):
        if revenue_ex_tax > 0:
            return (gross_profit / revenue_ex_tax) * 100.0
        return 0.0

    @api.model
    def _avea_performance_line_metrics(self, line):
        """Return revenue, cost, gross profit and unit counts for one POS line.

        Cost of goods sold comes from Odoo's ``pos.order.line.total_cost`` — the
        cost of the stock sold at transaction time (from stock moves / AVCO).
        ``avea_cost_ex_tax`` is not used here; it remains for Stock and pricing.
        Gross profit follows native POS ``margin`` (revenue ex tax minus COGS).
        """
        self._avea_performance_ensure_line_costs(line)
        qty = float(line.qty or 0.0)
        revenue_ex_tax = float(line.price_subtotal or 0.0)
        cost_total = float(line.total_cost or 0.0)
        gross_profit = float(line.margin or 0.0)
        discount_given = self._avea_performance_discount_given(line)
        units_positive = qty if qty > 0 else 0.0
        return {
            "qty": qty,
            "revenue_ex_tax": revenue_ex_tax,
            "cost_total": cost_total,
            "gross_profit": gross_profit,
            "discount_given": discount_given,
            "gross_margin_percent": self._avea_performance_gross_margin_percent(
                revenue_ex_tax, gross_profit
            ),
            "units_positive": units_positive,
        }

    @api.model
    def _avea_performance_financial_summary(self, orders):
        """Period totals for Sales, COGS, Gross Profit and Discounts Given."""
        product_lines = self._avea_performance_lines_for_orders(orders)
        self._avea_performance_ensure_line_costs(product_lines)
        discount_lines = self._avea_performance_discount_lines_for_orders(orders)
        revenue_ex_tax = sum(product_lines.mapped("price_subtotal"))
        cost_total = sum(product_lines.mapped("total_cost"))
        gross_profit = sum(product_lines.mapped("margin"))
        discounts_given = sum(
            self._avea_performance_discount_given(line) for line in discount_lines
        )
        return {
            "revenue_ex_tax": float(revenue_ex_tax or 0.0),
            "cost_total": float(cost_total or 0.0),
            "gross_profit": float(gross_profit or 0.0),
            "discounts_given": float(discounts_given or 0.0),
            "gross_margin_percent": self._avea_performance_gross_margin_percent(
                float(revenue_ex_tax or 0.0), float(gross_profit or 0.0)
            ),
        }

    @api.model
    def _avea_performance_product_label(self, product):
        """Customer-facing product label without internal reference."""
        return product._avea_plain_name()

    @api.model
    def _avea_performance_bucket_key(self, line, *, group_by):
        if group_by == "product":
            product = line.product_id
            if not product:
                return False
            return ("product", product.id, self._avea_performance_product_label(product))
        category = line.product_id.categ_id
        if not category:
            return ("category", 0, _("Uncategorised"))
        return ("category", category.id, category.complete_name or category.name)

    @api.model
    def _avea_performance_aggregate(self, lines, *, group_by):
        """Aggregate sale lines by product or category."""
        buckets = {}
        for line in lines:
            key = self._avea_performance_bucket_key(line, group_by=group_by)
            if not key:
                continue
            _kind, record_id, label = key
            metrics = self._avea_performance_line_metrics(line)
            bucket = buckets.setdefault(
                record_id,
                {
                    "record_id": record_id,
                    "label": label,
                    "qty_net": 0.0,
                    "units_positive": 0.0,
                    "revenue_ex_tax": 0.0,
                    "cost_total": 0.0,
                    "gross_profit": 0.0,
                    "discount_given": 0.0,
                },
            )
            bucket["qty_net"] += metrics["qty"]
            bucket["units_positive"] += metrics["units_positive"]
            bucket["revenue_ex_tax"] += metrics["revenue_ex_tax"]
            bucket["cost_total"] += metrics["cost_total"]
            bucket["gross_profit"] += metrics["gross_profit"]
            bucket["discount_given"] += metrics["discount_given"]
        return list(buckets.values())

    @api.model
    def _avea_performance_score_rows(self, aggregates):
        """Rank by balanced commercial strength (ADR-010)."""
        candidates = [
            row
            for row in aggregates
            if row["revenue_ex_tax"] > 0 and row["units_positive"] >= 1.0
        ]
        if not candidates:
            return []

        period_units = sum(row["units_positive"] for row in candidates)
        if period_units <= 0:
            return []

        scored = []
        for row in candidates:
            volume_ratio = row["units_positive"] / period_units
            performance_score = row["revenue_ex_tax"] * math.sqrt(volume_ratio)
            scored.append({**row, "performance_score": performance_score})

        scored.sort(
            key=lambda row: (
                -row["performance_score"],
                -row["revenue_ex_tax"],
                -row["units_positive"],
                row["label"],
            )
        )
        return scored[:PERFORMANCE_RANK_LIMIT]

    @api.model
    def _avea_performance_profit_rows(self, aggregates):
        """Rank by gross-profit contribution (ADR-010)."""
        candidates = [row for row in aggregates if row["gross_profit"] > 0]
        candidates.sort(
            key=lambda row: (
                -row["gross_profit"],
                -row["revenue_ex_tax"],
                -row["units_positive"],
                row["label"],
            )
        )
        return candidates[:PERFORMANCE_RANK_LIMIT]

    @api.model
    def _avea_performance_enrich_aggregate_rows(self, aggregates):
        for row in aggregates:
            row["gross_margin_percent"] = self._avea_performance_gross_margin_percent(
                row["revenue_ex_tax"], row["gross_profit"]
            )
        return aggregates

    @api.model
    def _avea_performance_rankings(self, orders):
        """Return four ranked lists for the selected paid POS orders."""
        lines = self._avea_performance_lines_for_orders(orders)
        self._avea_performance_ensure_line_costs(lines)
        product_aggs = self._avea_performance_enrich_aggregate_rows(
            self._avea_performance_aggregate(lines, group_by="product")
        )
        category_aggs = self._avea_performance_enrich_aggregate_rows(
            self._avea_performance_aggregate(lines, group_by="category")
        )
        return {
            "financial": self._avea_performance_financial_summary(orders),
            "top_products": self._avea_performance_score_rows(product_aggs),
            "top_categories": self._avea_performance_score_rows(category_aggs),
            "profit_products": self._avea_performance_profit_rows(product_aggs),
            "profit_categories": self._avea_performance_profit_rows(category_aggs),
        }
