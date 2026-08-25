from calendar import monthrange
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from odoo import Command, _, api, fields, models
from odoo.tools.misc import format_date

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
    period_range_display = fields.Char(
        string="Period Dates",
        compute="_compute_metrics",
    )
    comparison_label = fields.Char(
        string="Compared With",
        compute="_compute_metrics",
    )
    comparison_range_display = fields.Char(
        string="Comparison Dates",
        compute="_compute_metrics",
    )
    through_today_display = fields.Char(
        string="Through Today",
        compute="_compute_metrics",
    )
    show_through_today = fields.Boolean(
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

    busiest_day_name = fields.Char(
        string="Busiest Day",
        compute="_compute_metrics",
    )
    busiest_day_sales = fields.Monetary(
        compute="_compute_metrics",
        currency_field="currency_id",
    )
    busiest_day_count = fields.Integer(
        compute="_compute_metrics",
    )
    show_busiest_day = fields.Boolean(
        compute="_compute_metrics",
    )
    busiest_time_display = fields.Char(
        string="Busiest Time",
        compute="_compute_metrics",
    )
    busiest_time_sales = fields.Monetary(
        compute="_compute_metrics",
        currency_field="currency_id",
    )
    busiest_time_count = fields.Integer(
        compute="_compute_metrics",
    )
    show_busiest_time = fields.Boolean(
        compute="_compute_metrics",
    )
    show_busy_times = fields.Boolean(
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
            week_end = week_start + timedelta(days=6)
            prev_start = week_start - timedelta(days=7)
            prev_end = week_end - timedelta(days=7)
            return {
                "display_current": (week_start, week_end),
                "data_current": (week_start, today),
                "display_previous": (prev_start, prev_end),
                "data_previous": (prev_start, prev_end),
                "labels": (_("This Week"), _("Previous week")),
                "show_through_today": today < week_end,
                "today": today,
            }
        if period == "month":
            month_start = today.replace(day=1)
            if month_start.month == 1:
                prev_start = month_start.replace(year=month_start.year - 1, month=12)
            else:
                prev_start = month_start.replace(month=month_start.month - 1)
            prev_last_day = monthrange(prev_start.year, prev_start.month)[1]
            prev_end = prev_start.replace(day=min(today.day, prev_last_day))
            current = (month_start, today)
            previous = (prev_start, prev_end)
            return {
                "display_current": current,
                "data_current": current,
                "display_previous": previous,
                "data_previous": previous,
                "labels": (_("This Month"), _("Previous month")),
                "show_through_today": False,
                "today": today,
            }
        yesterday = today - timedelta(days=1)
        current = (today, today)
        previous = (yesterday, yesterday)
        return {
            "display_current": current,
            "data_current": current,
            "display_previous": previous,
            "data_previous": previous,
            "labels": (_("Today"), _("Yesterday")),
            "show_through_today": False,
            "today": today,
        }

    def _format_day_range(self, day_from, day_to):
        """Readable date range in the user's language, e.g. 18–25 August 2026."""
        if day_from == day_to:
            return format_date(self.env, day_from, date_format="d MMMM y")
        end = format_date(self.env, day_to, date_format="d MMMM y")
        same_month = day_from.month == day_to.month and day_from.year == day_to.year
        if same_month:
            start_day = format_date(self.env, day_from, date_format="d")
            return f"{start_day}–{end}"
        if day_from.year == day_to.year:
            start = format_date(self.env, day_from, date_format="d MMMM")
            return f"{start}–{end}"
        start = format_date(self.env, day_from, date_format="d MMMM y")
        return f"{start}–{end}"

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

    def _local_order_datetime(self, order):
        if not order.date_order:
            return False
        return order.date_order.replace(tzinfo=ZoneInfo("UTC")).astimezone(
            self._timezone()
        )

    def _format_hour_range(self, hour):
        start = f"{hour:02d}:00"
        end = f"{(hour + 1) % 24:02d}:00"
        return f"{start} – {end}"

    def _pick_busiest_bucket(self, buckets):
        if not buckets:
            return False
        return max(
            buckets.items(),
            key=lambda item: (item[1][0], item[1][1], -item[1][2]),
        )

    def _busy_stats_from_orders(self, orders):
        day_buckets = {}
        hour_buckets = {}
        for order in orders:
            local_dt = self._local_order_datetime(order)
            if not local_dt:
                continue
            amount = order.amount_total
            day = local_dt.date()
            hour = local_dt.hour
            day_entry = day_buckets.setdefault(day, [0.0, 0, day.toordinal()])
            day_entry[0] += amount
            day_entry[1] += 1
            hour_entry = hour_buckets.setdefault(hour, [0.0, 0, hour])
            hour_entry[0] += amount
            hour_entry[1] += 1

        busiest_day = self._pick_busiest_bucket(day_buckets)
        busiest_hour = self._pick_busiest_bucket(hour_buckets)
        result = {
            "day_name": False,
            "day_sales": 0.0,
            "day_count": 0,
            "time_display": False,
            "time_sales": 0.0,
            "time_count": 0,
        }
        if busiest_day:
            day, (sales, count, _sort) = busiest_day
            result.update(
                {
                    "day_name": format_date(self.env, day, date_format="EEEE"),
                    "day_sales": sales,
                    "day_count": count,
                }
            )
        if busiest_hour:
            hour, (sales, count, _sort) = busiest_hour
            result.update(
                {
                    "time_display": self._format_hour_range(hour),
                    "time_sales": sales,
                    "time_count": count,
                }
            )
        return result

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
            windows = overview._period_windows(period)
            current_orders = overview._paid_orders_between(*windows["data_current"])
            previous_orders = overview._paid_orders_between(*windows["data_previous"])
            sales = Session._avea_sales_summary_from_orders(current_orders)
            previous_sales = Session._avea_sales_summary_from_orders(previous_orders)
            activity = Session._avea_activity_from_orders(current_orders)
            cash = overview._cash_activity_between(*windows["data_current"])
            change_display, tone, delta = overview._change_display(
                sales["total_sales"],
                previous_sales["total_sales"],
            )
            busy = overview._busy_stats_from_orders(current_orders)
            refund_count = activity["refund_count"]
            period_range = overview._format_day_range(*windows["display_current"])
            comparison_range = overview._format_day_range(*windows["display_previous"])
            show_busiest_day = period != "today" and bool(busy["day_name"])
            show_busiest_time = bool(busy["time_display"])
            overview.update(
                {
                    "period_label": windows["labels"][0],
                    "period_range_display": period_range,
                    "comparison_label": windows["labels"][1],
                    "comparison_range_display": _(
                        "Compared with %s"
                    )
                    % comparison_range,
                    "through_today_display": _(
                        "Figures through %s"
                    )
                    % format_date(
                        overview.env,
                        windows["today"],
                        date_format="d MMMM y",
                    ),
                    "show_through_today": windows["show_through_today"],
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
                    "busiest_day_name": busy["day_name"] or "",
                    "busiest_day_sales": busy["day_sales"],
                    "busiest_day_count": busy["day_count"],
                    "show_busiest_day": show_busiest_day,
                    "busiest_time_display": busy["time_display"] or "",
                    "busiest_time_sales": busy["time_sales"],
                    "busiest_time_count": busy["time_count"],
                    "show_busiest_time": show_busiest_time,
                    "show_busy_times": show_busiest_day or show_busiest_time,
                }
            )

    def _get_product_rows(self):
        self.ensure_one()
        windows = self._period_windows(self.period or "today")
        orders = self._paid_orders_between(*windows["data_current"])
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
