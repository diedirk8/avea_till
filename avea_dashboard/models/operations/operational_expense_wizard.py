from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import formatLang

from .bank_reconcile_booking_rules import AveaBankReconcileBookingRules
from .withdraw_cash_wizard import SALARY_WAGES_ACCOUNT_CODE


class AveaOperationalExpenseWizard(models.TransientModel):
    _name = "avea.operational.expense.wizard"
    _description = "Add Operational Expense"

    partner_id = fields.Many2one(
        "res.partner",
        string="Paid to",
        required=True,
    )
    what_for = fields.Selection(
        selection=[
            ("expense", "Shop / operating expense"),
            ("salary", "Salary / wages"),
            ("advance", "Salary advance"),
        ],
        string="What is this?",
        default="expense",
        required=True,
    )
    expense_date = fields.Date(
        string="Date",
        required=True,
        default=fields.Date.context_today,
    )
    document_ref = fields.Char(
        string="Document Reference",
    )
    expense_account_id = fields.Many2one(
        "account.account",
        string="Expense Account",
        domain="[('id', 'in', available_expense_account_ids)]",
        help="What the money was spent on. Owner drawings is listed for personal card spend.",
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
    available_expense_account_ids = fields.Many2many(
        "account.account",
        compute="_compute_available_expense_account_ids",
    )
    description = fields.Char(
        string="Description",
        required=True,
    )
    amount = fields.Monetary(
        string="Amount",
        required=True,
        currency_field="currency_id",
        help="The total amount paid. Configured taxes are applied underneath.",
    )
    paid_from_journal_id = fields.Many2one(
        "account.journal",
        string="Paid From",
        required=True,
        domain="[('id', 'in', available_journal_ids)]",
        help="The company money account this expense was paid from.",
    )
    available_journal_ids = fields.Many2many(
        "account.journal",
        compute="_compute_available_journal_ids",
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
    bank_reconcile_line_id = fields.Many2one(
        "avea.bank.reconcile.line",
        string="Bank reconcile line",
        ondelete="set null",
    )
    booking_partner_role = fields.Selection(
        selection=[
            ("supplier", "Supplier"),
            ("employee", "Employee"),
            ("bank", "Bank"),
            ("merchant", "Merchant"),
        ],
        string="Payee type",
        readonly=True,
    )
    partner_hint = fields.Text(
        string="Payee help",
        readonly=True,
    )

    @api.depends("company_id")
    def _compute_available_journal_ids(self):
        for wizard in self:
            company = wizard.company_id
            wizard.available_journal_ids = (
                company._avea_expense_journals() if company else False
            )

    @api.depends("company_id")
    def _compute_available_expense_account_ids(self):
        Account = self.env["account.account"]
        for wizard in self:
            company = wizard.company_id or self.env.company
            wizard.available_expense_account_ids = Account.search(
                AveaBankReconcileBookingRules.expense_account_domain(company)
            )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        ctx = self.env.context
        role = ctx.get("avea_booking_partner_role")
        if role and "booking_partner_role" in fields_list:
            values["booking_partner_role"] = role
        hint = ctx.get("default_partner_hint")
        if hint and "partner_hint" in fields_list:
            values["partner_hint"] = hint
        return values

    @api.constrains("amount")
    def _check_amount_positive(self):
        for wizard in self:
            if wizard.currency_id.compare_amounts(wizard.amount, 0.0) <= 0:
                raise ValidationError(_("Amount must be greater than zero."))

    @api.constrains("what_for", "expense_account_id")
    def _check_expense_account(self):
        for wizard in self:
            if wizard.what_for == "expense" and not wizard.expense_account_id:
                raise ValidationError(_("Select what the money was spent on."))

    def _avea_is_staff_pay(self):
        self.ensure_one()
        return self.what_for in ("salary", "advance")

    @api.depends("partner_id", "what_for", "amount", "currency_id")
    def _compute_employee_advance_outstanding(self):
        for wizard in self:
            outstanding = 0.0
            if wizard.partner_id and wizard._avea_is_staff_pay():
                outstanding = wizard.partner_id.avea_employee_advance_outstanding or 0.0
            wizard.employee_advance_outstanding = outstanding
            cash = wizard.amount or 0.0
            if wizard.what_for == "salary":
                wizard.employee_salary_including_advances = cash + outstanding
            else:
                wizard.employee_salary_including_advances = 0.0
            if (
                wizard.what_for == "salary"
                and wizard.partner_id
                and wizard.currency_id
                and wizard.currency_id.compare_amounts(outstanding, 0.0) > 0
            ):
                wizard.employee_advance_help = _(
                    "%(advance)s already paid as advance — that is part of this salary. "
                    "Enter only the extra cash you are paying now. Total this salary: %(total)s.",
                    advance=formatLang(
                        wizard.env, outstanding, currency_obj=wizard.currency_id
                    ),
                    total=formatLang(
                        wizard.env,
                        cash + outstanding,
                        currency_obj=wizard.currency_id,
                    ),
                )
            elif wizard.what_for == "advance" and wizard.partner_id:
                wizard.employee_advance_help = _(
                    "This advance is salary paid early. It will show on %(name)s "
                    "and count toward their next salary.",
                    name=wizard.partner_id.display_name,
                )
            else:
                wizard.employee_advance_help = False

    def _avea_salary_account(self):
        company = self.company_id or self.env.company
        return self.env["account.account"].sudo().search(
            [
                ("code", "=", SALARY_WAGES_ACCOUNT_CODE),
                ("company_ids", "in", company.id),
                ("active", "=", True),
            ],
            limit=1,
        ) or self.env["account.account"].sudo().search(
            [
                ("company_ids", "in", company.id),
                ("active", "=", True),
                ("name", "ilike", "salary"),
            ],
            limit=1,
        )

    @api.onchange("what_for", "company_id")
    def _onchange_what_for(self):
        if self.what_for not in ("salary", "advance"):
            if self.booking_partner_role == "employee":
                self.booking_partner_role = "supplier"
                self.partner_hint = False
            return
        self.booking_partner_role = "employee"
        self.partner_hint = AveaBankReconcileBookingRules.partner_hint_for_role(
            "employee"
        )
        salary_account = self._avea_salary_account()
        if salary_account:
            self.expense_account_id = salary_account
        line = self.bank_reconcile_line_id
        if line and not self.partner_id:
            partner = AveaBankReconcileBookingRules.suggest_partner(
                self.env,
                company=self.company_id or self.env.company,
                partner_role="employee",
                description=line.description,
                reference=line.reference,
            )
            if partner:
                self.partner_id = partner

    @api.onchange("company_id")
    def _onchange_company_id_paid_from(self):
        journal = self.paid_from_journal_id
        allowed = self._avea_paid_from_journals(self.company_id)
        if journal and journal not in allowed:
            self.paid_from_journal_id = False

    @api.model
    def action_open_wizard(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Add Operational Expense"),
            "res_model": self._name,
            "view_mode": "form",
            "view_id": self.env.ref(
                "avea_till.view_avea_operational_expense_wizard_form"
            ).id,
            "target": "new",
        }

    def action_record_expense(self):
        self.ensure_one()
        self._avea_resolve_partner()
        if self._avea_is_staff_pay():
            statement_line = self._avea_post_staff_pay()
        else:
            if not self.expense_account_id:
                raise UserError(_("Select what the money was spent on."))
            bill = self._avea_create_vendor_bill()
            statement_line = self._avea_pay_bill(bill)
        self._avea_remember_bank_booking()
        if self.bank_reconcile_line_id:
            return self.bank_reconcile_line_id._avea_after_booked(statement_line)
        return self._avea_success_close()

    def _avea_remember_bank_booking(self):
        self.ensure_one()
        line = self.bank_reconcile_line_id
        if not line:
            return
        account = self.expense_account_id
        if self._avea_is_staff_pay() and not account:
            account = self._avea_salary_account()
        AveaBankReconcileBookingRules.remember(
            self.env,
            company=self.company_id,
            description=line.description,
            reference=line.reference,
            partner=self.partner_id,
            account=account,
            import_action="expense",
        )

    def _avea_resolve_partner(self):
        """Flag the payee as an employee or supplier before posting."""
        self.ensure_one()
        partner = self.partner_id
        if not partner:
            if self._avea_is_staff_pay():
                raise UserError(_("Choose the employee this salary or advance is for."))
            raise UserError(_("Choose a supplier or add a new one from the list."))
        if self._avea_is_staff_pay():
            partner._avea_mark_employee()
            return partner
        if partner.supplier_rank < 1:
            partner.sudo().write({"supplier_rank": 1})
        return partner

    def _avea_staff_pay_kind(self):
        self.ensure_one()
        if self.what_for == "advance":
            return "advance"
        if self.what_for == "salary":
            return "salary"
        return False

    def _avea_post_staff_pay(self):
        self.ensure_one()
        journal = self._avea_payment_journal()
        salary_account = self._avea_salary_account()
        if salary_account and not self.expense_account_id:
            self.expense_account_id = salary_account
        return self.partner_id._avea_post_staff_pay(
            journal=journal,
            amount=self.amount,
            pay_date=self.expense_date,
            kind=self._avea_staff_pay_kind(),
            reference=self.document_ref or self.description,
            narration=_(
                "Recorded from Avea. Paid from %(journal)s to %(name)s (%(kind)s).",
                journal=self.paid_from_journal_id.display_name,
                name=self.partner_id.display_name,
                kind=dict(self._fields["what_for"].selection).get(self.what_for),
            ),
        )

    def _avea_create_vendor_bill(self):
        self.ensure_one()
        journal = self._avea_purchase_journal()
        taxes = self._avea_purchase_taxes()
        price_unit = self._avea_line_price_unit(taxes)
        bill = (
            self.env["account.move"]
            .sudo()
            .with_company(self.company_id)
            .create(
                {
                    "move_type": "in_invoice",
                    "partner_id": self.partner_id.id,
                    "invoice_date": self.expense_date,
                    "invoice_date_due": self.expense_date,
                    "date": self.expense_date,
                    "ref": self.document_ref or False,
                    "invoice_origin": _("Avea Operational Expense"),
                    "journal_id": journal.id,
                    "company_id": self.company_id.id,
                    "currency_id": self.currency_id.id,
                    "invoice_user_id": self.env.user.id,
                    "narration": _(
                        "Recorded from Avea. Paid from %(journal)s.",
                        journal=self.paid_from_journal_id.display_name,
                    ),
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "name": self.description,
                                "account_id": self.expense_account_id.id,
                                "quantity": 1.0,
                                "price_unit": price_unit,
                                "tax_ids": [Command.set(taxes.ids)],
                                "display_type": "product",
                            }
                        )
                    ],
                }
            )
        )
        self._avea_align_bill_total(bill)
        bill.action_post()
        return bill

    def _avea_align_bill_total(self, bill):
        """Keep the bill total equal to the amount paid when tax rounding differs.

        Odoo computes tax from the untaxed price. For some totals that produces a
        1-cent difference from the tax-included amount the owner entered. Use the
        same tax_totals adjustment an accountant would make on the bill.
        """
        self.ensure_one()
        currency = self.currency_id
        if currency.compare_amounts(bill.amount_total, self.amount) == 0:
            return
        totals = bill.tax_totals
        if not totals or not totals.get("has_tax_groups"):
            return
        remaining = currency.round(bill.amount_total - self.amount)
        for subtotal in totals.get("subtotals") or []:
            for group in subtotal.get("tax_groups") or []:
                if currency.is_zero(remaining):
                    break
                group["tax_amount_currency"] = currency.round(
                    group["tax_amount_currency"] - remaining
                )
                remaining = 0.0
        bill.tax_totals = totals

    def _avea_line_price_unit(self, taxes):
        """Keep Amount as the total paid, using the company's configured taxes."""
        if not taxes:
            return self.amount
        included = taxes.with_context(force_price_include=True).compute_all(
            self.amount,
            currency=self.currency_id,
            quantity=1.0,
            partner=self.partner_id,
        )
        return included.get("total_excluded", self.amount)

    def _avea_purchase_taxes(self):
        taxes = self.expense_account_id.tax_ids.filtered(
            lambda tax: tax.type_tax_use == "purchase"
        )
        if not taxes:
            taxes = self.company_id.account_purchase_tax_id
        fiscal_position = self.partner_id.with_company(
            self.company_id
        ).property_account_position_id
        if fiscal_position:
            taxes = fiscal_position.map_tax(taxes)
        return taxes

    def _avea_purchase_journal(self):
        journal = self.env["account.journal"].search(
            [
                ("type", "=", "purchase"),
                ("company_id", "=", self.company_id.id),
            ],
            limit=1,
        )
        if not journal:
            raise UserError(
                _("No purchase journal is configured. Ask your accountant to set one up.")
            )
        return journal

    @api.model
    def _avea_paid_from_journals(self, company):
        company = company or self.env.company
        return company._avea_expense_journals()

    @api.model
    def _avea_default_paid_from_journal(self, company):
        journals = self._avea_paid_from_journals(company)
        return journals.filtered(lambda journal: journal.type == "cash")[:1] or journals[:1]

    def _avea_payment_journal(self):
        journal = self.paid_from_journal_id
        allowed = self._avea_paid_from_journals(self.company_id)
        if not allowed:
            raise UserError(
                _(
                    "No company money accounts are available for Operational "
                    "Expenses. Ask an administrator to select them under "
                    "Settings → Avea Dashboard."
                )
            )
        if not journal or journal not in allowed:
            raise UserError(
                _(
                    "Choose a company cash or bank account that is available "
                    "for Operational Expenses. Ask an administrator to update "
                    "Settings → Avea Dashboard if the account you need is missing."
                )
            )
        return journal

    def _avea_supplier_payable_account(self):
        payable = self.partner_id.with_company(
            self.company_id
        ).property_account_payable_id
        if not payable:
            raise UserError(
                _("This supplier has no payable account. Ask your accountant to set one up.")
            )
        return payable

    def _avea_pay_bill(self, bill):
        """Pay the vendor bill from the selected cash/bank journal.

        Uses Odoo's bank/cash statement line so the liquidity account is reduced
        and the supplier payable is reconciled, without POS session or till
        coupling, and without exposing journals or reconciliation to the owner.
        """
        journal = self._avea_payment_journal()
        payable = self._avea_supplier_payable_account()
        amount = bill.amount_residual or self.amount
        payment_ref = self.document_ref or self.description
        statement_line = (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(
                {
                    "journal_id": journal.id,
                    "amount": -amount,
                    "date": self.expense_date,
                    "payment_ref": payment_ref,
                    "partner_id": self.partner_id.id,
                    "counterpart_account_id": payable.id,
                }
            )
        )
        self._avea_reconcile_bill_with_statement(bill, statement_line, payable)
        return statement_line

    def _avea_reconcile_bill_with_statement(self, bill, statement_line, payable):
        bill_lines = bill.line_ids.filtered(
            lambda line: line.account_id == payable and not line.reconciled
        )
        statement_lines = statement_line.move_id.line_ids.filtered(
            lambda line: line.account_id == payable and not line.reconciled
        )
        to_reconcile = bill_lines | statement_lines
        if len(to_reconcile) >= 2:
            to_reconcile.sudo().reconcile()

    def _avea_success_close(self):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Expense recorded"),
                "message": _(
                    "%(description)s for %(supplier)s has been recorded.",
                    description=self.description or self._avea_staff_pay_kind() or _("Expense"),
                    supplier=self.partner_id.display_name,
                ),
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
