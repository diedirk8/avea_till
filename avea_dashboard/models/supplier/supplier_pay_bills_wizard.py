# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AveaSupplierPayBillsWizard(models.TransientModel):
    _name = "avea.supplier.pay.bills.wizard"
    _description = "Pay Supplier Bills"

    partner_id = fields.Many2one(
        "res.partner",
        string="Supplier",
        required=True,
        domain="[('supplier_rank', '>', 0)]",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
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
    payment_ref = fields.Char(string="Reference")
    payment_amount = fields.Monetary(
        string="This payment",
        currency_field="currency_id",
        help="The amount that left the bank. Tick bills below and type how much "
        "each one should take. Extra stays on the supplier as paid on account.",
    )
    line_ids = fields.One2many(
        "avea.supplier.pay.bills.wizard.line",
        "wizard_id",
        string="Bills",
    )
    amount_total = fields.Monetary(
        string="Applied to bills",
        currency_field="currency_id",
        compute="_compute_amount_total",
    )
    amount_on_account = fields.Monetary(
        string="Left on supplier",
        currency_field="currency_id",
        compute="_compute_amount_total",
    )
    selected_count = fields.Integer(compute="_compute_amount_total")

    @api.depends("company_id")
    def _compute_available_journal_ids(self):
        for wizard in self:
            company = wizard.company_id
            wizard.available_journal_ids = (
                company.sudo()._avea_expense_journals() if company else False
            )

    @api.depends("line_ids.pay", "line_ids.amount", "payment_amount", "currency_id")
    def _compute_amount_total(self):
        for wizard in self:
            currency = wizard.currency_id or wizard.env.company.currency_id
            selected = wizard.line_ids.filtered(
                lambda line: line.pay
                and line.currency_id
                and line.currency_id.compare_amounts(line.amount or 0.0, 0.0) > 0
            )
            wizard.selected_count = len(selected)
            applied = currency.round(sum(selected.mapped("amount")))
            wizard.amount_total = applied
            payment = currency.round(wizard.payment_amount or 0.0)
            if currency.compare_amounts(payment, 0.0) > 0:
                wizard.amount_on_account = currency.round(max(payment - applied, 0.0))
            else:
                wizard.amount_on_account = 0.0

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        values.setdefault("company_id", self.env.company.id)
        values.setdefault("pay_date", fields.Date.context_today(self))
        partner = self.env["res.partner"].browse(
            values.get("partner_id") or self.env.context.get("default_partner_id")
        )
        if partner:
            values["partner_id"] = partner.id
        company = self.env["res.company"].browse(
            values.get("company_id") or self.env.company.id
        )
        if partner and "line_ids" in fields_list:
            values["line_ids"] = self._avea_line_commands(
                partner,
                company,
                preselect_bill_id=self.env.context.get("default_bill_id"),
            )
        return values

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        for wizard in wizards:
            if wizard.partner_id and not wizard.line_ids:
                wizard.line_ids = wizard._avea_line_commands(
                    wizard.partner_id,
                    wizard.company_id,
                    preselect_bill_id=self.env.context.get("default_bill_id"),
                )
        return wizards

    def _avea_open_bills(self, partner, company):
        return self.env["account.move"].search(
            [
                ("partner_id", "=", partner.id),
                ("company_id", "=", company.id),
                ("move_type", "=", "in_invoice"),
                ("state", "=", "posted"),
                ("amount_residual", "!=", 0),
            ],
            order="invoice_date_due, invoice_date, id",
        )

    def _avea_line_commands(self, partner, company, preselect_bill_id=None):
        commands = []
        for bill in self._avea_open_bills(partner, company):
            selected = bool(preselect_bill_id and bill.id == preselect_bill_id)
            commands.append(
                (
                    0,
                    0,
                    {
                        "bill_id": bill.id,
                        "pay": selected,
                        "amount": bill.amount_residual if selected else 0.0,
                    },
                )
            )
        return commands

    @api.onchange("partner_id", "company_id")
    def _onchange_partner_id(self):
        self.line_ids = [(5, 0, 0)]
        if not self.partner_id or not self.company_id:
            return
        self.line_ids = self._avea_line_commands(
            self.partner_id,
            self.company_id,
            preselect_bill_id=self.env.context.get("default_bill_id"),
        )
        self._avea_auto_allocate()

    @api.onchange("payment_amount")
    def _onchange_payment_amount(self):
        self._avea_auto_allocate()

    def _avea_auto_allocate(self):
        """Fill Pay now from the oldest open bill until this payment is used."""
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        if not self.line_ids or currency.compare_amounts(self.payment_amount or 0.0, 0.0) <= 0:
            return
        bills = self.line_ids.mapped("bill_id")
        allocated, _leftover = self.env["avea.stock.mixin"]._avea_allocate_oldest_first(
            bills, self.payment_amount, currency
        )
        amount_by_bill = {bill.id: amount for bill, amount in allocated}
        for line in self.line_ids:
            amount = amount_by_bill.get(line.bill_id.id, 0.0)
            line.amount = amount
            line.pay = bool(currency.compare_amounts(amount, 0.0) > 0)

    def action_pay(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("Choose the supplier you paid."))
        selected = self.line_ids.filtered(
            lambda line: line.pay
            and line.currency_id
            and line.currency_id.compare_amounts(line.amount or 0.0, 0.0) > 0
        )
        currency = self.currency_id or self.env.company.currency_id
        payment_amount = currency.round(self.payment_amount or 0.0)
        if not selected and currency.compare_amounts(payment_amount, 0.0) <= 0:
            raise UserError(
                _(
                    "Enter the amount that left the bank, or tick the bills "
                    "this payment should cover."
                )
            )
        allowed = self.company_id.sudo()._avea_expense_journals()
        if not self.journal_id or self.journal_id not in allowed:
            raise UserError(_("Choose a cash or bank account to pay from."))
        allocations = []
        for line in selected:
            bill = line.bill_id.sudo()
            if bill.move_type != "in_invoice" or bill.state != "posted":
                raise UserError(_("Choose posted supplier bills."))
            if bill.partner_id != self.partner_id:
                raise UserError(_("Those bills are not all for this supplier."))
            allocations.append((bill, line.amount))
        statement_line = self.env["avea.stock.mixin"]._avea_pay_vendor_bills(
            allocations,
            self.journal_id,
            self.partner_id,
            self.company_id,
            self.pay_date or fields.Date.context_today(self),
            self.payment_ref,
            payment_amount=payment_amount if currency.compare_amounts(payment_amount, 0.0) > 0 else None,
        )
        for bill, _amount in allocations:
            receive = bill.avea_linked_receive_id
            if not receive:
                continue
            bill.invalidate_recordset(["amount_residual", "payment_state"])
            values = {"paid_from_journal_id": self.journal_id.id}
            if bill.currency_id.is_zero(bill.amount_residual):
                values["mark_as_paid"] = True
            receive.sudo().write(values)
        self.partner_id.invalidate_recordset()
        if not statement_line:
            return self.env["account.bank.statement.line"].action_avea_open_payments()
        return statement_line.with_context(
            avea_supplier_workspace=True
        ).get_formview_action()


class AveaSupplierPayBillsWizardLine(models.TransientModel):
    _name = "avea.supplier.pay.bills.wizard.line"
    _description = "Pay Supplier Bills Line"
    _order = "id"

    wizard_id = fields.Many2one(
        "avea.supplier.pay.bills.wizard",
        required=True,
        ondelete="cascade",
    )
    bill_id = fields.Many2one(
        "account.move",
        string="Bill",
        required=True,
        ondelete="cascade",
        domain="[('move_type', '=', 'in_invoice'), ('state', '=', 'posted')]",
    )
    currency_id = fields.Many2one(related="bill_id.currency_id")
    bill_date = fields.Date(related="bill_id.invoice_date")
    bill_due = fields.Date(related="bill_id.invoice_date_due")
    bill_label = fields.Char(related="bill_id.avea_supplier_bill_label")
    bill_ref = fields.Char(related="bill_id.ref")
    amount_due = fields.Monetary(
        string="Still open",
        currency_field="currency_id",
        related="bill_id.amount_residual",
    )
    pay = fields.Boolean(string="Pay")
    amount = fields.Monetary(
        string="Amount",
        currency_field="currency_id",
    )

    @api.onchange("pay")
    def _onchange_pay(self):
        for line in self:
            if line.pay and line.currency_id and line.currency_id.is_zero(line.amount or 0.0):
                line.amount = line.amount_due
            if not line.pay:
                line.amount = 0.0

    @api.onchange("amount")
    def _onchange_amount(self):
        for line in self:
            if not line.currency_id:
                continue
            if line.currency_id.compare_amounts(line.amount or 0.0, 0.0) > 0:
                line.pay = True
            elif line.currency_id.is_zero(line.amount or 0.0):
                line.pay = False
