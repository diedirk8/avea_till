# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

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
        string="Salary and advances",
    )
    avea_employee_currency_id = fields.Many2one(
        "res.currency",
        string="Employee currency",
        compute="_compute_avea_employee_stats",
        store=True,
    )
    avea_employee_paid_total = fields.Monetary(
        string="Salary paid",
        compute="_compute_avea_employee_stats",
        store=True,
        currency_field="avea_employee_currency_id",
        help="All salary and advances paid to this person. Advances are part of salary.",
    )
    avea_employee_advance_outstanding = fields.Monetary(
        string="Advances to count",
        compute="_compute_avea_employee_stats",
        store=True,
        currency_field="avea_employee_currency_id",
        help="Advances not yet counted in a later salary payment.",
    )
    avea_employee_last_paid = fields.Date(
        string="Last paid",
        compute="_compute_avea_employee_stats",
        store=True,
    )

    @api.depends(
        "company_id",
        "company_id.currency_id",
        "avea_employee_pay_ids",
        "avea_employee_pay_ids.amount",
        "avea_employee_pay_ids.date",
        "avea_employee_pay_ids.avea_staff_pay_kind",
        "avea_employee_pay_ids.avea_staff_applied_salary_id",
    )
    def _compute_avea_employee_stats(self):
        currency = self.env.company.currency_id
        for partner in self:
            partner.avea_employee_currency_id = (
                partner.company_id.currency_id or currency
            )
            lines = partner.avea_employee_pay_ids.filtered("avea_staff_pay_kind")
            partner.avea_employee_paid_total = sum(
                abs(line.amount or 0.0) for line in lines
            )
            outstanding = lines.filtered(
                lambda line: line.avea_staff_pay_kind == "advance"
                and not line.avea_staff_applied_salary_id
            )
            partner.avea_employee_advance_outstanding = sum(
                abs(line.amount or 0.0) for line in outstanding
            )
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
                "avea_employee_advance_outstanding",
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
