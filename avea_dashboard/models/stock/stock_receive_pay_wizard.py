from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AveaStockReceivePayWizard(models.TransientModel):
    _name = "avea.stock.receive.pay.wizard"
    _description = "Pay Vendor Bill"
    _inherit = ["avea.stock.mixin"]

    receive_id = fields.Many2one(
        "avea.stock.receive",
        string="Receive",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(related="receive_id.company_id")
    currency_id = fields.Many2one(related="receive_id.currency_id")
    partner_id = fields.Many2one(related="receive_id.partner_id")
    bill_id = fields.Many2one(related="receive_id.bill_id")
    amount_due = fields.Monetary(
        string="Balance due",
        currency_field="currency_id",
        compute="_compute_amount_due",
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Pay from",
        required=True,
        domain="[('id', 'in', available_journal_ids)]",
    )
    available_journal_ids = fields.Many2many(
        "account.journal",
        compute="_compute_available_journal_ids",
    )
    use_supplier_credit = fields.Boolean(
        string="Apply supplier credit",
    )
    supplier_credit_available = fields.Monetary(
        string="Supplier credit available",
        currency_field="currency_id",
        compute="_compute_supplier_credit_available",
    )
    has_supplier_credit = fields.Boolean(
        compute="_compute_supplier_credit_available",
    )
    use_store_credit = fields.Boolean(
        string="Pay with store credit",
    )
    store_credit_already_issued = fields.Boolean(
        string="Credit already issued",
    )
    store_credit_amount = fields.Monetary(
        string="Store credit amount",
        currency_field="currency_id",
    )
    store_credit_available = fields.Monetary(
        string="Store credit on account",
        currency_field="currency_id",
        compute="_compute_store_credit_available",
    )
    has_store_credit = fields.Boolean(
        compute="_compute_store_credit_available",
    )

    @api.depends("bill_id", "bill_id.amount_residual")
    def _compute_amount_due(self):
        for wizard in self:
            bill = wizard.bill_id
            wizard.amount_due = bill.amount_residual if bill else 0.0

    @api.depends("company_id")
    def _compute_available_journal_ids(self):
        for wizard in self:
            company = wizard.company_id
            wizard.available_journal_ids = (
                company._avea_expense_journals() if company else False
            )

    @api.depends("partner_id", "company_id")
    def _compute_supplier_credit_available(self):
        for wizard in self:
            partner = wizard.partner_id
            company = wizard.company_id
            available = (
                self._avea_supplier_credit_available(partner, company)
                if partner and company
                else 0.0
            )
            wizard.supplier_credit_available = available
            wizard.has_supplier_credit = available > 0.0

    @api.depends("partner_id")
    def _compute_store_credit_available(self):
        mixin = self.env["avea.stock.mixin"]
        for wizard in self:
            available = mixin._avea_partner_store_credit_balance(wizard.partner_id)
            wizard.store_credit_available = available
            wizard.has_store_credit = available > 0.0

    @api.onchange("use_store_credit")
    def _onchange_use_store_credit(self):
        if not self.use_store_credit:
            return
        balance = self.store_credit_available or 0.0
        self.store_credit_already_issued = balance > 0.0
        if self.currency_id.is_zero(self.store_credit_amount or 0.0):
            due = self.amount_due or 0.0
            self.store_credit_amount = min(due, balance) if balance else due

    def action_pay(self):
        self.ensure_one()
        receive = self.receive_id
        bill = receive.bill_id
        if not bill or receive.state != "done":
            raise UserError(_("There is no vendor bill to pay."))
        if bill.currency_id.is_zero(bill.amount_residual):
            raise UserError(_("This bill is already paid."))
        partner = receive.partner_id
        company = receive.company_id
        credit_applied = 0.0
        if self.use_supplier_credit:
            credit_applied = self._avea_apply_supplier_credits_to_bill(
                bill, partner, company
            )
        store_credit_applied = 0.0
        if self.use_store_credit:
            if bill.currency_id.compare_amounts(self.store_credit_amount or 0.0, 0.0) <= 0:
                raise UserError(
                    _("Enter the store credit amount used to pay this supplier.")
                )
            store_credit_applied = self._avea_apply_store_credit_to_vendor_bill(
                bill,
                partner,
                company,
                self.store_credit_amount,
                already_issued=self.store_credit_already_issued,
                pay_date=fields.Date.context_today(self),
                payment_ref=receive.invoice_number or bill.ref or bill.name,
            )
        bill.invalidate_recordset(["amount_residual", "payment_state"])
        paid_from_journal = self.journal_id
        if not bill.currency_id.is_zero(bill.amount_residual):
            if not self.journal_id or self.journal_id not in self.available_journal_ids:
                raise UserError(_("Choose a cash or bank account to pay from."))
            self._avea_pay_vendor_bill(
                bill,
                self.journal_id,
                partner,
                company,
                fields.Date.context_today(self),
                receive.invoice_number or bill.ref or bill.name,
            )
        elif not paid_from_journal:
            paid_from_journal = receive.paid_from_journal_id
        values = {
            "supplier_credit_applied": (receive.supplier_credit_applied or 0.0)
            + credit_applied,
            "store_credit_applied": (receive.store_credit_applied or 0.0)
            + store_credit_applied,
        }
        bill.invalidate_recordset(["amount_residual", "payment_state"])
        if bill.currency_id.is_zero(bill.amount_residual):
            values["mark_as_paid"] = True
        if paid_from_journal:
            values["paid_from_journal_id"] = paid_from_journal.id
        receive.write(values)
        return {"type": "ir.actions.act_window_close"}
