# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AveaSupplierBillPayWizard(models.TransientModel):
    _name = "avea.supplier.bill.pay.wizard"
    _description = "Record Supplier Bill Payment"

    bill_id = fields.Many2one(
        "account.move",
        string="Bill",
        required=True,
        ondelete="cascade",
        domain="[('move_type', '=', 'in_invoice')]",
    )
    company_id = fields.Many2one(related="bill_id.company_id")
    currency_id = fields.Many2one(related="bill_id.currency_id")
    partner_id = fields.Many2one(related="bill_id.partner_id")
    bill_label = fields.Char(related="bill_id.avea_supplier_bill_label")
    amount_due = fields.Monetary(
        string="Still open",
        currency_field="currency_id",
        compute="_compute_amount_due",
    )
    amount = fields.Monetary(
        string="Amount paid",
        currency_field="currency_id",
        required=True,
    )
    pay_date = fields.Date(
        string="Paid on",
        required=True,
        default=fields.Date.context_today,
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Pay from",
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
                company.sudo()._avea_expense_journals() if company else False
            )

    @api.depends("partner_id", "company_id")
    def _compute_supplier_credit_available(self):
        for wizard in self:
            partner = wizard.partner_id
            company = wizard.company_id
            available = (
                self.env["avea.stock.mixin"]._avea_supplier_credit_available(
                    partner, company
                )
                if partner and company
                else 0.0
            )
            wizard.supplier_credit_available = available
            wizard.has_supplier_credit = available > 0.0

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        bill = self.env["account.move"].browse(
            values.get("bill_id") or self.env.context.get("default_bill_id")
        )
        if bill:
            values.setdefault("amount", bill.amount_residual)
            values.setdefault("pay_date", fields.Date.context_today(self))
            journals = (
                bill.company_id.sudo()._avea_expense_journals()
                if bill.company_id
                else self.env["account.journal"]
            )
            default_journal = journals.filtered(
                lambda journal: journal.type == "cash"
            )[:1] or journals[:1]
            if default_journal:
                values.setdefault("journal_id", default_journal.id)
        return values

    def action_pay(self):
        self.ensure_one()
        bill = self.bill_id.sudo()
        if bill.move_type != "in_invoice" or bill.state != "posted":
            raise UserError(_("This is not a posted supplier bill."))
        if bill.currency_id.is_zero(bill.amount_residual):
            raise UserError(_("This bill is already paid."))
        partner = bill.partner_id
        company = bill.company_id
        credit_applied = 0.0
        if self.use_supplier_credit:
            credit_applied = self.env["avea.stock.mixin"]._avea_apply_supplier_credits_to_bill(
                bill, partner, company
            )
            bill.invalidate_recordset(["amount_residual", "payment_state"])
        remaining = bill.amount_residual
        if not bill.currency_id.is_zero(remaining):
            pay_amount = bill.currency_id.round(self.amount or 0.0)
            if bill.currency_id.compare_amounts(pay_amount, 0.0) <= 0:
                raise UserError(_("Enter the amount you paid."))
            if bill.currency_id.compare_amounts(pay_amount, remaining) > 0:
                pay_amount = remaining
            allowed = self.company_id.sudo()._avea_expense_journals()
            if not self.journal_id or self.journal_id not in allowed:
                raise UserError(_("Choose a cash or bank account to pay from."))
            self.env["avea.stock.mixin"]._avea_pay_vendor_bill(
                bill,
                self.journal_id,
                partner,
                company,
                self.pay_date or fields.Date.context_today(self),
                bill.ref or bill.name,
                amount=pay_amount,
            )
        receive = bill.avea_linked_receive_id
        if receive:
            values = {}
            bill.invalidate_recordset(["amount_residual", "payment_state"])
            if bill.currency_id.is_zero(bill.amount_residual):
                values["mark_as_paid"] = True
            if self.journal_id:
                values["paid_from_journal_id"] = self.journal_id.id
            if credit_applied:
                values["supplier_credit_applied"] = (
                    receive.supplier_credit_applied or 0.0
                ) + credit_applied
            if values:
                receive.sudo().write(values)
        partner.invalidate_recordset()
        return partner.action_avea_open_supplier()
