from datetime import datetime, time
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.tools.misc import format_date

from .reporting_period import (
    PERIOD_CUSTOM,
    PERIOD_LAST_7,
    PERIOD_LAST_30,
    PERIOD_MTD,
    PERIOD_TODAY,
    PERIOD_WTD,
    PERIOD_YTD,
    normalize_period_key,
    resolve_reporting_period,
)


class AveaBusinessPerformanceLine(models.TransientModel):
    _name = "avea.business.performance.line"
    _description = "Business Performance Ranking Line"
    _order = "section, rank, id"

    dashboard_id = fields.Many2one(
        "avea.business.performance",
        string="Performance",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(
        related="dashboard_id.currency_id",
    )
    section = fields.Selection(
        [
            ("top_product", "Top Product"),
            ("top_category", "Top Category"),
            ("profit_product", "Most Profitable Product"),
            ("profit_category", "Most Profitable Category"),
        ],
        required=True,
        readonly=True,
    )
    rank = fields.Integer(
        readonly=True,
    )
    product_id = fields.Many2one(
        "product.product",
        readonly=True,
    )
    category_id = fields.Many2one(
        "product.category",
        readonly=True,
    )
    name = fields.Char(
        string="Name",
        readonly=True,
    )
    quantity_sold = fields.Float(
        string="Qty",
        digits="Product Unit",
        readonly=True,
    )
    revenue_ex_tax = fields.Monetary(
        string="Revenue EX Tax",
        currency_field="currency_id",
        readonly=True,
    )
    gross_profit = fields.Monetary(
        string="Gross Profit",
        currency_field="currency_id",
        readonly=True,
    )


class AveaBusinessPerformance(models.TransientModel):
    _name = "avea.business.performance"
    _description = "Business Performance"
    _rec_name = "period_label"

    period = fields.Selection(
        [
            ("today", "Today"),
            ("wtd", "Week to Date"),
            ("mtd", "Month to Date"),
            ("last_7", "Last 7 Days"),
            ("last_30", "Last 30 Days"),
            ("ytd", "Year to Date"),
            ("custom", "Custom Period"),
        ],
        string="Period",
        default="today",
        required=True,
    )
    date_from = fields.Date(string="From")
    date_to = fields.Date(string="To")
    period_label = fields.Char(
        compute="_compute_period_labels",
    )
    period_range_display = fields.Char(
        compute="_compute_period_labels",
    )
    comparison_label = fields.Char(
        compute="_compute_period_labels",
    )
    comparison_range_display = fields.Char(
        compute="_compute_period_labels",
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )

    line_ids = fields.One2many(
        "avea.business.performance.line",
        "dashboard_id",
        string="Rankings",
        readonly=True,
    )
    top_product_line_ids = fields.One2many(
        "avea.business.performance.line",
        "dashboard_id",
        domain=[("section", "=", "top_product")],
        readonly=True,
    )
    top_category_line_ids = fields.One2many(
        "avea.business.performance.line",
        "dashboard_id",
        domain=[("section", "=", "top_category")],
        readonly=True,
    )
    profit_product_line_ids = fields.One2many(
        "avea.business.performance.line",
        "dashboard_id",
        domain=[("section", "=", "profit_product")],
        readonly=True,
    )
    profit_category_line_ids = fields.One2many(
        "avea.business.performance.line",
        "dashboard_id",
        domain=[("section", "=", "profit_category")],
        readonly=True,
    )

    show_top_products = fields.Boolean(compute="_compute_visibility")
    show_top_categories = fields.Boolean(compute="_compute_visibility")
    show_profit_products = fields.Boolean(compute="_compute_visibility")
    show_profit_categories = fields.Boolean(compute="_compute_visibility")

    @api.model_create_multi
    def create(self, vals_list):
        dashboards = super().create(vals_list)
        dashboards._populate_rankings()
        return dashboards

    def write(self, vals):
        res = super().write(vals)
        if any(key in vals for key in ("period", "date_from", "date_to")):
            self._populate_rankings()
        return res

    @api.depends(
        "line_ids",
        "top_product_line_ids",
        "top_category_line_ids",
        "profit_product_line_ids",
        "profit_category_line_ids",
    )
    def _compute_visibility(self):
        for dashboard in self:
            dashboard.show_top_products = bool(dashboard.top_product_line_ids)
            dashboard.show_top_categories = bool(dashboard.top_category_line_ids)
            dashboard.show_profit_products = bool(dashboard.profit_product_line_ids)
            dashboard.show_profit_categories = bool(dashboard.profit_category_line_ids)

    @api.depends("period", "date_from", "date_to")
    def _compute_period_labels(self):
        for dashboard in self:
            windows = dashboard._period_windows(dashboard.period or PERIOD_TODAY)
            dashboard.period_label = windows["labels"][0]
            dashboard.period_range_display = dashboard._format_day_range(
                *windows["display_current"]
            )
            dashboard.comparison_label = windows["labels"][1]
            dashboard.comparison_range_display = _(
                "Compared with %s"
            ) % dashboard._format_day_range(*windows["display_previous"])

    @api.model
    def action_open_business_performance(
        self, period="today", date_from=None, date_to=None
    ):
        period = normalize_period_key(period)
        vals = {"period": period}
        if period == PERIOD_CUSTOM:
            start, end = self._normalize_custom_dates(date_from, date_to)
            vals["date_from"] = start
            vals["date_to"] = end
        dashboard = self.create(vals)
        return {
            "type": "ir.actions.act_window",
            "name": _("Performance"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": dashboard.id,
            "target": "current",
            "context": {"clear_breadcrumbs": True},
        }

    def action_period_today(self):
        return self.action_open_business_performance(period=PERIOD_TODAY)

    def action_period_wtd(self):
        return self.action_open_business_performance(period=PERIOD_WTD)

    def action_period_mtd(self):
        return self.action_open_business_performance(period=PERIOD_MTD)

    def action_period_last_7(self):
        return self.action_open_business_performance(period=PERIOD_LAST_7)

    def action_period_last_30(self):
        return self.action_open_business_performance(period=PERIOD_LAST_30)

    def action_period_ytd(self):
        return self.action_open_business_performance(period=PERIOD_YTD)

    def action_period_custom(self):
        today = fields.Date.context_today(self)
        return self.action_open_business_performance(
            period=PERIOD_CUSTOM,
            date_from=today.replace(day=1),
            date_to=today,
        )

    def action_apply_custom_period(self):
        self.ensure_one()
        return self.action_open_business_performance(
            period=PERIOD_CUSTOM,
            date_from=self.date_from,
            date_to=self.date_to,
        )

    def action_open_overview(self):
        return self.env["avea.business.overview"].action_open_business_overview()

    def action_refresh(self):
        self.ensure_one()
        return self.action_open_business_performance(
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
        reporting = resolve_reporting_period(
            period=period,
            today=fields.Date.context_today(self),
            custom_from=self.date_from,
            custom_to=self.date_to,
        )
        current = reporting.current
        previous = reporting.comparison
        return {
            "display_current": current,
            "data_current": current,
            "display_previous": previous,
            "data_previous": previous,
            "labels": (_(reporting.label), _(reporting.comparison_label)),
        }

    def _format_day_range(self, day_from, day_to):
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

    def _populate_rankings(self):
        Line = self.env["avea.business.performance.line"]
        PosLine = self.env["pos.order.line"]
        for dashboard in self:
            if not dashboard.id:
                continue
            Line.search([("dashboard_id", "=", dashboard.id)]).unlink()
            windows = dashboard._period_windows(dashboard.period or PERIOD_TODAY)
            orders = dashboard._paid_orders_between(*windows["data_current"])
            rankings = PosLine._avea_performance_rankings(orders)
            rows = []
            section_map = {
                "top_products": ("top_product", "product"),
                "top_categories": ("top_category", "category"),
                "profit_products": ("profit_product", "product"),
                "profit_categories": ("profit_category", "category"),
            }
            for key, (section, kind) in section_map.items():
                for index, row in enumerate(rankings.get(key) or [], start=1):
                    vals = {
                        "dashboard_id": dashboard.id,
                        "section": section,
                        "rank": index,
                        "name": row["label"],
                        "quantity_sold": row["units_positive"],
                        "revenue_ex_tax": row["revenue_ex_tax"],
                        "gross_profit": row["gross_profit"],
                    }
                    if kind == "product":
                        vals["product_id"] = row["record_id"]
                    else:
                        vals["category_id"] = row["record_id"] or False
                    rows.append(vals)
            if rows:
                Line.create(rows)
