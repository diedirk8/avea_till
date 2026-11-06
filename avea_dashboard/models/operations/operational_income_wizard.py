from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AveaOperationalIncomeWizard(models.TransientModel):
    _name = "avea.operational.income.wizard"
    _description = "Record Operational Income"

    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
    )
    income_date = fields.Date(
        string="Date",
        required=True,
        default=fields.Date.context_today,
    )
    document_ref = fields.Char(string="Document Reference")
    income_account_id = fields.Many2one(
        "account.account",
        string="Income Account",
        required=True,
        domain=(
            "[('active', '=', True), "
            "('account_type', 'in', ('income', 'income_other'))]"
        ),
    )
    description = fields.Char(string="Description", required=True)
    amount = fields.Monetary(
        string="Amount",
        required=True,
        currency_field="currency_id",
    )
    received_in_journal_id = fields.Many2one(
        "account.journal",
        string="Received In",
        required=True,
        domain="[('id', 'in', available_journal_ids)]",
    )
    available_journal_ids = fields.Many2many(
        "account.journal",
        compute="_compute_available_journal_ids",
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        required=True,
    )
    bank_reconcile_line_id = fields.Many2one(
        "avea.bank.reconcile.line",
        string="Bank reconcile line",
        ondelete="set null",
    )

    @api.depends("company_id")
    def _compute_available_journal_ids(self):
        for wizard in self:
            company = wizard.company_id
            wizard.available_journal_ids = (
                company._avea_expense_journals() if company else False
            )

    @api.constrains("amount")
    def _check_amount_positive(self):
        for wizard in self:
            if wizard.currency_id.compare_amounts(wizard.amount, 0.0) <= 0:
                raise ValidationError(_("Amount must be greater than zero."))

    def action_record_income(self):
        self.ensure_one()
        self._avea_resolve_customer()
        invoice = self._avea_create_customer_invoice()
        statement_line = self._avea_register_payment(invoice)
        if self.bank_reconcile_line_id:
            return self.bank_reconcile_line_id._avea_after_booked(statement_line)
        return self._avea_success_close()

    def _avea_resolve_customer(self):
        partner = self.partner_id
        if not partner:
            raise UserError(_("Choose a customer or add a new one from the list."))
        if partner.customer_rank < 1:
            partner.sudo().write({"customer_rank": 1})
        return partner

    def _avea_create_customer_invoice(self):
        journal = self.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", self.company_id.id)],
            limit=1,
        )
        if not journal:
            raise UserError(_("No sales journal is configured."))
        taxes = self.income_account_id.tax_ids.filtered(
            lambda tax: tax.type_tax_use == "sale"
        )
        if not taxes:
            taxes = self.company_id.account_sale_tax_id
        fiscal_position = self.partner_id.with_company(
            self.company_id
        ).property_account_position_id
        if fiscal_position:
            taxes = fiscal_position.map_tax(taxes)
        if taxes:
            included = taxes.with_context(force_price_include=True).compute_all(
                self.amount,
                currency=self.currency_id,
                quantity=1.0,
                partner=self.partner_id,
            )
            price_unit = included.get("total_excluded", self.amount)
        else:
            price_unit = self.amount
        invoice = (
            self.env["account.move"]
            .sudo()
            .with_company(self.company_id)
            .create(
                {
                    "move_type": "out_invoice",
                    "partner_id": self.partner_id.id,
                    "invoice_date": self.income_date,
                    "invoice_date_due": self.income_date,
                    "date": self.income_date,
                    "ref": self.document_ref or False,
                    "invoice_origin": _("Avea Operational Income"),
                    "journal_id": journal.id,
                    "company_id": self.company_id.id,
                    "currency_id": self.currency_id.id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "name": self.description,
                                "account_id": self.income_account_id.id,
                                "quantity": 1.0,
                                "price_unit": price_unit,
                                "tax_ids": [Command.set(taxes.ids)],
                            }
                        )
                    ],
                }
            )
        )
        invoice.action_post()
        return invoice

    def _avea_register_payment(self, invoice):
        journal = self.received_in_journal_id
        receivable = self.partner_id.with_company(
            self.company_id
        ).property_account_receivable_id
        if not receivable:
            raise UserError(_("This customer has no receivable account."))
        amount = invoice.amount_residual or self.amount
        payment_ref = self.document_ref or self.description
        statement_line = (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(
                {
                    "journal_id": journal.id,
                    "amount": amount,
                    "date": self.income_date,
                    "payment_ref": payment_ref,
                    "partner_id": self.partner_id.id,
                    "counterpart_account_id": receivable.id,
                }
            )
        )
        invoice_lines = invoice.line_ids.filtered(
            lambda line: line.account_id == receivable and not line.reconciled
        )
        st_move_lines = statement_line.move_id.line_ids.filtered(
            lambda line: line.account_id == receivable and not line.reconciled
        )
        to_reconcile = invoice_lines | st_move_lines
        if len(to_reconcile) >= 2:
            to_reconcile.sudo().reconcile()
        return statement_line

    def _avea_success_close(self):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Income recorded"),
                "message": _(
                    "%(description)s for %(customer)s has been recorded.",
                    description=self.description,
                    customer=self.partner_id.display_name,
                ),
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
