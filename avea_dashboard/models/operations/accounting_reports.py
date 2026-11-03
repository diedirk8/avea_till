# -*- coding: utf-8 -*-
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.tools.misc import format_date

from odoo.addons.avea_till.models.till.reporting_period import (
    PERIOD_CUSTOM,
    normalize_period_key,
)

# Signed display helpers (company currency, excl. tax on P&L lines)
_INCOME_TYPES = ("income", "income_other")
_EXPENSE_TYPES = ("expense", "expense_other", "expense_direct_cost")
_ASSET_TYPES = (
    "asset_receivable",
    "asset_cash",
    "asset_current",
    "asset_non_current",
    "asset_fixed",
    "asset_prepayments",
)
_LIABILITY_TYPES = (
    "liability_payable",
    "liability_credit_card",
    "liability_current",
    "liability_non_current",
)
_EQUITY_TYPES = ("equity", "equity_unaffected")

_PERIOD_SELECTION = [
    ("mtd", "Month to Date"),
    ("ytd", "Year to Date"),
    ("last_30", "Last 30 Days"),
    ("custom", "Custom"),
]

_SECTION_LABELS = {
    "income": "Income",
    "expense_direct_cost": "Cost of sales",
    "expense": "Expenses",
    "other_expense": "Other expenses",
    "asset": "Assets",
    "liability": "Liabilities",
    "equity": "Equity",
}


class AveaAccountingReportMixin(models.AbstractModel):
    _name = "avea.accounting.report.mixin"
    _description = "Avea accounting report helpers"

    @api.model
    def _avea_report_company(self):
        return self.env.company

    @api.model
    def _avea_report_currency(self):
        return self.env.company.currency_id

    @api.model
    def _avea_report_resolve_dates(self, period, date_from=None, date_to=None):
        period = normalize_period_key(period or "ytd")
        if period == PERIOD_CUSTOM:
            today = fields.Date.context_today(self)
            start = date_from or today.replace(month=1, day=1)
            end = date_to or today
            if start > end:
                start, end = end, start
        else:
            windows = self.env["avea.reporting.workspace.mixin"]._reporting_period_windows(
                period, date_from, date_to
            )
            start, end = windows["display_current"]
        return period, start, end

    @api.model
    def _avea_report_range_label(self, date_from, date_to):
        return self.env["avea.reporting.workspace.mixin"]._reporting_format_day_range(
            date_from, date_to
        )

    @api.model
    def _avea_move_line_balances(self, domain):
        """Return {account_id: balance_sum} for posted lines matching domain."""
        company = self._avea_report_company()
        MoveLine = self.env["account.move.line"].sudo().with_company(company)
        grouped = MoveLine._read_group(
            domain=domain,
            groupby=["account_id"],
            aggregates=["balance:sum"],
        )
        totals = {}
        for account, balance in grouped:
            account_id = account.id if isinstance(account, models.Model) else account
            totals[account_id] = balance or 0.0
        return totals

    @api.model
    def _avea_display_amount(self, account_type, balance):
        """Turn Odoo balance into a human-friendly positive/negative amount."""
        if account_type in _INCOME_TYPES:
            return -(balance or 0.0)
        if account_type in _LIABILITY_TYPES + _EQUITY_TYPES:
            return -(balance or 0.0)
        return balance or 0.0

    @api.model
    def _avea_pl_section(self, account_type):
        if account_type in _INCOME_TYPES:
            return "income"
        if account_type == "expense_direct_cost":
            return "expense_direct_cost"
        if account_type in _EXPENSE_TYPES:
            return "expense"
        return "other_expense"

    @api.model
    def _avea_bs_section(self, account_type):
        if account_type in _ASSET_TYPES:
            return "asset"
        if account_type in _LIABILITY_TYPES:
            return "liability"
        if account_type in _EQUITY_TYPES:
            return "equity"
        return False


class AveaAccountingReportsHome(models.TransientModel):
    _name = "avea.accounting.reports.home"
    _description = "Accounting reports"
    _inherit = ["avea.accounting.report.mixin"]

    period = fields.Selection(
        _PERIOD_SELECTION,
        required=True,
        default="ytd",
    )
    date_from = fields.Date()
    date_to = fields.Date()
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        required=True,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        readonly=True,
    )
    period_range_display = fields.Char(compute="_compute_period_range_display")

    @api.depends("period", "date_from", "date_to")
    def _compute_period_range_display(self):
        for record in self:
            _, start, end = record._avea_report_resolve_dates(
                record.period, record.date_from, record.date_to
            )
            record.period_range_display = record._avea_report_range_label(start, end)

    @api.model
    def action_open_home(self):
        wizard = self.create({})
        return {
            "type": "ir.actions.act_window",
            "name": _("Reports"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": wizard.id,
            "target": "current",
        }

    def _avea_period_kwargs(self):
        self.ensure_one()
        return {
            "period": self.period,
            "date_from": self.date_from,
            "date_to": self.date_to,
        }

    def action_open_profit_loss(self):
        self.ensure_one()
        return self.env["avea.accounting.profit.loss"].action_open_report(
            **self._avea_period_kwargs()
        )

    def action_open_balance_sheet(self):
        self.ensure_one()
        return self.env["avea.accounting.balance.sheet"].action_open_report(
            **self._avea_period_kwargs()
        )

    def action_open_trial_balance(self):
        self.ensure_one()
        return self.env["avea.accounting.trial.balance"].action_open_report(
            **self._avea_period_kwargs()
        )

    def action_open_general_ledger(self):
        self.ensure_one()
        return self.env["avea.accounting.general.ledger"].action_open_report(
            **self._avea_period_kwargs()
        )


class AveaAccountingProfitLossLine(models.TransientModel):
    _name = "avea.accounting.profit.loss.line"
    _description = "Profit and loss line"
    _order = "section, sequence, account_name"

    report_id = fields.Many2one(
        "avea.accounting.profit.loss",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(related="report_id.currency_id")
    section = fields.Char()
    section_label = fields.Char()
    sequence = fields.Integer(default=10)
    account_id = fields.Many2one("account.account")
    account_name = fields.Char()
    account_code = fields.Char()
    amount = fields.Monetary(currency_field="currency_id")
    is_total = fields.Boolean(default=False)


class AveaAccountingProfitLoss(models.TransientModel):
    _name = "avea.accounting.profit.loss"
    _description = "Profit and loss"
    _inherit = ["avea.accounting.report.mixin"]

    period = fields.Selection(_PERIOD_SELECTION, readonly=True)
    date_from = fields.Date(readonly=True)
    date_to = fields.Date(readonly=True)
    period_range_display = fields.Char(readonly=True)
    currency_id = fields.Many2one(
        "res.currency",
        readonly=True,
    )
    total_income = fields.Monetary(currency_field="currency_id", readonly=True)
    total_expense = fields.Monetary(currency_field="currency_id", readonly=True)
    net_profit = fields.Monetary(currency_field="currency_id", readonly=True)
    line_ids = fields.One2many(
        "avea.accounting.profit.loss.line",
        "report_id",
        readonly=True,
    )

    @api.model
    def action_open_report(self, *, period="ytd", date_from=None, date_to=None):
        period, start, end = self._avea_report_resolve_dates(period, date_from, date_to)
        currency = self._avea_report_currency()
        domain = [
            ("company_id", "=", self._avea_report_company().id),
            ("parent_state", "=", "posted"),
            ("date", ">=", start),
            ("date", "<=", end),
            (
                "account_id.account_type",
                "in",
                _INCOME_TYPES + _EXPENSE_TYPES,
            ),
        ]
        totals = self._avea_move_line_balances(domain)
        Account = self.env["account.account"].sudo()
        accounts = Account.browse(list(totals.keys())).exists()
        lines = []
        section_seq = {"income": 10, "expense_direct_cost": 20, "expense": 30, "other_expense": 40}
        income_total = expense_total = 0.0
        by_section = defaultdict(list)
        for account in accounts:
            amount = self._avea_display_amount(
                account.account_type, totals.get(account.id, 0.0)
            )
            if not amount:
                continue
            section = self._avea_pl_section(account.account_type)
            by_section[section].append(
                {
                    "account_id": account.id,
                    "account_name": account.display_name,
                    "account_code": account.code,
                    "amount": amount,
                }
            )
            if section == "income":
                income_total += amount
            else:
                expense_total += amount
        report = self.create(
            {
                "period": period,
                "date_from": start,
                "date_to": end,
                "period_range_display": self._avea_report_range_label(start, end),
                "currency_id": currency.id,
                "total_income": income_total,
                "total_expense": expense_total,
                "net_profit": income_total - expense_total,
            }
        )
        line_vals = []
        for section in ("income", "expense_direct_cost", "expense", "other_expense"):
            rows = sorted(by_section.get(section, []), key=lambda row: row["account_name"].lower())
            if not rows:
                continue
            for row in rows:
                line_vals.append(
                    {
                        "report_id": report.id,
                        "section": section,
                        "section_label": _(_SECTION_LABELS[section]),
                        "sequence": section_seq[section],
                        "account_id": row["account_id"],
                        "account_name": row["account_name"],
                        "account_code": row["account_code"],
                        "amount": row["amount"],
                    }
                )
            subtotal = sum(row["amount"] for row in rows)
            line_vals.append(
                {
                    "report_id": report.id,
                    "section": section,
                    "section_label": _(_SECTION_LABELS[section]),
                    "sequence": section_seq[section] + 1,
                    "account_name": _("Total %s") % _(_SECTION_LABELS[section]),
                    "amount": subtotal,
                    "is_total": True,
                }
            )
        if line_vals:
            self.env["avea.accounting.profit.loss.line"].create(line_vals)
        return report._avea_action_form(_("Profit and loss"))

    def action_back(self):
        return self.env["avea.accounting.reports.home"].action_open_home()

    def _avea_action_form(self, title):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }


class AveaAccountingBalanceSheetLine(models.TransientModel):
    _name = "avea.accounting.balance.sheet.line"
    _description = "Balance sheet line"
    _order = "section, sequence, account_name"

    report_id = fields.Many2one(
        "avea.accounting.balance.sheet",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(related="report_id.currency_id")
    section = fields.Char()
    section_label = fields.Char()
    sequence = fields.Integer(default=10)
    account_id = fields.Many2one("account.account")
    account_name = fields.Char()
    account_code = fields.Char()
    amount = fields.Monetary(currency_field="currency_id")
    is_total = fields.Boolean(default=False)


class AveaAccountingBalanceSheet(models.TransientModel):
    _name = "avea.accounting.balance.sheet"
    _description = "Balance sheet"
    _inherit = ["avea.accounting.report.mixin"]

    period = fields.Selection(_PERIOD_SELECTION, readonly=True)
    date_from = fields.Date(readonly=True)
    date_to = fields.Date(readonly=True)
    period_range_display = fields.Char(readonly=True)
    as_at_display = fields.Char(readonly=True)
    currency_id = fields.Many2one("res.currency", readonly=True)
    total_assets = fields.Monetary(currency_field="currency_id", readonly=True)
    total_liabilities = fields.Monetary(currency_field="currency_id", readonly=True)
    total_equity = fields.Monetary(currency_field="currency_id", readonly=True)
    line_ids = fields.One2many(
        "avea.accounting.balance.sheet.line",
        "report_id",
        readonly=True,
    )

    @api.model
    def action_open_report(self, *, period="ytd", date_from=None, date_to=None):
        period, _start, end = self._avea_report_resolve_dates(period, date_from, date_to)
        currency = self._avea_report_currency()
        domain = [
            ("company_id", "=", self._avea_report_company().id),
            ("parent_state", "=", "posted"),
            ("date", "<=", end),
            (
                "account_id.account_type",
                "in",
                _ASSET_TYPES + _LIABILITY_TYPES + _EQUITY_TYPES,
            ),
        ]
        totals = self._avea_move_line_balances(domain)
        Account = self.env["account.account"].sudo()
        accounts = Account.browse(list(totals.keys())).exists()
        by_section = defaultdict(list)
        section_totals = defaultdict(float)
        for account in accounts:
            section = self._avea_bs_section(account.account_type)
            if not section:
                continue
            amount = self._avea_display_amount(
                account.account_type, totals.get(account.id, 0.0)
            )
            if not amount:
                continue
            by_section[section].append(
                {
                    "account_id": account.id,
                    "account_name": account.display_name,
                    "account_code": account.code,
                    "amount": amount,
                }
            )
            section_totals[section] += amount
        report = self.create(
            {
                "period": period,
                "date_from": end,
                "date_to": end,
                "period_range_display": self._avea_report_range_label(end, end),
                "as_at_display": format_date(self.env, end, date_format="d MMMM y"),
                "currency_id": currency.id,
                "total_assets": section_totals["asset"],
                "total_liabilities": section_totals["liability"],
                "total_equity": section_totals["equity"],
            }
        )
        line_vals = []
        section_seq = {"asset": 10, "liability": 20, "equity": 30}
        for section in ("asset", "liability", "equity"):
            rows = sorted(by_section.get(section, []), key=lambda row: row["account_name"].lower())
            if not rows:
                continue
            for row in rows:
                line_vals.append(
                    {
                        "report_id": report.id,
                        "section": section,
                        "section_label": _(_SECTION_LABELS[section]),
                        "sequence": section_seq[section],
                        **row,
                    }
                )
            line_vals.append(
                {
                    "report_id": report.id,
                    "section": section,
                    "section_label": _(_SECTION_LABELS[section]),
                    "sequence": section_seq[section] + 1,
                    "account_name": _("Total %s") % _(_SECTION_LABELS[section]),
                    "amount": section_totals[section],
                    "is_total": True,
                }
            )
        if line_vals:
            self.env["avea.accounting.balance.sheet.line"].create(line_vals)
        return report._avea_action_form(_("Balance sheet"))

    def action_back(self):
        return self.env["avea.accounting.reports.home"].action_open_home()

    def _avea_action_form(self, title):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }


class AveaAccountingTrialBalanceLine(models.TransientModel):
    _name = "avea.accounting.trial.balance.line"
    _description = "Trial balance line"
    _order = "account_code, account_name"

    report_id = fields.Many2one(
        "avea.accounting.trial.balance",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(related="report_id.currency_id")
    account_id = fields.Many2one("account.account")
    account_name = fields.Char()
    account_code = fields.Char()
    debit = fields.Monetary(currency_field="currency_id")
    credit = fields.Monetary(currency_field="currency_id")


class AveaAccountingTrialBalance(models.TransientModel):
    _name = "avea.accounting.trial.balance"
    _description = "Trial balance"
    _inherit = ["avea.accounting.report.mixin"]

    period = fields.Selection(_PERIOD_SELECTION, readonly=True)
    date_from = fields.Date(readonly=True)
    date_to = fields.Date(readonly=True)
    period_range_display = fields.Char(readonly=True)
    currency_id = fields.Many2one("res.currency", readonly=True)
    total_debit = fields.Monetary(currency_field="currency_id", readonly=True)
    total_credit = fields.Monetary(currency_field="currency_id", readonly=True)
    line_ids = fields.One2many(
        "avea.accounting.trial.balance.line",
        "report_id",
        readonly=True,
    )

    @api.model
    def action_open_report(self, *, period="ytd", date_from=None, date_to=None):
        period, start, end = self._avea_report_resolve_dates(period, date_from, date_to)
        currency = self._avea_report_currency()
        domain = [
            ("company_id", "=", self._avea_report_company().id),
            ("parent_state", "=", "posted"),
            ("date", ">=", start),
            ("date", "<=", end),
        ]
        totals = self._avea_move_line_balances(domain)
        Account = self.env["account.account"].sudo()
        accounts = Account.search(
            [("id", "in", list(totals.keys()))],
            order="code, name",
        )
        line_vals = []
        total_debit = total_credit = 0.0
        for account in accounts:
            balance = totals.get(account.id, 0.0)
            if not balance:
                continue
            debit = balance if balance > 0 else 0.0
            credit = -balance if balance < 0 else 0.0
            total_debit += debit
            total_credit += credit
            line_vals.append(
                {
                    "account_id": account.id,
                    "account_name": account.display_name,
                    "account_code": account.code or "",
                    "debit": debit,
                    "credit": credit,
                }
            )
        report = self.create(
            {
                "period": period,
                "date_from": start,
                "date_to": end,
                "period_range_display": self._avea_report_range_label(start, end),
                "currency_id": currency.id,
                "total_debit": total_debit,
                "total_credit": total_credit,
            }
        )
        if line_vals:
            for row in line_vals:
                row["report_id"] = report.id
            self.env["avea.accounting.trial.balance.line"].create(line_vals)
        return report._avea_action_form(_("Trial balance"))

    def action_back(self):
        return self.env["avea.accounting.reports.home"].action_open_home()

    def _avea_action_form(self, title):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }


class AveaAccountingGeneralLedgerLine(models.TransientModel):
    _name = "avea.accounting.general.ledger.line"
    _description = "General ledger line"
    _order = "date desc, id desc"

    report_id = fields.Many2one(
        "avea.accounting.general.ledger",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(related="report_id.currency_id")
    date = fields.Date()
    move_name = fields.Char(string="Entry")
    account_id = fields.Many2one("account.account")
    account_name = fields.Char()
    account_code = fields.Char()
    label = fields.Char(string="What")
    partner_name = fields.Char(string="Who")
    debit = fields.Monetary(currency_field="currency_id")
    credit = fields.Monetary(currency_field="currency_id")


class AveaAccountingGeneralLedger(models.TransientModel):
    _name = "avea.accounting.general.ledger"
    _description = "General ledger"
    _inherit = ["avea.accounting.report.mixin"]

    period = fields.Selection(_PERIOD_SELECTION, readonly=True)
    date_from = fields.Date(readonly=True)
    date_to = fields.Date(readonly=True)
    period_range_display = fields.Char(readonly=True)
    currency_id = fields.Many2one("res.currency", readonly=True)
    line_ids = fields.One2many(
        "avea.accounting.general.ledger.line",
        "report_id",
        readonly=True,
    )

    @api.model
    def action_open_report(self, *, period="ytd", date_from=None, date_to=None):
        period, start, end = self._avea_report_resolve_dates(period, date_from, date_to)
        currency = self._avea_report_currency()
        MoveLine = self.env["account.move.line"].sudo().with_company(
            self._avea_report_company()
        )
        lines = MoveLine.search(
            [
                ("company_id", "=", self._avea_report_company().id),
                ("parent_state", "=", "posted"),
                ("date", ">=", start),
                ("date", "<=", end),
            ],
            order="date desc, id desc",
            limit=5000,
        )
        report = self.create(
            {
                "period": period,
                "date_from": start,
                "date_to": end,
                "period_range_display": self._avea_report_range_label(start, end),
                "currency_id": currency.id,
            }
        )
        line_vals = []
        for line in lines:
            balance = line.balance or 0.0
            line_vals.append(
                {
                    "report_id": report.id,
                    "date": line.date,
                    "move_name": line.move_name,
                    "account_id": line.account_id.id,
                    "account_name": line.account_id.display_name,
                    "account_code": line.account_id.code or "",
                    "label": line.name or line.move_name,
                    "partner_name": line.partner_id.display_name if line.partner_id else "",
                    "debit": line.debit,
                    "credit": line.credit,
                }
            )
        if line_vals:
            self.env["avea.accounting.general.ledger.line"].create(line_vals)
        return report._avea_action_form(_("General ledger"))

    def action_back(self):
        return self.env["avea.accounting.reports.home"].action_open_home()

    def _avea_action_form(self, title):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }
