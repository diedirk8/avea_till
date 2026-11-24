from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import formatLang

SALARY_WAGES_ACCOUNT_CODE = "610050"
OWNER_DRAWING_ACCOUNT_CODE = "300070"


class AveaWithdrawCashWizard(models.TransientModel):
    _name = "avea.withdraw.cash.wizard"
    _description = "Withdraw"

    cash_journal_id = fields.Many2one(
        "account.journal",
        string="From",
        required=True,
        domain="[('id', 'in', available_journal_ids)]",
        help="The cash or bank account the money leaves.",
    )
    available_journal_ids = fields.Many2many(
        "account.journal",
        compute="_compute_available_journal_ids",
    )
    withdrawal_purpose = fields.Selection(
        [
            ("staff_advance", "Staff Advance"),
            ("salary_wages", "Salary / Wages"),
            ("owner_drawing", "Owner / director"),
            ("other_expense", "Other Expense"),
        ],
        string="For",
        required=True,
        default="owner_drawing",
    )
    amount = fields.Monetary(
        string="Amount",
        required=True,
        currency_field="currency_id",
    )
    employee_id = fields.Many2one(
        "res.partner",
        string="Employee",
        help="Who this salary or advance is for. Advances are part of their salary.",
    )
    employee_advance_outstanding = fields.Monetary(
        string="Advances already paid",
        compute="_compute_employee_advance_outstanding",
        currency_field="currency_id",
    )
    employee_salary_including_advances = fields.Monetary(
        string="Salary including advances",
        compute="_compute_employee_advance_outstanding",
        currency_field="currency_id",
    )
    employee_advance_help = fields.Char(
        compute="_compute_employee_advance_outstanding",
    )
    reference_name = fields.Char(
        string="Reference / Name",
        help="A short label for this withdrawal, e.g. John - salary advance.",
    )
    expense_account_id = fields.Many2one(
        "account.account",
        string="Expense",
        domain=(
            "[('active', '=', True), "
            "('account_type', 'in', "
            "('expense', 'expense_other', 'expense_direct_cost'))]"
        ),
        help="What the withdrawn money was spent on.",
    )
    withdrawal_date = fields.Date(
        string="Date",
        required=True,
        default=fields.Date.context_today,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )

    @api.depends("company_id")
    def _compute_available_journal_ids(self):
        for wizard in self:
            company = wizard.company_id
            wizard.available_journal_ids = (
                company._avea_expense_journals() if company else False
            )

    @api.model
    def default_get(self, fields_list):
        return super().default_get(fields_list)

    @api.constrains("amount")
    def _check_amount_positive(self):
        for wizard in self:
            if wizard.currency_id.compare_amounts(wizard.amount, 0.0) <= 0:
                raise ValidationError(_("Amount must be greater than zero."))

    @api.constrains("withdrawal_purpose", "expense_account_id")
    def _check_other_expense_account(self):
        for wizard in self:
            if wizard.withdrawal_purpose == "other_expense" and not wizard.expense_account_id:
                raise ValidationError(_("Select what the money was spent on."))

    @api.constrains("withdrawal_purpose", "employee_id")
    def _check_employee_for_salary(self):
        for wizard in self:
            if (
                wizard.withdrawal_purpose in ("staff_advance", "salary_wages")
                and not wizard.employee_id
            ):
                raise ValidationError(
                    _("Choose the employee this salary or advance is for.")
                )

    @api.depends("employee_id", "withdrawal_purpose", "amount", "currency_id")
    def _compute_employee_advance_outstanding(self):
        for wizard in self:
            employee = wizard.employee_id
            outstanding = 0.0
            if employee and wizard.withdrawal_purpose in (
                "staff_advance",
                "salary_wages",
            ):
                outstanding = employee.avea_employee_advance_outstanding or 0.0
            wizard.employee_advance_outstanding = outstanding
            cash = wizard.amount or 0.0
            if wizard.withdrawal_purpose == "salary_wages":
                wizard.employee_salary_including_advances = cash + outstanding
            else:
                wizard.employee_salary_including_advances = 0.0
            wizard.employee_advance_help = wizard._avea_employee_pay_help(
                employee, outstanding, cash
            )

    def _avea_employee_pay_help(self, employee, outstanding, cash):
        self.ensure_one()
        if not employee or not self.currency_id:
            return False
        currency = self.currency_id
        money = lambda amount: formatLang(self.env, amount, currency_obj=currency)
        if self.withdrawal_purpose == "staff_advance":
            return _(
                "This is salary paid early. It comes off %(name)s's next salary "
                "so you do not pay it twice.",
                name=employee.display_name,
            )
        if self.withdrawal_purpose != "salary_wages":
            return False
        parts = []
        usual = employee.avea_employee_usual_salary or 0.0
        if currency.compare_amounts(usual, 0.0) > 0:
            parts.append(_("Usual salary %(usual)s.", usual=money(usual)))
        if currency.compare_amounts(outstanding, 0.0) > 0:
            parts.append(
                _(
                    "%(advance)s already paid — that comes off this salary.",
                    advance=money(outstanding),
                )
            )
            due = employee.avea_employee_cash_due or 0.0
            if currency.compare_amounts(due, 0.0) > 0:
                parts.append(
                    _("Cash still due: %(due)s. Enter the cash you are paying now.", due=money(due))
                )
            else:
                parts.append(
                    _(
                        "Enter only extra cash if you are paying more. This salary: %(total)s.",
                        total=money(cash + outstanding),
                    )
                )
        elif currency.compare_amounts(usual, 0.0) > 0:
            parts.append(_("Enter the cash you are paying now."))
        return " ".join(parts) if parts else False

    @api.onchange("company_id")
    def _onchange_company_id_cash_journal(self):
        journal = self.cash_journal_id
        allowed = self._avea_cash_journals(self.company_id)
        if journal and journal not in allowed:
            self.cash_journal_id = False

    @api.onchange("withdrawal_purpose")
    def _onchange_withdrawal_purpose(self):
        if self.withdrawal_purpose != "other_expense":
            self.expense_account_id = False
        if self.withdrawal_purpose not in ("staff_advance", "salary_wages"):
            self.employee_id = False

    @api.onchange("employee_id", "withdrawal_purpose")
    def _onchange_employee_suggest_salary_cash(self):
        if self.withdrawal_purpose != "salary_wages" or not self.employee_id:
            return
        due = self.employee_id.avea_employee_cash_due or 0.0
        if self.currency_id.compare_amounts(due, 0.0) <= 0:
            return
        if self.currency_id.compare_amounts(self.amount or 0.0, 0.0) <= 0:
            self.amount = due

    @api.model
    def action_open_wizard(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Withdraw"),
            "res_model": self._name,
            "view_mode": "form",
            "view_id": self.env.ref(
                "avea_till.view_avea_withdraw_cash_wizard_form"
            ).id,
            "target": "new",
        }

    def action_withdraw_cash(self):
        self.ensure_one()
        self._avea_check_withdrawal()
        self._avea_post_withdrawal()
        return self._avea_success_close()

    @api.model
    def _avea_cash_journals(self, company):
        company = company or self.env.company
        return company._avea_expense_journals()

    @api.model
    def _avea_default_cash_journal(self, company):
        company = company or self.env.company
        journals = company._avea_expense_journals()
        if company.avea_cash_safe_journal_id and company.avea_cash_safe_journal_id in journals:
            return company.avea_cash_safe_journal_id
        cash_journals = journals.filtered(lambda journal: journal.type == "cash")
        petty = cash_journals.filtered(lambda journal: "petty" in (journal.name or "").lower())
        return petty[:1] or cash_journals[:1] or journals[:1]

    @api.model
    def _avea_account_by_code(self, company, code, label):
        account = (
            self.env["account.account"]
            .sudo()
            .search(
                [
                    ("code", "=", code),
                    ("company_ids", "in", company.id),
                ],
                limit=1,
            )
        )
        if not account:
            raise UserError(
                _(
                    "%(label)s is not set up in your accounts (%(code)s). "
                    "Ask your accountant to configure it before recording a withdrawal.",
                    label=label,
                    code=code,
                )
            )
        return account

    def _avea_destination_account(self):
        self.ensure_one()
        company = self.company_id
        if self.withdrawal_purpose == "staff_advance":
            return self._avea_account_by_code(
                company,
                SALARY_WAGES_ACCOUNT_CODE,
                _("Distribution Salaries and Wages"),
            )
        if self.withdrawal_purpose == "salary_wages":
            return self._avea_account_by_code(
                company,
                SALARY_WAGES_ACCOUNT_CODE,
                _("Distribution Salaries and Wages"),
            )
        if self.withdrawal_purpose == "owner_drawing":
            return self._avea_account_by_code(
                company,
                OWNER_DRAWING_ACCOUNT_CODE,
                _("Drawings"),
            )
        return self.expense_account_id

    def _avea_cash_journal(self):
        self.ensure_one()
        journal = self.cash_journal_id
        allowed = self._avea_cash_journals(self.company_id)
        if not allowed:
            raise UserError(
                _(
                    "No cash or bank accounts are available for withdrawals. "
                    "Ask an administrator to select them under "
                    "Settings → Avea Dashboard."
                )
            )
        if not journal or journal not in allowed:
            raise UserError(
                _(
                    "Choose a cash or bank account to withdraw from. "
                    "Ask an administrator to update Settings → Avea Dashboard "
                    "if the account you need is missing."
                )
            )
        if not journal.default_account_id:
            raise UserError(
                _(
                    "%(journal)s has no money account set. "
                    "Ask your accountant to configure it.",
                    journal=journal.display_name,
                )
            )
        return journal

    def _avea_check_withdrawal(self):
        self.ensure_one()
        if self.currency_id.compare_amounts(self.amount, 0.0) <= 0:
            raise UserError(_("Amount must be greater than zero."))
        if self.withdrawal_purpose == "other_expense" and not self.expense_account_id:
            raise UserError(_("Select what the money was spent on."))
        if self.withdrawal_purpose in ("staff_advance", "salary_wages") and not self.employee_id:
            raise UserError(_("Choose the employee this salary or advance is for."))
        self._avea_cash_journal()
        self._avea_destination_account()

    def _avea_purpose_label(self):
        self.ensure_one()
        return dict(self._fields["withdrawal_purpose"].selection).get(
            self.withdrawal_purpose, ""
        )

    def _avea_payment_reference(self):
        self.ensure_one()
        reference = (self.reference_name or "").strip()
        if reference:
            return reference
        if self.employee_id:
            return _("%(name)s — %(purpose)s", name=self.employee_id.name, purpose=self._avea_purpose_label())
        return self._avea_purpose_label()

    def _avea_narration(self):
        self.ensure_one()
        parts = [
            _(
                "Recorded from Avea. Withdrawn from %(source)s for %(purpose)s.",
                source=self.cash_journal_id.display_name,
                purpose=self._avea_purpose_label(),
            )
        ]
        if self.employee_id:
            parts.append(_("Employee: %(name)s", name=self.employee_id.display_name))
        reference = (self.reference_name or "").strip()
        if reference:
            parts.append(_("Reference: %(reference)s", reference=reference))
        if self.withdrawal_purpose == "staff_advance":
            parts.append(_("This advance is part of the employee's salary."))
        if self.withdrawal_purpose == "other_expense":
            parts.append(
                _("Expense: %(account)s", account=self.expense_account_id.display_name)
            )
        return "\n".join(parts)

    def _avea_staff_pay_kind(self):
        self.ensure_one()
        if self.withdrawal_purpose == "staff_advance":
            return "advance"
        if self.withdrawal_purpose == "salary_wages":
            return "salary"
        return False

    def _avea_post_withdrawal(self):
        """Reduce the selected cash or bank account via a statement line."""
        self.ensure_one()
        journal = self._avea_cash_journal()
        kind = self._avea_staff_pay_kind()
        if kind and self.employee_id:
            return self.employee_id._avea_post_staff_pay(
                journal=journal,
                amount=self.amount,
                pay_date=self.withdrawal_date,
                kind=kind,
                reference=self._avea_payment_reference(),
                narration=self._avea_narration(),
            )
        destination_account = self._avea_destination_account()
        statement_line = (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(
                {
                    "journal_id": journal.id,
                    "amount": -self.amount,
                    "date": self.withdrawal_date,
                    "payment_ref": self._avea_payment_reference(),
                    "partner_id": self.company_id.partner_id.id,
                    "counterpart_account_id": destination_account.id,
                }
            )
        )
        moves = statement_line.move_id
        if moves:
            moves.sudo().write({"narration": self._avea_narration()})
        return statement_line

    def _avea_success_close(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Withdrawn"),
                "message": _(
                    "%(amount)s withdrawn from %(source)s for %(purpose)s%(employee)s.",
                    amount=formatLang(
                        self.env, self.amount, currency_obj=self.currency_id
                    ),
                    source=self.cash_journal_id.display_name,
                    purpose=self._avea_purpose_label(),
                    employee=(
                        _(" — %(name)s", name=self.employee_id.display_name)
                        if self.employee_id
                        else ""
                    ),
                ),
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
