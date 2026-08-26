from calendar import monthrange
from datetime import datetime, time, timedelta
from html import escape
from zoneinfo import ZoneInfo

from markupsafe import Markup
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
            ("custom", "Custom Period"),
        ],
        string="Period",
        default="today",
        required=True,
    )
    date_from = fields.Date(string="From")
    date_to = fields.Date(string="To")
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
    sales_vs_previous_display = fields.Char(
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
    show_open_sessions = fields.Boolean(
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

    items_sold_display = fields.Char(
        string="Items Sold",
        compute="_compute_metrics",
    )
    average_items_display = fields.Char(
        string="Average Items per Sale",
        compute="_compute_metrics",
    )
    slowest_day_name = fields.Char(
        string="Slowest Day",
        compute="_compute_metrics",
    )
    slowest_day_sales = fields.Monetary(
        compute="_compute_metrics",
        currency_field="currency_id",
    )
    slowest_day_count = fields.Integer(
        compute="_compute_metrics",
    )
    show_slowest_day = fields.Boolean(
        compute="_compute_metrics",
    )
    refund_total = fields.Monetary(
        string="Refunds",
        compute="_compute_metrics",
        currency_field="currency_id",
    )
    sales_trend_html = fields.Html(
        string="Sales Trend",
        compute="_compute_metrics",
        sanitize=False,
    )
    show_sales_trend = fields.Boolean(
        compute="_compute_metrics",
    )
    sales_sparkline_html = fields.Html(
        string="Sales Sparkline",
        compute="_compute_metrics",
        sanitize=False,
    )
    show_sales_sparkline = fields.Boolean(
        compute="_compute_metrics",
    )
    trading_pattern_html = fields.Html(
        string="Busy Times",
        compute="_compute_metrics",
        sanitize=False,
    )
    show_trading_pattern = fields.Boolean(
        compute="_compute_metrics",
    )

    @api.model_create_multi
    def create(self, vals_list):
        overviews = super().create(vals_list)
        overviews._populate_product_lines()
        return overviews

    def write(self, vals):
        res = super().write(vals)
        if any(key in vals for key in ("period", "date_from", "date_to")):
            self._populate_product_lines()
        return res

    @api.depends("product_line_ids")
    def _compute_show_products(self):
        for overview in self:
            overview.show_products = bool(overview.product_line_ids)

    @api.model
    def action_open_business_overview(
        self, period="today", date_from=None, date_to=None
    ):
        if period not in ("today", "week", "month", "custom"):
            period = "today"
        vals = {"period": period}
        if period == "custom":
            start, end = self._normalize_custom_dates(date_from, date_to)
            vals["date_from"] = start
            vals["date_to"] = end
        overview = self.create(vals)
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

    def action_period_custom(self):
        today = fields.Date.context_today(self)
        return self.action_open_business_overview(
            period="custom",
            date_from=today.replace(day=1),
            date_to=today,
        )

    def action_apply_custom_period(self):
        self.ensure_one()
        return self.action_open_business_overview(
            period="custom",
            date_from=self.date_from,
            date_to=self.date_to,
        )

    def action_open_sessions(self):
        return self.env["avea.till.session.dashboard"].action_open_session_dashboard()

    def action_open_cash(self):
        return self.env["avea.till.dashboard"].action_open_dashboard()

    def action_refresh(self):
        self.ensure_one()
        return self.action_open_business_overview(
            period=self.period,
            date_from=self.date_from,
            date_to=self.date_to,
        )

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

    @api.model
    def _normalize_custom_dates(self, date_from=None, date_to=None):
        today = fields.Date.context_today(self)
        start = date_from or today.replace(day=1)
        end = date_to or today
        if start > end:
            start, end = end, start
        return start, end

    def _period_windows(self, period):
        today = fields.Date.context_today(self)
        if period == "custom":
            date_from, date_to = self._normalize_custom_dates(
                self.date_from, self.date_to
            )
            duration = (date_to - date_from).days + 1
            prev_end = date_from - timedelta(days=1)
            prev_start = prev_end - timedelta(days=duration - 1)
            return {
                "display_current": (date_from, date_to),
                "data_current": (date_from, date_to),
                "display_previous": (prev_start, prev_end),
                "data_previous": (prev_start, prev_end),
                "labels": (_("Custom Period"), _("Previous period")),
                "show_through_today": False,
                "today": today,
            }
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

    def _chart_period_days(self, period, windows):
        """Calendar span for Trading Pattern. KPI totals keep ``data_current``."""
        today = windows["today"]
        if period == "week":
            return windows["display_current"]
        if period == "month":
            month_start = today.replace(day=1)
            last_day = monthrange(month_start.year, month_start.month)[1]
            return (month_start, month_start.replace(day=last_day))
        if period == "custom":
            return windows["display_current"]
        return (today, today)

    def _is_single_day_period(self, period, windows):
        if period == "today":
            return True
        if period == "custom":
            day_from, day_to = windows["display_current"]
            return day_from == day_to
        return False

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

    def _format_busy_date(self, day):
        return format_date(self.env, day, date_format="EEEE, d MMMM")

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
        hour_date_buckets = {}
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
            hour_day_entry = hour_date_buckets.setdefault(hour, {}).setdefault(
                day, [0.0, 0, day.toordinal()]
            )
            hour_day_entry[0] += amount
            hour_day_entry[1] += 1

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
                    "day_name": self._format_busy_date(day),
                    "day_sales": sales,
                    "day_count": count,
                }
            )
        if busiest_hour:
            hour, (sales, count, _sort) = busiest_hour
            hour_range = self._format_hour_range(hour)
            hour_day = self._pick_busiest_bucket(hour_date_buckets.get(hour) or {})
            if hour_day:
                time_display = _("%s on %s") % (
                    hour_range,
                    self._format_busy_date(hour_day[0]),
                )
            else:
                time_display = hour_range
            result.update(
                {
                    "time_display": time_display,
                    "time_sales": sales,
                    "time_count": count,
                }
            )
        return result

    def _format_money(self, amount):
        return self.env.company.currency_id.format(amount)

    def _format_qty_display(self, qty):
        rounded = round(float(qty or 0.0), 2)
        if abs(rounded - round(rounded)) < 0.005:
            return str(int(round(rounded)))
        return f"{rounded:.1f}"

    def _day_rows_from_orders(self, orders, day_from, day_to):
        buckets = {}
        for order in orders:
            local_dt = self._local_order_datetime(order)
            if not local_dt:
                continue
            day = local_dt.date()
            entry = buckets.setdefault(day, [0.0, 0])
            entry[0] += order.amount_total
            entry[1] += 1
        rows = []
        current = day_from
        while current <= day_to:
            sales, count = buckets.get(current, [0.0, 0])
            rows.append((current, sales, count))
            current += timedelta(days=1)
        return rows

    def _hours_from_orders(self, orders):
        buckets = {}
        for order in orders:
            local_dt = self._local_order_datetime(order)
            if not local_dt:
                continue
            entry = buckets.setdefault(local_dt.hour, [0.0, 0])
            entry[0] += order.amount_total
            entry[1] += 1
        return buckets

    def _days_from_orders(self, orders):
        buckets = {}
        for order in orders:
            local_dt = self._local_order_datetime(order)
            if not local_dt:
                continue
            entry = buckets.setdefault(local_dt.date(), [0.0, 0])
            entry[0] += order.amount_total
            entry[1] += 1
        return buckets

    def _pattern_cell_class(self, sales, max_sales, extra=""):
        if max_sales <= 0 or sales <= 0:
            classes = "o_avea_pattern_cell o_avea_pattern_cell--empty"
        else:
            ratio = sales / max_sales
            if ratio >= 0.75:
                tone = "hot"
            elif ratio >= 0.4:
                tone = "warm"
            elif ratio >= 0.15:
                tone = "mild"
            else:
                tone = "low"
            classes = f"o_avea_pattern_cell o_avea_pattern_cell--{tone}"
        if extra:
            classes = f"{classes} {extra}"
        return classes

    def _build_sales_trend_html(self, day_rows):
        if not day_rows:
            return False
        max_sales = max((sales for _day, sales, _count in day_rows), default=0.0)
        parts = ['<div class="o_avea_trend">']
        for day, sales, count in day_rows:
            label = escape(format_date(self.env, day, date_format="EEE d"))
            amount = escape(self._format_money(sales))
            width = 0
            if max_sales > 0 and sales > 0:
                width = max(6, int(round((sales / max_sales) * 100)))
            parts.append(
                '<div class="o_avea_trend_row">'
                f'<span class="o_avea_trend_label">{label}</span>'
                '<span class="o_avea_trend_track">'
                f'<span class="o_avea_trend_bar" style="width: {width}%"></span>'
                "</span>"
                f'<span class="o_avea_trend_amount">{amount}</span>'
                "</div>"
            )
        parts.append("</div>")
        return Markup("".join(parts))

    def _sparkline_values(self, day_rows, orders=None):
        """Same sales totals as Sales Trend; hours only when the trend is one day."""
        values = [float(sales) for _day, sales, _count in (day_rows or [])]
        if len(values) > 1:
            return values
        hours = self._hours_from_orders(orders) if orders else {}
        if hours:
            columns = self._pattern_hour_columns(hours)
            return [float(hours.get(hour, (0.0, 0))[0]) for hour in columns]
        if values:
            return [0.0, values[0]]
        return []

    def _build_sales_sparkline_html(self, day_rows, orders=None):
        values = self._sparkline_values(day_rows, orders)
        if not values or all(value <= 0 for value in values):
            return False
        width, height, pad = 160.0, 40.0, 2.0
        max_value = max(values)
        min_value = min(values)
        span = max_value - min_value
        count = len(values)

        def point_x(index):
            if count == 1:
                return width / 2.0
            return pad + (width - 2.0 * pad) * index / (count - 1)

        def point_y(value):
            if span <= 0:
                return height / 2.0
            return pad + (height - 2.0 * pad) * (1.0 - (value - min_value) / span)

        points = [(point_x(index), point_y(value)) for index, value in enumerate(values)]
        line = " ".join(
            f"{'M' if index == 0 else 'L'}{pos_x:.2f} {pos_y:.2f}"
            for index, (pos_x, pos_y) in enumerate(points)
        )
        first_x, last_x = points[0][0], points[-1][0]
        area = (
            f"{line} L{last_x:.2f} {height - pad:.2f} "
            f"L{first_x:.2f} {height - pad:.2f} Z"
        )
        return Markup(
            '<div class="o_avea_sparkline" aria-hidden="true">'
            f'<svg viewBox="0 0 {int(width)} {int(height)}" preserveAspectRatio="none">'
            f'<path class="o_avea_sparkline_area" d="{area}"/>'
            f'<path class="o_avea_sparkline_line" d="{line}" fill="none"/>'
            "</svg></div>"
        )

    def _pattern_hour_columns(self, hours):
        """Display columns for the today heatmap. Does not change totals."""
        start = min(hours)
        end = max(hours)
        while end - start + 1 < 8:
            expanded = False
            if start > 0:
                start -= 1
                expanded = True
            if end - start + 1 >= 8:
                break
            if end < 23:
                end += 1
                expanded = True
            if not expanded:
                break
        return list(range(start, end + 1))

    def _pattern_cell_title(self, label, sales, count):
        return escape(
            _("%(label)s · %(amount)s · %(count)s")
            % {
                "label": label,
                "amount": self._format_money(sales),
                "count": _("%s transactions") % count,
            }
        )

    def _pattern_legend_html(self):
        return (
            '<div class="o_avea_pattern_legend">'
            f'<span class="o_avea_pattern_legend_label">{escape(_("Least activity →"))}</span>'
            '<span class="o_avea_pattern_legend_scale" aria-hidden="true">'
            '<span class="o_avea_pattern_swatch o_avea_pattern_cell--empty"></span>'
            '<span class="o_avea_pattern_swatch o_avea_pattern_cell--low"></span>'
            '<span class="o_avea_pattern_swatch o_avea_pattern_cell--mild"></span>'
            '<span class="o_avea_pattern_swatch o_avea_pattern_cell--warm"></span>'
            '<span class="o_avea_pattern_swatch o_avea_pattern_cell--hot"></span>'
            "</span>"
            f'<span class="o_avea_pattern_legend_label">{escape(_("Most activity"))}</span>'
            "</div>"
        )

    def _pattern_weekday_heads(self, monday):
        parts = []
        for weekday in range(7):
            label = escape(
                format_date(
                    self.env,
                    monday + timedelta(days=weekday),
                    date_format="EEE",
                )
            )
            parts.append(f'<span class="o_avea_pattern_head">{label}</span>')
        return parts

    def _pattern_day_cell(self, day, sales, count, max_sales):
        cell_class = self._pattern_cell_class(sales, max_sales)
        title = self._pattern_cell_title(
            self._format_busy_date(day), sales, count
        )
        number = escape(format_date(self.env, day, date_format="d"))
        return (
            f'<span class="{cell_class}" title="{title}">'
            f'<span class="o_avea_pattern_date">{number}</span>'
            "</span>"
        )

    def _build_pattern_hours_html(self, hour_buckets):
        hours = self._pattern_hour_columns(hour_buckets)
        max_sales = max(sales for sales, _count in hour_buckets.values())
        col_count = len(hours)
        parts = [
            '<div class="o_avea_pattern o_avea_pattern--hours">'
            f'<div class="o_avea_pattern_grid o_avea_pattern_grid--hours o_avea_pattern_grid--cols-{col_count}">'
        ]
        for hour in hours:
            parts.append(f'<span class="o_avea_pattern_head o_avea_pattern_hour">{hour:02d}</span>')
        for hour in hours:
            sales, count = hour_buckets.get(hour, (0.0, 0))
            cell_class = self._pattern_cell_class(sales, max_sales)
            title = self._pattern_cell_title(
                self._format_hour_range(hour), sales, count
            )
            parts.append(f'<span class="{cell_class}" title="{title}"></span>')
        parts.append("</div>")
        parts.append(self._pattern_legend_html())
        parts.append("</div>")
        return Markup("".join(parts))

    def _build_pattern_week_html(self, day_buckets, week_start):
        days = [week_start + timedelta(days=offset) for offset in range(7)]
        max_sales = max(
            (day_buckets.get(day, (0.0, 0))[0] for day in days),
            default=0.0,
        )
        parts = [
            '<div class="o_avea_pattern o_avea_pattern--week">'
            '<div class="o_avea_pattern_grid o_avea_pattern_grid--week">'
        ]
        parts.extend(self._pattern_weekday_heads(week_start))
        for day in days:
            sales, count = day_buckets.get(day, (0.0, 0))
            parts.append(self._pattern_day_cell(day, sales, count, max_sales))
        parts.append("</div>")
        parts.append(self._pattern_legend_html())
        parts.append("</div>")
        return Markup("".join(parts))

    def _build_pattern_month_html(self, day_buckets, month_start, month_end):
        max_sales = max(
            (sales for sales, _count in day_buckets.values()),
            default=0.0,
        )
        grid_start = month_start - timedelta(days=month_start.weekday())
        grid_end = month_end + timedelta(days=(6 - month_end.weekday()))
        parts = [
            '<div class="o_avea_pattern o_avea_pattern--month">'
            '<div class="o_avea_pattern_grid o_avea_pattern_grid--month">'
        ]
        parts.extend(self._pattern_weekday_heads(grid_start))
        current = grid_start
        while current <= grid_end:
            if current < month_start or current > month_end:
                parts.append(
                    '<span class="o_avea_pattern_cell o_avea_pattern_cell--out"></span>'
                )
            else:
                sales, count = day_buckets.get(current, (0.0, 0))
                parts.append(
                    self._pattern_day_cell(current, sales, count, max_sales)
                )
            current += timedelta(days=1)
        parts.append("</div>")
        parts.append(self._pattern_legend_html())
        parts.append("</div>")
        return Markup("".join(parts))

    def _build_trading_pattern_html(self, period, orders, windows):
        if not orders:
            return False
        if period == "today":
            hour_buckets = self._hours_from_orders(orders)
            if not hour_buckets:
                return False
            return self._build_pattern_hours_html(hour_buckets)
        if period == "custom":
            day_from, day_to = windows["display_current"]
            if day_from == day_to:
                hour_buckets = self._hours_from_orders(orders)
                if not hour_buckets:
                    return False
                return self._build_pattern_hours_html(hour_buckets)
            day_buckets = self._days_from_orders(orders)
            if not day_buckets:
                return False
            return self._build_pattern_month_html(day_buckets, day_from, day_to)
        day_buckets = self._days_from_orders(orders)
        if not day_buckets:
            return False
        if period == "week":
            week_start, _week_end = windows["display_current"]
            return self._build_pattern_week_html(day_buckets, week_start)
        month_start, month_end = self._chart_period_days(period, windows)
        return self._build_pattern_month_html(day_buckets, month_start, month_end)

    @api.depends("period", "date_from", "date_to")
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
            refund_total = activity.get("refund_amount", 0.0)
            items_sold = activity["items_sold"]
            average_items = (
                items_sold / sales["order_count"] if sales["order_count"] else 0.0
            )
            day_from, day_to = windows["data_current"]
            day_rows = overview._day_rows_from_orders(
                current_orders, day_from, day_to
            )
            days_with_sales = [
                (day, sales_amt, count)
                for day, sales_amt, count in day_rows
                if count > 0
            ]
            slowest = (
                min(days_with_sales, key=lambda row: (row[1], row[2], row[0].toordinal()))
                if len(days_with_sales) >= 2
                else False
            )
            chart_from, chart_to = overview._chart_period_days(period, windows)
            chart_orders = overview._paid_orders_between(chart_from, chart_to)
            period_range = overview._format_day_range(*windows["display_current"])
            comparison_range = overview._format_day_range(*windows["display_previous"])
            single_day = overview._is_single_day_period(period, windows)
            show_busiest_day = (not single_day) and bool(busy["day_name"])
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
                    "sales_vs_previous_display": _("%s vs %s")
                    % (
                        overview._format_money(sales["total_sales"]),
                        overview._format_money(previous_sales["total_sales"]),
                    ),
                    "cash_sales": sales["cash_sales"],
                    "card_sales": sales["card_sales"],
                    "other_payments": sales["other_payments"],
                    "cash_in_total": cash["cash_in_total"],
                    "cash_out_total": cash["cash_out_total"],
                    "cash_in_count": cash["cash_in_count"],
                    "cash_out_count": cash["cash_out_count"],
                    "activity_refund_count": refund_count,
                    "open_session_count": open_session_count,
                    "show_open_sessions": bool(open_session_count),
                    "busiest_day_name": busy["day_name"] or "",
                    "busiest_day_sales": busy["day_sales"],
                    "busiest_day_count": busy["day_count"],
                    "show_busiest_day": show_busiest_day,
                    "busiest_time_display": busy["time_display"] or "",
                    "busiest_time_sales": busy["time_sales"],
                    "busiest_time_count": busy["time_count"],
                    "show_busiest_time": show_busiest_time,
                    "show_busy_times": show_busiest_day or show_busiest_time,
                    "items_sold_display": overview._format_qty_display(items_sold),
                    "average_items_display": overview._format_qty_display(
                        average_items
                    ),
                    "slowest_day_name": (
                        overview._format_busy_date(slowest[0]) if slowest else ""
                    ),
                    "slowest_day_sales": slowest[1] if slowest else 0.0,
                    "slowest_day_count": slowest[2] if slowest else 0,
                    "show_slowest_day": bool(slowest) and not single_day,
                    "refund_total": refund_total,
                    "sales_trend_html": overview._build_sales_trend_html(day_rows),
                    "show_sales_trend": bool(days_with_sales),
                    "sales_sparkline_html": overview._build_sales_sparkline_html(
                        day_rows, current_orders
                    ),
                    "show_sales_sparkline": bool(days_with_sales),
                    "trading_pattern_html": overview._build_trading_pattern_html(
                        period, chart_orders, windows
                    ),
                    "show_trading_pattern": bool(chart_orders),
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
