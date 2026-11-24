# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

SALARY_WAGES_ACCOUNT_CODE = "610050"


class ResPartnerEmployeeCentre(models.Model):
    _inherit = "res.partner"

    avea_is_employee = fields.Boolean(
        string="Employee",
        default=False,
        index=True,
        help="People you pay salary or advances to. They live under Employees, not Suppliers.",
    )
    avea_employee_pay_ids = fields.One2many(
        "account.bank.statement.line",
        "avea_employee_id",
        string="Pay history",
    )
    avea_employee_job_title = fields.Char(string="Job")
    avea_employee_start_date = fields.Date(string="Started")
    avea_employee_pay_frequency = fields.Selection(
        selection=[
            ("weekly", "Weekly"),
            ("fortnightly", "Every 2 weeks"),
            ("monthly", "Monthly"),
        ],
        string="Paid",
        default="monthly",
    )
    avea_employee_usual_salary = fields.Monetary(
        string="Usual salary",
        currency_field="avea_employee_currency_id",
        help="What this person is usually paid. Used to show cash still due after advances.",
    )
    avea_employee_bank_holder = fields.Char(string="Account name")
    avea_employee_bank_name = fields.Char(string="Bank")
    avea_employee_bank_branch = fields.Char(string="Branch code")
    avea_employee_bank_account = fields.Char(string="Account number")
    avea_employee_currency_id = fields.Many2one(
        "res.currency",
        string="Employee currency",
        compute="_compute_avea_employee_stats",
        store=True,
    )
    avea_employee_paid_total = fields.Monetary(
        string="Paid in total",
        compute="_compute_avea_employee_stats",
        store=True,
        currency_field="avea_employee_currency_id",
        help="All salary and advances paid to this person. Advances are part of salary.",
    )
    avea_employee_paid_year = fields.Monetary(
        string="Paid this year",
        compute="_compute_avea_employee_stats",
        store=True,
        currency_field="avea_employee_currency_id",
    )
    avea_employee_paid_month = fields.Monetary(
        string="Paid this month",
        compute="_compute_avea_employee_stats",
        store=True,
        currency_field="avea_employee_currency_id",
    )
    avea_employee_advance_outstanding = fields.Monetary(
        string="Already paid",
        compute="_compute_avea_employee_stats",
        store=True,
        currency_field="avea_employee_currency_id",
        help="Salary paid early. Comes off the next salary so it is not paid twice.",
    )
    avea_employee_cash_due = fields.Monetary(
        string="Cash still due",
        compute="_compute_avea_employee_stats",
        store=True,
        currency_field="avea_employee_currency_id",
        help="Usual salary minus what was already paid as an advance.",
    )
    avea_employee_last_paid = fields.Date(
        string="Last paid",
        compute="_compute_avea_employee_stats",
        store=True,
    )

    @api.depends(
        "company_id",
        "company_id.currency_id",
        "avea_employee_usual_salary",
        "avea_employee_pay_ids",
        "avea_employee_pay_ids.amount",
        "avea_employee_pay_ids.date",
        "avea_employee_pay_ids.avea_staff_pay_kind",
        "avea_employee_pay_ids.avea_staff_applied_salary_id",
    )
    def _compute_avea_employee_stats(self):
        currency = self.env.company.currency_id
        today = fields.Date.context_today(self)
        year_start = today.replace(month=1, day=1)
        month_start = today.replace(day=1)
        for partner in self:
            partner.avea_employee_currency_id = (
                partner.company_id.currency_id or currency
            )
            lines = partner.avea_employee_pay_ids.filtered("avea_staff_pay_kind")
            partner.avea_employee_paid_total = sum(
                abs(line.amount or 0.0) for line in lines
            )
            partner.avea_employee_paid_year = sum(
                abs(line.amount or 0.0)
                for line in lines
                if line.date and line.date >= year_start
            )
            partner.avea_employee_paid_month = sum(
                abs(line.amount or 0.0)
                for line in lines
                if line.date and line.date >= month_start
            )
            outstanding = lines.filtered(
                lambda line: line.avea_staff_pay_kind == "advance"
                and not line.avea_staff_applied_salary_id
            )
            already_paid = sum(abs(line.amount or 0.0) for line in outstanding)
            partner.avea_employee_advance_outstanding = already_paid
            usual = partner.avea_employee_usual_salary or 0.0
            partner.avea_employee_cash_due = max(usual - already_paid, 0.0) if usual else 0.0
            partner.avea_employee_last_paid = max(
                lines.mapped("date"),
                default=False,
            )

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get("avea_employee_workspace") or self.env.context.get(
            "avea_staff_payee"
        ):
            for vals in vals_list:
                vals.setdefault("avea_is_employee", True)
                vals.setdefault("is_company", False)
        return super().create(vals_list)

    def _avea_use_employee_workspace_form(self):
        self.ensure_one()
        if self.env.context.get("avea_employee_workspace"):
            return True
        if self.env.context.get("avea_supplier_workspace") or self.env.context.get(
            "avea_customer_workspace"
        ):
            return False
        return bool(self.avea_is_employee) and not self.customer_rank

    def _avea_mark_employee(self):
        self.ensure_one()
        values = {}
        if not self.avea_is_employee:
            values["avea_is_employee"] = True
        if self.is_company:
            values["is_company"] = False
        if values:
            self.sudo().write(values)
        return self

    def _avea_employee_outstanding_advances(self, on_date=None):
        self.ensure_one()
        domain = [
            ("avea_employee_id", "=", self.id),
            ("avea_staff_pay_kind", "=", "advance"),
            ("avea_staff_applied_salary_id", "=", False),
        ]
        if on_date:
            domain.append(("date", "<=", on_date))
        return self.env["account.bank.statement.line"].sudo().search(domain)

    def _avea_salary_account(self):
        company = self.company_id or self.env.company
        account = (
            self.env["account.account"]
            .sudo()
            .search(
                [
                    ("code", "=", SALARY_WAGES_ACCOUNT_CODE),
                    ("company_ids", "in", company.id),
                    ("active", "=", True),
                ],
                limit=1,
            )
        )
        if account:
            return account
        return (
            self.env["account.account"]
            .sudo()
            .search(
                [
                    ("company_ids", "in", company.id),
                    ("active", "=", True),
                    ("name", "ilike", "salary"),
                ],
                limit=1,
            )
        )

    def _avea_post_staff_pay(
        self, *, journal, amount, pay_date, kind, reference, narration=False
    ):
        """Post salary or advance against this employee. Advances stay part of salary."""
        self.ensure_one()
        self._avea_mark_employee()
        destination = self._avea_salary_account()
        if not destination:
            raise UserError(
                _(
                    "Salaries and Wages is not set up in your accounts (%(code)s). "
                    "Ask your accountant to configure it before recording a salary.",
                    code=SALARY_WAGES_ACCOUNT_CODE,
                )
            )
        if not journal or not journal.default_account_id:
            raise UserError(
                _("Choose a cash or bank account to pay this employee from.")
            )
        statement_line = (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(
                {
                    "journal_id": journal.id,
                    "amount": -abs(amount),
                    "date": pay_date,
                    "payment_ref": reference,
                    "partner_id": self.id,
                    "avea_employee_id": self.id,
                    "avea_staff_pay_kind": kind,
                    "counterpart_account_id": destination.id,
                }
            )
        )
        if narration and statement_line.move_id:
            statement_line.move_id.sudo().write({"narration": narration})
        if kind == "salary":
            statement_line._avea_apply_employee_advances()
        self.invalidate_recordset(
            [
                "avea_employee_pay_ids",
                "avea_employee_paid_total",
                "avea_employee_paid_year",
                "avea_employee_paid_month",
                "avea_employee_advance_outstanding",
                "avea_employee_cash_due",
                "avea_employee_last_paid",
            ]
        )
        return statement_line

    def action_avea_open_employee(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": self.id,
            "view_mode": "form",
            "views": [
                (self.env.ref("avea_till.view_avea_employee_form").id, "form"),
            ],
            "target": "current",
            "context": dict(self.env.context, avea_employee_workspace=True),
        }

    def action_avea_record_employee_salary(self):
        self.ensure_one()
        self._avea_mark_employee()
        action = self.env["avea.withdraw.cash.wizard"].action_open_wizard()
        action["context"] = dict(
            action.get("context") or {},
            default_withdrawal_purpose="salary_wages",
            default_employee_id=self.id,
            avea_staff_payee=True,
            avea_employee_workspace=True,
        )
        return action

    def action_avea_open_employee_pay_history(self):
        self.ensure_one()
        action = self.env["account.bank.statement.line"].action_avea_employee_pay_history()
        action["name"] = _("Pay history — %s", self.display_name)
        action["domain"] = [
            ("avea_employee_id", "=", self.id),
            ("avea_staff_pay_kind", "!=", False),
        ]
        ctx = action.get("context") or {}
        if isinstance(ctx, str):
            ctx = safe_eval(ctx, {"uid": self.env.uid})
        ctx = dict(ctx)
        ctx["default_avea_employee_id"] = self.id
        action["context"] = ctx
        return action

    def action_avea_record_employee_advance(self):
        self.ensure_one()
        self._avea_mark_employee()
        action = self.env["avea.withdraw.cash.wizard"].action_open_wizard()
        action["context"] = dict(
            action.get("context") or {},
            default_withdrawal_purpose="staff_advance",
            default_employee_id=self.id,
            avea_staff_payee=True,
            avea_employee_workspace=True,
        )
        return action

    @api.model
    def avea_employee_advance_outstanding_domain(self):
        return [("avea_is_employee", "=", True), ("avea_employee_advance_outstanding", ">", 0)]
