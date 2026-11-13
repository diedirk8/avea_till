"""Performance analytics for Avea Business Performance workspace.

Ranking methodology and gross-profit cost basis are defined in ADR-010
(docs/decisions.md).
"""
import math
import re

from collections import defaultdict

from odoo import _, api, models
from odoo.tools.float_utils import float_is_zero
from odoo.tools.misc import formatLang

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
    def _avea_performance_revenue_lines_for_orders(self, orders):
        """Product sale lines plus Avea Combo Price discount lines (negative revenue)."""
        product_lines = self._avea_performance_lines_for_orders(orders)
        if not orders:
            return product_lines
        combo_lines = orders.lines.filtered("avea_combo_program_id")
        return product_lines | combo_lines

    @api.model
    def _avea_performance_financial_summary(self, orders):
        """Period totals for Sales, COGS, Gross Profit and Discounts Given."""
        product_lines = self._avea_performance_lines_for_orders(orders)
        revenue_lines = self._avea_performance_revenue_lines_for_orders(orders)
        self._avea_performance_ensure_line_costs(product_lines)
        discount_lines = self._avea_performance_discount_lines_for_orders(orders)
        revenue_ex_tax = sum(revenue_lines.mapped("price_subtotal"))
        cost_total = sum(product_lines.mapped("total_cost"))
        gross_profit = sum(revenue_lines.mapped("margin"))
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
    def _avea_discount_pricelist_reason(self, line):
        """Pricelist name when the order used a non-default POS pricelist."""
        order = line.order_id
        if not order or not order.pricelist_id:
            return False
        baseline = order.config_id.pricelist_id if order.config_id else False
        if baseline and order.pricelist_id.id == baseline.id:
            return False
        name = (order.pricelist_id.name or order.pricelist_id.display_name or "").strip()
        return name or False

    @api.model
    def _avea_discount_reason_label(self, line):
        """Best-effort discount reason from POS line data; neutral when unknown."""
        Program = self.env["loyalty.program"]
        if line.avea_combo_program_id:
            program = Program.browse(line.avea_combo_program_id).exists()
            if program and program.avea_is_combo:
                return _("Combo Price")
            if program:
                return _("Promotion")
        reward_program = line.reward_id.program_id if line.reward_id else False
        if reward_program:
            program_type = reward_program.program_type or ""
            if program_type == "loyalty":
                return _("Loyalty")
            if program_type == "ewallet":
                return _("e-wallet")
            if program_type == "gift_card":
                return _("Gift card")
            return _("Promotion")
        if line.is_reward_line:
            return _("Promotion")
        if float(line.discount or 0.0):
            return _("Manual discount")
        if getattr(line, "price_type", False) == "manual":
            return _("Price override")
        pricelist_reason = self._avea_discount_pricelist_reason(line)
        if pricelist_reason:
            return pricelist_reason
        return _("Other")

    @api.model
    def _avea_reward_discount_product_line_candidates(self, order):
        return order.lines.filtered(
            lambda candidate: (
                not candidate.is_reward_line
                and candidate.product_id
                and candidate.product_id.type not in ("service", "combo")
                and not candidate.combo_line_ids
                and candidate.qty
            )
        )

    @api.model
    def _avea_reward_discount_target_lines_from_description(self, line):
        """When POS only stored reward_identifier_code on the discount line."""
        label = (line.full_product_name or line.name or "").strip()
        if not label:
            return self.env["pos.order.line"]
        product_hint = False
        match = re.search(r"\bon\s+(.+)$", label, flags=re.IGNORECASE)
        if match:
            product_hint = match.group(1).strip()
        if not product_hint or product_hint.lower() in {"your order", "the order"}:
            return self.env["pos.order.line"]
        candidates = self._avea_reward_discount_product_line_candidates(line.order_id)

        def line_label(candidate):
            return (
                candidate.avea_product_display
                or candidate.full_product_name
                or candidate.product_id.display_name
                or ""
            ).strip()

        return candidates.filtered(
            lambda candidate: (
                line_label(candidate) == product_hint
                or product_hint in line_label(candidate)
                or line_label(candidate) in product_hint
            )
        )

    @api.model
    def _avea_reward_discount_target_lines(self, line):
        """Product lines that a POS loyalty reward discount line applies to."""
        if not line.is_reward_line:
            return self.env["pos.order.line"]
        if line.reward_identifier_code:
            linked = line.order_id.lines.filtered(
                lambda candidate: (
                    candidate.reward_identifier_code == line.reward_identifier_code
                    and not candidate.is_reward_line
                    and candidate.product_id
                    and candidate.product_id.type not in ("service", "combo")
                    and not candidate.combo_line_ids
                    and candidate.qty
                )
            )
            if linked:
                return linked
        return self._avea_reward_discount_target_lines_from_description(line)

    @api.model
    def _avea_discount_report_line_presentation(self, line, discount_amount):
        """Product label and unit amounts for a discount report row."""
        target_lines = self._avea_reward_discount_target_lines(line)
        if target_lines:
            labels = []
            seen = set()
            for target in target_lines:
                label = (
                    target.avea_product_display
                    or target.full_product_name
                    or target.product_id.display_name
                )
                if label and label not in seen:
                    seen.add(label)
                    labels.append(label)
            product_display = ", ".join(labels)
            qty = sum(abs(float(target.qty or 0.0)) for target in target_lines)
            retail_unit = target_lines[0]._avea_sale_time_retail_unit_ex_tax()
            actual_unit = retail_unit - (discount_amount / qty) if qty else 0.0
            return {
                "product_display": product_display,
                "quantity": qty,
                "retail_unit_ex_tax": retail_unit,
                "actual_unit_ex_tax": actual_unit,
            }
        qty = float(line.qty or 0.0)
        retail_unit = line._avea_sale_time_retail_unit_ex_tax()
        actual_unit = float(line.price_subtotal or 0.0) / qty if qty else 0.0
        return {
            "product_display": line.avea_product_display
            or line.full_product_name
            or (line.product_id.display_name if line.product_id else ""),
            "quantity": qty,
            "retail_unit_ex_tax": retail_unit,
            "actual_unit_ex_tax": actual_unit,
        }

    @api.model
    def _avea_profit_report_rows(self, orders):
        """Line-level profit rows that reconcile to the financial summary."""
        revenue_lines = self._avea_performance_revenue_lines_for_orders(orders)
        self._avea_performance_ensure_line_costs(revenue_lines)
        rows = []
        for line in revenue_lines.sorted(
            key=lambda record: (record.avea_order_date or record.create_date, record.id),
            reverse=True,
        ):
            metrics = self._avea_performance_line_metrics(line)
            rows.append(
                {
                    "pos_line_id": line.id,
                    "order_reference": line.avea_order_reference
                    or line.order_id._avea_till_display_reference()
                    or line.order_id.name,
                    "order_date_label": line.avea_order_date_label,
                    "product_display": line.avea_product_display
                    or line.full_product_name
                    or line.product_id.display_name,
                    "quantity": metrics["qty"],
                    "sales": metrics["revenue_ex_tax"],
                    "cost_total": metrics["cost_total"],
                    "gross_profit": metrics["gross_profit"],
                    "gross_margin_percent": metrics["gross_margin_percent"],
                }
            )
        return rows

    @api.model
    def _avea_discount_report_rows(self, orders):
        """Discount rows that reconcile to Discounts Given for the period."""
        discount_lines = self._avea_performance_discount_lines_for_orders(orders)
        currency = self.env.company.currency_id
        rows = []
        for line in discount_lines.sorted(
            key=lambda record: (record.avea_order_date or record.create_date, record.id),
            reverse=True,
        ):
            discount_amount = self._avea_performance_discount_given(line)
            if float_is_zero(discount_amount, precision_rounding=currency.rounding):
                continue
            presentation = self._avea_discount_report_line_presentation(
                line, discount_amount
            )
            rows.append(
                {
                    "pos_line_id": line.id,
                    "order_reference": line.avea_order_reference
                    or line.order_id._avea_till_display_reference()
                    or line.order_id.name,
                    "order_date_label": line.avea_order_date_label,
                    "product_display": presentation["product_display"],
                    "quantity": presentation["quantity"],
                    "retail_unit_ex_tax": presentation["retail_unit_ex_tax"],
                    "actual_unit_ex_tax": presentation["actual_unit_ex_tax"],
                    "discount_amount": discount_amount,
                    "discount_reason": self._avea_discount_reason_label(line),
                }
            )
        return rows

    @api.model
    def _avea_profit_report_data(self, orders):
        summary = self._avea_performance_financial_summary(orders)
        rows = self._avea_profit_report_rows(orders)
        return {"summary": summary, "rows": rows}

    @api.model
    def _avea_discount_report_data(self, orders):
        summary = self._avea_performance_financial_summary(orders)
        rows = self._avea_discount_report_rows(orders)
        return {"summary": summary, "rows": rows}

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

    PROMOTION_PRODUCT_ROW_LIMIT = 40
    _AVEA_PROMOTION_PROGRAM_TYPES = frozenset(
        ("promotion", "promo_code", "buy_x_get_y")
    )

    @api.model
    def _avea_is_reportable_promotion_program(self, program):
        """Avea till deals, plus native POS promotions (not loyalty clubs)."""
        if not program:
            return False
        if program.avea_promotion_id or program.avea_is_combo:
            return True
        return (program.program_type or "") in self._AVEA_PROMOTION_PROGRAM_TYPES

    @api.model
    def _avea_promotion_program_for_line(self, line):
        Program = self.env["loyalty.program"]
        program = False
        if line.avea_combo_program_id:
            program = Program.browse(line.avea_combo_program_id).exists()
        elif line.reward_id:
            program = line.reward_id.program_id
        elif "coupon_id" in line._fields and line.coupon_id:
            program = line.coupon_id.program_id
        if program and self._avea_is_reportable_promotion_program(program):
            return program
        return Program.browse()

    @api.model
    def _avea_promotion_programs_on_order(self, order):
        programs = self.env["loyalty.program"]
        for line in order.lines:
            programs |= self._avea_promotion_program_for_line(line)
        point_ids = order.coupon_point_ids if "coupon_point_ids" in order._fields else []
        for rec in point_ids:
            program = getattr(rec, "program_id", False)
            if not program:
                coupon = getattr(rec, "coupon_id", False)
                program = coupon.program_id if coupon else False
            if program and self._avea_is_reportable_promotion_program(program):
                programs |= program
        return programs

    @api.model
    def _avea_promotion_meta(self, program):
        promotion = program.avea_promotion_id
        if promotion:
            deal_type = promotion.deal_type or ""
            labels = dict(promotion._fields["deal_type"].selection)
            return {
                "promotion_id": promotion.id,
                "program_id": program.id,
                "name": promotion.name or program.name,
                "deal_type": deal_type,
                "deal_type_label": labels.get(deal_type) or _("Promotion"),
                "deal_summary": promotion.deal_summary or labels.get(deal_type) or _("Promotion"),
            }
        if program.avea_is_combo:
            label = _("Combo Price")
            return {
                "promotion_id": False,
                "program_id": program.id,
                "name": program.name,
                "deal_type": "combo_price",
                "deal_type_label": label,
                "deal_summary": label,
            }
        type_labels = {
            "buy_x_get_y": _("Buy X Get Y"),
            "promo_code": _("Promo code"),
            "promotion": _("Promotion"),
        }
        label = type_labels.get(program.program_type or "", _("Promotion"))
        return {
            "promotion_id": False,
            "program_id": program.id,
            "name": program.name,
            "deal_type": program.program_type or "promotion",
            "deal_type_label": label,
            "deal_summary": label,
        }

    @api.model
    def _avea_promotion_discount_display(self, amount, deal_type_label, currency=None):
        currency = currency or self.env.company.currency_id
        if not currency.is_zero(amount or 0.0):
            return formatLang(self.env, amount, currency_obj=currency)
        return deal_type_label or _("Promotion")

    @api.model
    def _avea_promotion_scope_product_lines(self, order, promotion):
        candidates = self._avea_reward_discount_product_line_candidates(order)
        if not promotion:
            return candidates
        if promotion.deal_type == "combo_price":
            combo_products = promotion.combo_line_ids.mapped("product_id")
            if combo_products:
                return candidates.filtered(lambda line: line.product_id in combo_products)
        if promotion.product_scope == "products" and promotion.product_ids:
            return candidates.filtered(lambda line: line.product_id in promotion.product_ids)
        if promotion.product_scope == "category" and promotion.product_category_id:
            category = promotion.product_category_id
            return candidates.filtered(
                lambda line: line.product_id.categ_id
                and (
                    line.product_id.categ_id == category
                    or line.product_id.categ_id.parent_path
                    and line.product_id.categ_id.parent_path.startswith(
                        category.parent_path or ""
                    )
                )
            )
        return candidates

    @api.model
    def _avea_promotion_target_product_lines(self, reward_line):
        targets = self._avea_reward_discount_target_lines(reward_line)
        if targets:
            return targets
        return self._avea_reward_discount_product_line_candidates(reward_line.order_id)

    @api.model
    def _avea_promotion_empty_analysis(self):
        return {
            "summary": {
                "order_count": 0,
                "unit_count": 0.0,
                "discount_given": 0.0,
                "sales_ex_tax": 0.0,
                "promotion_count": 0,
            },
            "promotions": [],
            "products": [],
        }

    @api.model
    def _avea_promotion_analysis(self, orders):
        """Period promotion analysis: deals that fired, products sold, discount or type."""
        empty = self._avea_promotion_empty_analysis()
        if not orders:
            return empty

        currency = self.env.company.currency_id
        buckets = {}
        product_buckets = {}
        summary_order_ids = set()
        summary_product_line_ids = set()
        summary_discount_line_ids = set()
        summary_discount = 0.0

        def bucket_for(program):
            key = program.id
            if key not in buckets:
                meta = self._avea_promotion_meta(program)
                buckets[key] = {
                    **meta,
                    "order_ids": set(),
                    "unit_count": 0.0,
                    "discount_given": 0.0,
                    "sales_ex_tax": 0.0,
                    "product_line_ids": set(),
                    "discount_line_ids": set(),
                }
            return buckets[key]

        def add_product_line(program, line, allocated_discount=0.0):
            if not line or not line.product_id:
                return
            if line.product_id.type in ("service", "combo") or line.combo_line_ids:
                return
            metrics = self._avea_performance_line_metrics(line)
            bucket = bucket_for(program)
            if line.id not in bucket["product_line_ids"]:
                bucket["product_line_ids"].add(line.id)
                bucket["unit_count"] += abs(metrics["qty"])
                bucket["sales_ex_tax"] += metrics["revenue_ex_tax"]
                summary_product_line_ids.add(line.id)
            product_key = (program.id, line.product_id.id)
            row = product_buckets.setdefault(
                product_key,
                {
                    "promotion_id": bucket["promotion_id"],
                    "program_id": program.id,
                    "promotion_name": bucket["name"],
                    "deal_type_label": bucket["deal_type_label"],
                    "product_id": line.product_id.id,
                    "product_display": self._avea_performance_product_label(line.product_id),
                    "quantity": 0.0,
                    "discount_given": 0.0,
                    "sales_ex_tax": 0.0,
                    "line_ids": set(),
                },
            )
            if line.id not in row["line_ids"]:
                row["line_ids"].add(line.id)
                row["quantity"] += abs(metrics["qty"])
                row["sales_ex_tax"] += metrics["revenue_ex_tax"]
            row["discount_given"] += allocated_discount

        def add_discount_line(program, line):
            if not line or line.id in summary_discount_line_ids:
                return 0.0
            amount = self._avea_performance_discount_given(line)
            summary_discount_line_ids.add(line.id)
            bucket = bucket_for(program)
            bucket["discount_line_ids"].add(line.id)
            bucket["discount_given"] += amount
            nonlocal summary_discount
            summary_discount += amount
            return amount

        for order in orders:
            programs = self._avea_promotion_programs_on_order(order)
            if not programs:
                continue
            summary_order_ids.add(order.id)
            for program in programs:
                bucket_for(program)["order_ids"].add(order.id)

            allocated_product_ids = set()
            discount_lines = []
            tagged_product_lines = []
            for line in order.lines:
                program = self._avea_promotion_program_for_line(line)
                if not program:
                    continue
                if line.avea_combo_program_id or line.is_reward_line:
                    discount_lines.append((program, line))
                else:
                    tagged_product_lines.append((program, line))

            for program, line in discount_lines:
                discount_amount = add_discount_line(program, line)
                targets = self._avea_promotion_target_product_lines(line)
                if line.avea_combo_program_id:
                    targets = (
                        self._avea_promotion_scope_product_lines(
                            order, program.avea_promotion_id
                        )
                        or targets
                    )
                if not targets:
                    continue
                weights = [abs(float(target.qty or 0.0)) for target in targets]
                weight_total = sum(weights) or float(len(targets) or 1)
                for target, weight in zip(targets, weights):
                    share = (
                        discount_amount * (weight / weight_total) if weight_total else 0.0
                    )
                    add_product_line(program, target, allocated_discount=share)
                    allocated_product_ids.add(target.id)

            for program, line in tagged_product_lines:
                line_discount = 0.0
                if line.id not in summary_discount_line_ids:
                    line_discount = self._avea_performance_discount_given(line)
                    if line_discount:
                        add_discount_line(program, line)
                add_product_line(program, line, allocated_discount=line_discount)
                allocated_product_ids.add(line.id)

            for program in programs:
                scoped = self._avea_promotion_scope_product_lines(
                    order, program.avea_promotion_id
                )
                for line in scoped:
                    if line.id in allocated_product_ids:
                        continue
                    add_product_line(program, line)

        promotion_rows = []
        for bucket in buckets.values():
            discount = bucket["discount_given"]
            promotion_rows.append(
                {
                    "promotion_id": bucket["promotion_id"] or False,
                    "program_id": bucket["program_id"],
                    "name": bucket["name"],
                    "deal_type": bucket["deal_type"],
                    "deal_type_label": bucket["deal_type_label"],
                    "deal_summary": bucket["deal_summary"],
                    "order_count": len(bucket["order_ids"]),
                    "quantity": bucket["unit_count"],
                    "discount_given": discount,
                    "discount_display": self._avea_promotion_discount_display(
                        discount, bucket["deal_type_label"], currency
                    ),
                    "sales_ex_tax": bucket["sales_ex_tax"],
                }
            )
        promotion_rows.sort(
            key=lambda row: (
                -abs(row["discount_given"]),
                -row["sales_ex_tax"],
                -row["quantity"],
                row["name"] or "",
            )
        )

        product_rows = []
        for row in product_buckets.values():
            product_rows.append(
                {
                    "promotion_id": row["promotion_id"] or False,
                    "program_id": row["program_id"],
                    "promotion_name": row["promotion_name"],
                    "deal_type_label": row["deal_type_label"],
                    "product_id": row["product_id"],
                    "product_display": row["product_display"],
                    "quantity": row["quantity"],
                    "discount_given": row["discount_given"],
                    "discount_display": self._avea_promotion_discount_display(
                        row["discount_given"], row["deal_type_label"], currency
                    ),
                    "sales_ex_tax": row["sales_ex_tax"],
                }
            )
        product_rows.sort(
            key=lambda row: (
                -row["quantity"],
                -abs(row["discount_given"]),
                -row["sales_ex_tax"],
                row["product_display"] or "",
            )
        )
        product_rows = product_rows[: self.PROMOTION_PRODUCT_ROW_LIMIT]

        summary_units = 0.0
        summary_sales = 0.0
        if summary_product_line_ids:
            product_lines = self.env["pos.order.line"].browse(list(summary_product_line_ids))
            self._avea_performance_ensure_line_costs(product_lines)
            for line in product_lines:
                metrics = self._avea_performance_line_metrics(line)
                summary_units += abs(metrics["qty"])
                summary_sales += metrics["revenue_ex_tax"]

        return {
            "summary": {
                "order_count": len(summary_order_ids),
                "unit_count": summary_units,
                "discount_given": summary_discount,
                "sales_ex_tax": summary_sales,
                "promotion_count": len(promotion_rows),
            },
            "promotions": promotion_rows,
            "products": product_rows,
        }
