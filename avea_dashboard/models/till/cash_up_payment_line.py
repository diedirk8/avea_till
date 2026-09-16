from odoo import fields, models


class AveaCashUpPaymentLine(models.Model):
    _name = "avea.cash.up.payment.line"
    _description = "Cash Up Payment Reconciliation Line"
    _order = "sequence, id"

    cash_up_id = fields.Many2one(
        "avea.cash.up",
        string="Cash Up",
        required=True,
        ondelete="cascade",
        index=True,
    )
    payment_kind = fields.Selection(
        selection=[
            ("cash", "Cash"),
            ("card", "Card"),
            ("eft", "EFT"),
            ("store_credit", "Store Credit"),
            ("other", "Other"),
        ],
        string="Payment Method",
        required=True,
    )
    sequence = fields.Integer(default=10)
    expected = fields.Monetary(currency_field="currency_id")
    counted = fields.Monetary(currency_field="currency_id")
    difference = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="cash_up_id.currency_id", store=True)
