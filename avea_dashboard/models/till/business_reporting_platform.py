# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class AveaBusinessReportingPlatformLine(models.TransientModel):
    _name = "avea.business.reporting.platform.line"
    _description = "Business Reporting Sales Platform Line"
    _order = "sales_ex_tax desc, id"

    overview_id = fields.Many2one(
        "avea.business.overview",
        string="Overview",
        ondelete="cascade",
    )
    performance_id = fields.Many2one(
        "avea.business.performance",
        string="Performance",
        ondelete="cascade",
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
        readonly=True,
    )
    platform_id = fields.Many2one(
        "avea.sales.platform",
        string="Platform",
        readonly=True,
    )
    name = fields.Char(string="Platform", readonly=True)
    sales_ex_tax = fields.Monetary(
        string="Sales",
        currency_field="currency_id",
        readonly=True,
    )
    cost_total = fields.Monetary(
        string="COGS",
        currency_field="currency_id",
        readonly=True,
    )
    gross_profit = fields.Monetary(
        string="Gross Profit",
        currency_field="currency_id",
        readonly=True,
    )
    commission = fields.Monetary(
        string="Platform costs",
        currency_field="currency_id",
        readonly=True,
    )
    contribution = fields.Monetary(
        string="After platform costs",
        currency_field="currency_id",
        readonly=True,
    )
    line_count = fields.Integer(string="Sale lines", readonly=True)
    top_product_name = fields.Char(string="Top product", readonly=True)

    @api.depends("overview_id.currency_id", "performance_id.currency_id")
    def _compute_currency_id(self):
        for line in self:
            parent = line.overview_id or line.performance_id
            line.currency_id = parent.currency_id if parent else False

    def action_open_platform_sales(self):
        self.ensure_one()
        if not self.platform_id:
            return False
        action = self.platform_id.action_view_platform_sales()
        parent = self.overview_id or self.performance_id
        if parent:
            windows = parent._period_windows(parent.period or "today")
            day_from, day_to = windows["data_current"]
            start, end = parent._reporting_utc_bounds(day_from, day_to)
            action["domain"] = list(action.get("domain") or []) + [
                ("avea_order_date", ">=", start),
                ("avea_order_date", "<=", end),
            ]
        return action
