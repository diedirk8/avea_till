from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import formatLang

SALARY_WAGES_ACCOUNT_CODE = "610050"
OWNER_DRAWING_ACCOUNT_CODE = "300070"


class AveaWithdrawCashWizard(models.TransientModel):
    _name = "avea.withdraw.cash.wizard"
    _description = "Withdraw Cash"

    cash_journal_id = fields.Many2one(
        "account.journal",
        string="Cash from",
        required=True,
        domain="[('id', 'in', available_journal_ids)]",
        help="The cash account to take the money from.",
    )
    available_journal_ids = fields.Many2many(
        "account.journal",
        compute="_compute_available_journal_ids",
    )
    withdrawal_purpose = fields.Selection(
        [
            ("staff_advance", "Staff Advance"),
            ("salary_wages", "Salary / Wages"),
            ("owner_drawing", "Owner Drawing"),
            ("other_expense", "Other Expense"),
        ],
        string="Cash for",
        required=True,
        default="owner_drawing",
    )
    amount = fields.Monetary(
        string="Amount",
        required=True,
        currency_field="currency_id",
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
        values = super().default_get(fields_list)
        if "cash_journal_id" in fields_list and not values.get("cash_journal_id"):
            journal = self._avea_default_cash_journal(self.env.company)
            if journal:
                values["cash_journal_id"] = journal.id
        return values

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

    @api.onchange("company_id")
    def _onchange_company_id_cash_journal(self):
        journal = self.cash_journal_id
        allowed = self._avea_cash_journals(self.company_id)
        if journal and journal not in allowed:
            self.cash_journal_id = self._avea_default_cash_journal(self.company_id)

    @api.onchange("withdrawal_purpose")
    def _onchange_withdrawal_purpose(self):
        if self.withdrawal_purpose != "other_expense":
            self.expense_account_id = False

    @api.model
    def action_open_wizard(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Withdraw Cash"),
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
                    "Ask your accountant to configure it before withdrawing cash.",
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
                    "No cash accounts are available for withdrawals. "
                    "Ask an administrator to select them under "
                    "Settings → Avea Dashboard."
                )
            )
        if not journal or journal not in allowed:
            raise UserError(
                _(
                    "Choose a cash account that is available for withdrawals. "
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
        reference = (self.reference_name or "").strip()
        if reference:
            parts.append(_("Reference: %(reference)s", reference=reference))
        if self.withdrawal_purpose == "other_expense":
            parts.append(
                _("Expense: %(account)s", account=self.expense_account_id.display_name)
            )
        return "\n".join(parts)

    def _avea_post_withdrawal(self):
        """Reduce the selected cash account via a bank/cash statement line."""
        self.ensure_one()
        journal = self._avea_cash_journal()
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
                "title": _("Cash withdrawn"),
                "message": _(
                    "%(amount)s withdrawn from %(source)s for %(purpose)s.",
                    amount=formatLang(
                        self.env, self.amount, currency_obj=self.currency_id
                    ),
                    source=self.cash_journal_id.display_name,
                    purpose=self._avea_purpose_label(),
                ),
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
