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
        bill.invalidate_recordset(["amount_residual", "payment_state"])
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
        receive.write(
            {
                "mark_as_paid": True,
                "paid_from_journal_id": self.journal_id.id,
                "supplier_credit_applied": (receive.supplier_credit_applied or 0.0)
                + credit_applied,
            }
        )
        return {"type": "ir.actions.act_window_close"}
