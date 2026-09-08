# -*- coding: utf-8 -*-
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .stock_mixin import AVEA_SUPPLIER_COST_PRECISION


class AveaStockReceiveCharge(models.Model):
    """Supplier invoice charges that stay on the bill as expenses.

    Not allocated into inventory / product cost. Future Landed Costs can pick
    these up separately via ``avea_additional_charge`` on the bill lines.
    """

    _name = "avea.stock.receive.charge"
    _description = "Receive Stock Additional Charge"
    _order = "id"

    receive_id = fields.Many2one(
        "avea.stock.receive",
        string="Receive Stock",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(related="receive_id.company_id", store=True)
    currency_id = fields.Many2one(related="receive_id.currency_id")
    name = fields.Char(
        string="Description",
        required=True,
        help="What this charge is for, e.g. Shipping, Handling, Packaging.",
    )
    amount = fields.Float(
        string="Amount EX Tax",
        digits=AVEA_SUPPLIER_COST_PRECISION,
        required=True,
        default=0.0,
        help="Charge amount excluding tax, matching supplier invoice lines.",
    )
    # Reserved for a future Landed Costs workflow. Always expense for now.
    charge_kind = fields.Selection(
        selection=[
            ("expense", "Expense (not in stock cost)"),
            ("landed_cost", "Landed cost candidate"),
        ],
        string="Charge kind",
        default="expense",
        required=True,
    )
    price_subtotal = fields.Monetary(
        string="Ex-tax",
        currency_field="currency_id",
        compute="_compute_charge_totals",
    )
    price_tax = fields.Monetary(
        string="Tax",
        currency_field="currency_id",
        compute="_compute_charge_totals",
    )
    price_total = fields.Monetary(
        string="Total",
        currency_field="currency_id",
        compute="_compute_charge_totals",
    )

    def _avea_charge_taxes(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        taxes = company.account_purchase_tax_id
        partner = self.receive_id.effective_partner_id
        fiscal_position = partner.with_company(company).property_account_position_id
        if fiscal_position and taxes:
            taxes = fiscal_position.map_tax(taxes)
        return taxes

    @api.depends(
        "amount",
        "currency_id",
        "receive_id.partner_id",
        "receive_id.add_new_supplier",
        "company_id",
    )
    def _compute_charge_totals(self):
        AccountTax = self.env["account.tax"]
        for charge in self:
            if not charge.currency_id or not charge.amount:
                charge.price_subtotal = 0.0
                charge.price_tax = 0.0
                charge.price_total = 0.0
                continue
            company = charge.company_id or self.env.company
            taxes = charge._avea_charge_taxes()
            base_line = AccountTax._prepare_base_line_for_taxes_computation(
                charge,
                tax_ids=taxes,
                quantity=1.0,
                partner_id=charge.receive_id.effective_partner_id,
                currency_id=charge.currency_id,
                price_unit=charge.amount,
                discount=0.0,
            )
            AccountTax._add_tax_details_in_base_line(base_line, company)
            AccountTax._round_base_lines_tax_details([base_line], company)
            charge.price_subtotal = base_line["tax_details"]["total_excluded_currency"]
            charge.price_total = base_line["tax_details"]["total_included_currency"]
            charge.price_tax = charge.price_total - charge.price_subtotal

    @api.constrains("amount")
    def _check_amount(self):
        for charge in self:
            if charge.amount < 0:
                raise ValidationError(_("Additional charge amounts cannot be negative."))
