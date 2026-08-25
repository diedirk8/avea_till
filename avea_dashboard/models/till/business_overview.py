from calendar import monthrange
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from odoo import Command, _, api, fields, models

from .till_movement import POS_CASH_IN_REASON, POS_CASH_OUT_REASON

OVERVIEW_PRODUCT_LIMIT = 8


class AveaBusinessOverviewProductLine(models.TransientModel):
    _name = "avea.business.overview.product.line"
    _description = "Business Overview Product Line"
    _order = "rank, id"

    dashboard_id = fields.Many2one(
        "avea.business.overview",
        string="Overview",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(
        related="dashboard_id.currency_id",
    )
    rank = fields.Integer(
        string="Rank",
        readonly=True,
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product Record",
        readonly=True,
    )
    product_name = fields.Char(
        string="Product",
        readonly=True,
    )
    quantity_sold = fields.Float(
        string="Quantity Sold",
        digits="Product Unit",
        readonly=True,
    )
    sales_value = fields.Monetary(
        string="Sales Value",
        currency_field="currency_id",
        readonly=True,
    )


class AveaBusinessOverview(models.TransientModel):
    _name = "avea.business.overview"
    _description = "Business Overview"
    _rec_name = "period_label"

    period = fields.Selection(
        [
            ("today", "Today"),
            ("week", "This Week"),
            ("month", "This Month"),
        ],
        string="Period",
        default="today",
        required=True,
    )
    period_label = fields.Char(
        string="Period Label",
        compute="_compute_metrics",
    )
    comparison_label = fields.Char(
        string="Compared With",
        compute="_compute_metrics",
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )

    total_sales = fields.Monetary(
        string="Sales",
        compute="_compute_metrics",
        currency_field="currency_id",
    )
    order_count = fields.Integer(
        string="Transactions",
        compute="_compute_metrics",
    )
    average_order_value = fields.Monetary(
        string="Average Sale",
        compute="_compute_metrics",
        currency_field="currency_id",
    )
    previous_sales = fields.Monetary(
        string="Previous Period",
        compute="_compute_metrics",
        currency_field="currency_id",
    )
    previous_order_count = fields.Integer(
        string="Previous Transactions",
        compute="_compute_metrics",
    )
    sales_change_amount = fields.Monetary(
        string="Change",
        compute="_compute_metrics",
        currency_field="currency_id",
    )
    sales_change_display = fields.Char(
        string="Change %",
        compute="_compute_metrics",
    )
    sales_change_tone = fields.Selection(
        [("up", "Up"), ("down", "Down"), ("flat", "Flat")],
        compute="_compute_metrics",
    )

    cash_sales = fields.Monetary(
        string="Cash",
        compute="_compute_metrics",
        currency_field="currency_id",
    )
    card_sales = fields.Monetary(
        string="Card",
        compute="_compute_metrics",
        currency_field="currency_id",
    )
    other_payments = fields.Monetary(
        string="Other",
        compute="_compute_metrics",
        currency_field="currency_id",
    )
    cash_in_total = fields.Monetary(
        string="Cash In",
        compute="_compute_metrics",
        currency_field="currency_id",
    )
    cash_out_total = fields.Monetary(
        string="Cash Out",
        compute="_compute_metrics",
        currency_field="currency_id",
    )
    cash_in_count = fields.Integer(
        compute="_compute_metrics",
    )
    cash_out_count = fields.Integer(
        compute="_compute_metrics",
    )

    product_line_ids = fields.One2many(
        "avea.business.overview.product.line",
        "dashboard_id",
        string="Top Products",
        readonly=True,
    )
    show_products = fields.Boolean(
        compute="_compute_show_products",
    )
    activity_refund_count = fields.Integer(
        string="Refunds",
        compute="_compute_metrics",
    )
    open_session_count = fields.Integer(
        string="Open Tills",
        compute="_compute_metrics",
    )
    show_refund_attention = fields.Boolean(
        compute="_compute_metrics",
    )
    show_open_sessions = fields.Boolean(
        compute="_compute_metrics",
    )
    show_attention = fields.Boolean(
        compute="_compute_metrics",
    )

    @api.model_create_multi
    def create(self, vals_list):
        overviews = super().create(vals_list)
        overviews._populate_product_lines()
        return overviews

    def write(self, vals):
        res = super().write(vals)
        if "period" in vals:
            self._populate_product_lines()
        return res

    @api.depends("product_line_ids")
    def _compute_show_products(self):
        for overview in self:
            overview.show_products = bool(overview.product_line_ids)

    @api.model
    def action_open_business_overview(self, period="today"):
        if period not in ("today", "week", "month"):
            period = "today"
        overview = self.create({"period": period})
        return {
            "type": "ir.actions.act_window",
            "name": _("Business Overview"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": overview.id,
            "target": "current",
            "context": {"clear_breadcrumbs": True},
        }

    def action_period_today(self):
        return self.action_open_business_overview(period="today")

    def action_period_week(self):
        return self.action_open_business_overview(period="week")

    def action_period_month(self):
        return self.action_open_business_overview(period="month")

    def action_open_sessions(self):
        return self.env["ir.actions.act_window"]._for_xml_id(
            "avea_till.action_avea_sessions"
        )

    def action_open_cash(self):
        return self.env["avea.till.dashboard"].action_open_dashboard()

    def action_refresh(self):
        self.ensure_one()
        return self.action_open_business_overview(period=self.period)

    def _timezone(self):
        tzname = self.env.user.tz or self.env.context.get("tz") or "UTC"
        try:
            return ZoneInfo(tzname)
        except Exception:
            return ZoneInfo("UTC")

    def _utc_bounds(self, day_from, day_to):
        tz = self._timezone()
        start_local = datetime.combine(day_from, time.min, tzinfo=tz)
        end_local = datetime.combine(
            day_to,
            time.max.replace(microsecond=0),
            tzinfo=tz,
        )
        return (
            start_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
            end_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
        )

    def _period_windows(self, period):
        today = fields.Date.context_today(self)
        if period == "week":
            week_start = today - timedelta(days=today.weekday())
            current = (week_start, today)
            previous = (week_start - timedelta(days=7), today - timedelta(days=7))
            labels = (_("This Week"), _("Previous week"))
        elif period == "month":
            month_start = today.replace(day=1)
            if month_start.month == 1:
                prev_start = month_start.replace(year=month_start.year - 1, month=12)
            else:
                prev_start = month_start.replace(month=month_start.month - 1)
            prev_last_day = monthrange(prev_start.year, prev_start.month)[1]
            prev_end = prev_start.replace(day=min(today.day, prev_last_day))
            current = (month_start, today)
            previous = (prev_start, prev_end)
            labels = (_("This Month"), _("Previous month"))
        else:
            yesterday = today - timedelta(days=1)
            current = (today, today)
            previous = (yesterday, yesterday)
            labels = (_("Today"), _("Yesterday"))
        return current, previous, labels

    def _paid_orders_between(self, day_from, day_to):
        start, end = self._utc_bounds(day_from, day_to)
        Session = self.env["pos.session"]
        return self.env["pos.order"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("state", "in", Session._avea_paid_order_states()),
                ("date_order", ">=", start),
                ("date_order", "<=", end),
            ]
        )

    def _cash_activity_between(self, day_from, day_to):
        start, end = self._utc_bounds(day_from, day_to)
        Movement = self.env["avea.till.movement"]
        domain = [
            ("session_id.company_id", "=", self.env.company.id),
            ("movement_date", ">=", start),
            ("movement_date", "<=", end),
        ]
        cash_in_domain = domain + [("reason", "=", POS_CASH_IN_REASON)]
        cash_out_domain = domain + [("reason", "=", POS_CASH_OUT_REASON)]
        return {
            "cash_in_total": Movement.sum_amount_for_domain(cash_in_domain),
            "cash_out_total": Movement.sum_amount_for_domain(cash_out_domain),
            "cash_in_count": Movement.search_count(cash_in_domain),
            "cash_out_count": Movement.search_count(cash_out_domain),
        }

    def _change_display(self, current, previous):
        currency = self.env.company.currency_id
        delta = current - previous
        if currency.is_zero(previous):
            if currency.is_zero(current):
                return _("—"), "flat", delta
            return _("New"), "up", delta
        percent = (delta / previous) * 100.0
        sign = "+" if percent > 0 else ""
        display = f"{sign}{percent:.1f}%"
        if currency.is_zero(delta):
            tone = "flat"
        elif delta > 0:
            tone = "up"
        else:
            tone = "down"
        return display, tone, delta

    @api.depends("period")
    def _compute_metrics(self):
        Session = self.env["pos.session"]
        open_session_count = Session.search_count(
            [
                ("company_id", "=", self.env.company.id),
                ("state", "in", ("opened", "closing_control")),
            ]
        )
        for overview in self:
            period = overview.period or "today"
            current, previous, labels = overview._period_windows(period)
            current_orders = overview._paid_orders_between(*current)
            previous_orders = overview._paid_orders_between(*previous)
            sales = Session._avea_sales_summary_from_orders(current_orders)
            previous_sales = Session._avea_sales_summary_from_orders(previous_orders)
            activity = Session._avea_activity_from_orders(current_orders)
            cash = overview._cash_activity_between(*current)
            change_display, tone, delta = overview._change_display(
                sales["total_sales"],
                previous_sales["total_sales"],
            )
            refund_count = activity["refund_count"]
            overview.update(
                {
                    "period_label": labels[0],
                    "comparison_label": labels[1],
                    "total_sales": sales["total_sales"],
                    "order_count": sales["order_count"],
                    "average_order_value": sales["average_order_value"],
                    "previous_sales": previous_sales["total_sales"],
                    "previous_order_count": previous_sales["order_count"],
                    "sales_change_amount": delta,
                    "sales_change_display": change_display,
                    "sales_change_tone": tone,
                    "cash_sales": sales["cash_sales"],
                    "card_sales": sales["card_sales"],
                    "other_payments": sales["other_payments"],
                    "cash_in_total": cash["cash_in_total"],
                    "cash_out_total": cash["cash_out_total"],
                    "cash_in_count": cash["cash_in_count"],
                    "cash_out_count": cash["cash_out_count"],
                    "activity_refund_count": refund_count,
                    "open_session_count": open_session_count,
                    "show_refund_attention": bool(refund_count),
                    "show_open_sessions": bool(open_session_count),
                    "show_attention": bool(refund_count),
                }
            )

    def _get_product_rows(self):
        self.ensure_one()
        current, _previous, _labels = self._period_windows(self.period or "today")
        orders = self._paid_orders_between(*current)
        return self.env["pos.session"]._avea_products_from_orders(
            orders,
            limit=OVERVIEW_PRODUCT_LIMIT,
        )

    def _populate_product_lines(self):
        ProductLine = self.env["avea.business.overview.product.line"]
        for overview in self:
            if not overview.id:
                continue
            ProductLine.search([("dashboard_id", "=", overview.id)]).unlink()
            rows = overview._get_product_rows()
            if not rows:
                continue
            ProductLine.create(
                [
                    {
                        "dashboard_id": overview.id,
                        "rank": index,
                        "product_id": row["product_id"],
                        "product_name": row["product_name"],
                        "quantity_sold": row["quantity_sold"],
                        "sales_value": row["sales_value"],
                    }
                    for index, row in enumerate(rows, start=1)
                ]
            )
