from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AveaOperationalExpenseWizard(models.TransientModel):
    _name = "avea.operational.expense.wizard"
    _description = "Add Operational Expense"

    partner_id = fields.Many2one(
        "res.partner",
        string="Supplier",
        required=True,
        domain="[('supplier_rank', '>', 0)]",
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
        required=True,
        domain=(
            "[('active', '=', True), "
            "('account_type', 'in', "
            "('expense', 'expense_other', 'expense_direct_cost'))]"
        ),
        help="What the business spent the money on.",
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
        if "paid_from_journal_id" in fields_list and not values.get(
            "paid_from_journal_id"
        ):
            journal = self._avea_default_paid_from_journal(self.env.company)
            if journal:
                values["paid_from_journal_id"] = journal.id
        return values

    @api.constrains("amount")
    def _check_amount_positive(self):
        for wizard in self:
            if wizard.currency_id.compare_amounts(wizard.amount, 0.0) <= 0:
                raise ValidationError(_("Amount must be greater than zero."))

    @api.onchange("company_id")
    def _onchange_company_id_paid_from(self):
        journal = self.paid_from_journal_id
        allowed = self._avea_paid_from_journals(self.company_id)
        if journal and journal not in allowed:
            self.paid_from_journal_id = self._avea_default_paid_from_journal(
                self.company_id
            )

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
        bill = self._avea_create_vendor_bill()
        self._avea_pay_bill(bill)
        return self._avea_success_close()

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
                    description=self.description,
                    supplier=self.partner_id.display_name,
                ),
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
