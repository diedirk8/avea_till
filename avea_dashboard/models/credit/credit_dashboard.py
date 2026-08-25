from datetime import datetime, time

from odoo import _, api, fields, models

RECENT_ACTIVITY_LIMIT = 10
ATTENTION_CUSTOMER_LIMIT = 10


class AveaCreditDashboardReasonLine(models.TransientModel):
    _name = "avea.credit.dashboard.reason.line"
    _description = "Customer Credit Dashboard Reason Summary Line"
    _order = "reason_id"

    dashboard_id = fields.Many2one(
        "avea.credit.dashboard",
        string="Dashboard",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(
        related="dashboard_id.currency_id",
    )
    reason_id = fields.Many2one(
        "avea.credit.reason",
        string="Reason",
        required=True,
        readonly=True,
    )
    transaction_count = fields.Integer(
        string="Number of Transactions",
        readonly=True,
    )
    total_amount = fields.Monetary(
        string="Total Amount",
        currency_field="currency_id",
        readonly=True,
    )


class AveaCreditDashboard(models.TransientModel):
    _name = "avea.credit.dashboard"
    _description = "Customer Credit Dashboard"
    _rec_name = "name"

    name = fields.Char(
        string="Title",
        default=lambda self: _("Customer Credit Dashboard"),
        required=True,
    )

    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )
    outstanding_store_credit = fields.Monetary(
        string="Outstanding Store Credit",
        compute="_compute_dashboard_metrics",
        currency_field="currency_id",
    )
    credit_issued_today = fields.Monetary(
        string="Credit Issued Today",
        compute="_compute_dashboard_metrics",
        currency_field="currency_id",
    )
    credit_redeemed_today = fields.Monetary(
        string="Credit Redeemed Today",
        compute="_compute_dashboard_metrics",
        currency_field="currency_id",
    )
    outstanding_customers = fields.Integer(
        string="Outstanding Customers",
        compute="_compute_dashboard_metrics",
    )
    transactions_today = fields.Integer(
        string="Transactions Today",
        compute="_compute_dashboard_metrics",
    )
    average_customer_balance = fields.Monetary(
        string="Average Customer Balance",
        compute="_compute_dashboard_metrics",
        currency_field="currency_id",
    )
    recent_entry_ids = fields.Many2many(
        "avea.credit.ledger.entry",
        string="Recent Activity",
        compute="_compute_recent_entries",
    )
    reason_line_ids = fields.One2many(
        "avea.credit.dashboard.reason.line",
        "dashboard_id",
        string="Credit by Reason",
        readonly=True,
    )
    attention_partner_ids = fields.Many2many(
        "res.partner",
        string="Customers Requiring Attention",
        compute="_compute_attention_partners",
    )

    @api.model_create_multi
    def create(self, vals_list):
        dashboards = super().create(vals_list)
        dashboards._populate_reason_lines()
        return dashboards

    @api.model
    def action_open_credit_dashboard(self):
        dashboard = self.create({})
        return {
            "type": "ir.actions.act_window",
            "name": _("Customer Credit Dashboard"),
            "res_model": "avea.credit.dashboard",
            "view_mode": "form",
            "res_id": dashboard.id,
            "view_id": self.env.ref("avea_till.view_avea_credit_dashboard_form").id,
            "target": "current",
        }

    def _populate_reason_lines(self):
        Ledger = self.env["avea.credit.ledger.entry"]
        ReasonLine = self.env["avea.credit.dashboard.reason.line"]
        for dashboard in self:
            ReasonLine.search([("dashboard_id", "=", dashboard.id)]).unlink()
            groups = Ledger.read_group(
                dashboard._get_company_ledger_domain([("state", "=", "posted")]),
                ["amount:sum"],
                ["reason_id"],
            )
            ReasonLine.create(
                [
                    {
                        "dashboard_id": dashboard.id,
                        "reason_id": group["reason_id"][0],
                        "transaction_count": group["reason_id_count"],
                        "total_amount": group["amount"],
                    }
                    for group in groups
                    if group.get("reason_id")
                ]
            )

    def _get_company_ledger_domain(self, extra_domain=None):
        domain = [("company_id", "=", self.env.company.id)]
        if extra_domain:
            domain.extend(extra_domain)
        return domain

    def _get_today_domain(self):
        today = fields.Date.context_today(self)
        start = datetime.combine(today, time.min)
        end = datetime.combine(today, time.max)
        return [
            ("transaction_date", ">=", fields.Datetime.to_string(start)),
            ("transaction_date", "<=", fields.Datetime.to_string(end)),
        ]

    @api.depends("currency_id")
    def _compute_dashboard_metrics(self):
        Ledger = self.env["avea.credit.ledger.entry"]
        Partner = self.env["res.partner"]
        for dashboard in self:
            company = self.env.company
            partners = Partner.search(
                [
                    ("avea_credit_balance", ">", 0),
                    "|",
                    ("company_id", "=", company.id),
                    ("company_id", "=", False),
                ]
            )
            outstanding_store_credit = sum(partners.mapped("avea_credit_balance"))
            outstanding_customers = len(partners)
            average_customer_balance = (
                outstanding_store_credit / outstanding_customers
                if outstanding_customers
                else 0.0
            )

            posted_today_domain = dashboard._get_company_ledger_domain(
                [("state", "=", "posted")] + dashboard._get_today_domain()
            )
            transactions_today = Ledger.search_count(posted_today_domain)

            issued_today_domain = posted_today_domain + [
                ("reason_id.is_outflow", "=", False),
            ]
            issued_groups = Ledger.read_group(
                issued_today_domain,
                ["amount:sum"],
                [],
            )
            credit_issued_today = issued_groups[0]["amount"] if issued_groups else 0.0

            redeemed_today_domain = posted_today_domain + [
                ("reason_id.is_outflow", "=", True),
            ]
            redeemed_groups = Ledger.read_group(
                redeemed_today_domain,
                ["amount:sum"],
                [],
            )
            credit_redeemed_today = (
                redeemed_groups[0]["amount"] if redeemed_groups else 0.0
            )

            dashboard.update(
                {
                    "outstanding_store_credit": outstanding_store_credit,
                    "credit_issued_today": credit_issued_today,
                    "credit_redeemed_today": credit_redeemed_today,
                    "outstanding_customers": outstanding_customers,
                    "transactions_today": transactions_today,
                    "average_customer_balance": average_customer_balance,
                }
            )

    @api.depends("currency_id")
    def _compute_recent_entries(self):
        Ledger = self.env["avea.credit.ledger.entry"]
        for dashboard in self:
            entries = Ledger.search(
                dashboard._get_company_ledger_domain([("state", "=", "posted")]),
                order="transaction_date desc, id desc",
                limit=RECENT_ACTIVITY_LIMIT,
            )
            dashboard.recent_entry_ids = entries

    @api.depends("currency_id")
    def _compute_attention_partners(self):
        Partner = self.env["res.partner"]
        company = self.env.company
        for dashboard in self:
            partners = Partner.search(
                [
                    ("avea_credit_balance", ">", 0),
                    "|",
                    ("company_id", "=", company.id),
                    ("company_id", "=", False),
                ],
                order="avea_credit_balance desc",
                limit=ATTENTION_CUSTOMER_LIMIT,
            )
            dashboard.attention_partner_ids = partners

    def action_open_ledger(self):
        return self.env["avea.credit.ledger.entry"].action_open_ledger()

    def action_issue_credit(self):
        self.ensure_one()
        return self.env["avea.credit.issue.wizard"].action_open_wizard()

    def action_refresh(self):
        self.ensure_one()
        return self.env["avea.credit.dashboard"].action_open_credit_dashboard()
