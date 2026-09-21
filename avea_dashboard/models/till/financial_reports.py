from odoo import _, api, fields, models

from .reporting_period import PERIOD_CUSTOM, normalize_period_key
from .reporting_workspace import AveaReportingWorkspaceMixin


class AveaProfitReportLine(models.TransientModel):
    _name = "avea.profit.report.line"
    _description = "Profit Report Line"
    _order = "order_date desc, id desc"

    report_id = fields.Many2one(
        "avea.profit.report",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(related="report_id.currency_id")
    pos_line_id = fields.Many2one("pos.order.line", readonly=True)
    order_date = fields.Datetime(related="pos_line_id.avea_order_date", readonly=True)
    order_date_label = fields.Char(string="Date / Time", readonly=True)
    order_reference = fields.Char(string="Receipt", readonly=True)
    product_display = fields.Char(string="Product", readonly=True)
    quantity = fields.Float(string="Qty", digits="Product Unit", readonly=True)
    sales = fields.Monetary(string="Sales", currency_field="currency_id", readonly=True)
    cost_total = fields.Monetary(string="COGS", currency_field="currency_id", readonly=True)
    gross_profit = fields.Monetary(
        string="Gross Profit",
        currency_field="currency_id",
        readonly=True,
    )
    gross_margin_percent = fields.Float(
        string="Gross Margin %",
        digits=(16, 1),
        readonly=True,
    )


class AveaProfitReport(models.TransientModel):
    _name = "avea.profit.report"
    _description = "Profit Report"
    _inherit = ["avea.reporting.workspace.mixin"]

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
        required=True,
        readonly=True,
    )
    date_from = fields.Date(readonly=True)
    date_to = fields.Date(readonly=True)
    period_label = fields.Char(readonly=True)
    period_range_display = fields.Char(readonly=True)
    source_model = fields.Char(readonly=True)
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )
    sales_ex_tax = fields.Monetary(
        string="Sales",
        currency_field="currency_id",
        readonly=True,
    )
    cost_of_goods_sold = fields.Monetary(
        string="Cost of Goods Sold",
        currency_field="currency_id",
        readonly=True,
    )
    gross_profit = fields.Monetary(
        string="Gross Profit",
        currency_field="currency_id",
        readonly=True,
    )
    gross_margin_percent = fields.Float(
        string="Gross Margin %",
        digits=(16, 1),
        readonly=True,
    )
    line_ids = fields.One2many(
        "avea.profit.report.line",
        "report_id",
        string="Transactions",
        readonly=True,
    )

    @api.model
    def action_open_for_workspace(
        self,
        *,
        period,
        date_from=None,
        date_to=None,
        source_model=None,
    ):
        period = normalize_period_key(period)
        if period == PERIOD_CUSTOM:
            date_from, date_to = self._reporting_normalize_custom_dates(
                date_from, date_to
            )
        else:
            date_from = date_to = False
        context = self._reporting_period_context(
            period=period,
            date_from=date_from,
            date_to=date_to,
        )
        windows = context["windows"]
        financial = context["financial"]
        report = self.create(
            {
                "period": period,
                "date_from": date_from,
                "date_to": date_to,
                "period_label": windows["period_label"],
                "period_range_display": self._reporting_format_day_range(
                    *windows["display_current"]
                ),
                "source_model": source_model,
                "sales_ex_tax": financial["revenue_ex_tax"],
                "cost_of_goods_sold": financial["cost_total"],
                "gross_profit": financial["gross_profit"],
                "gross_margin_percent": financial["gross_margin_percent"],
            }
        )
        rows = self.env["pos.order.line"]._avea_profit_report_rows(context["orders"])
        if rows:
            self.env["avea.profit.report.line"].create(
                [{"report_id": report.id, **row} for row in rows]
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Profit Report"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": report.id,
            "target": "current",
        }

    def action_back(self):
        self.ensure_one()
        if self.source_model == "avea.business.performance":
            return self.env["avea.business.performance"].action_open_business_performance(
                period=self.period,
                date_from=self.date_from,
                date_to=self.date_to,
            )
        return self.env["avea.business.overview"].action_open_business_overview(
            period=self.period,
            date_from=self.date_from,
            date_to=self.date_to,
        )


class AveaDiscountReportLine(models.TransientModel):
    _name = "avea.discount.report.line"
    _description = "Discount Report Line"
    _order = "order_date desc, id desc"

    report_id = fields.Many2one(
        "avea.discount.report",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(related="report_id.currency_id")
    pos_line_id = fields.Many2one("pos.order.line", readonly=True)
    order_date = fields.Datetime(related="pos_line_id.avea_order_date", readonly=True)
    order_date_label = fields.Char(string="Date / Time", readonly=True)
    order_reference = fields.Char(string="Receipt", readonly=True)
    product_display = fields.Char(string="Product", readonly=True)
    quantity = fields.Float(string="Qty", digits="Product Unit", readonly=True)
    retail_unit_ex_tax = fields.Monetary(
        string="Retail Price",
        currency_field="currency_id",
        readonly=True,
    )
    actual_unit_ex_tax = fields.Monetary(
        string="Actual Price",
        currency_field="currency_id",
        readonly=True,
    )
    discount_amount = fields.Monetary(
        string="Discount",
        currency_field="currency_id",
        readonly=True,
    )
    discount_reason = fields.Char(string="Reason", readonly=True)


class AveaDiscountReport(models.TransientModel):
    _name = "avea.discount.report"
    _description = "Discount Report"
    _inherit = ["avea.reporting.workspace.mixin"]

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
        required=True,
        readonly=True,
    )
    date_from = fields.Date(readonly=True)
    date_to = fields.Date(readonly=True)
    period_label = fields.Char(readonly=True)
    period_range_display = fields.Char(readonly=True)
    source_model = fields.Char(readonly=True)
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )
    discounts_given = fields.Monetary(
        string="Total Discounts Given",
        currency_field="currency_id",
        readonly=True,
    )
    line_ids = fields.One2many(
        "avea.discount.report.line",
        "report_id",
        string="Discounts",
        readonly=True,
    )

    @api.model
    def action_open_for_workspace(
        self,
        *,
        period,
        date_from=None,
        date_to=None,
        source_model=None,
    ):
        period = normalize_period_key(period)
        if period == PERIOD_CUSTOM:
            date_from, date_to = self._reporting_normalize_custom_dates(
                date_from, date_to
            )
        else:
            date_from = date_to = False
        context = self._reporting_period_context(
            period=period,
            date_from=date_from,
            date_to=date_to,
        )
        windows = context["windows"]
        financial = context["financial"]
        report = self.create(
            {
                "period": period,
                "date_from": date_from,
                "date_to": date_to,
                "period_label": windows["period_label"],
                "period_range_display": self._reporting_format_day_range(
                    *windows["display_current"]
                ),
                "source_model": source_model,
                "discounts_given": financial["discounts_given"],
            }
        )
        rows = self.env["pos.order.line"]._avea_discount_report_rows(context["orders"])
        if rows:
            self.env["avea.discount.report.line"].create(
                [{"report_id": report.id, **row} for row in rows]
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Discount Report"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": report.id,
            "target": "current",
        }

    def action_back(self):
        self.ensure_one()
        if self.source_model == "avea.business.performance":
            return self.env["avea.business.performance"].action_open_business_performance(
                period=self.period,
                date_from=self.date_from,
                date_to=self.date_to,
            )
        return self.env["avea.business.overview"].action_open_business_overview(
            period=self.period,
            date_from=self.date_from,
            date_to=self.date_to,
        )
