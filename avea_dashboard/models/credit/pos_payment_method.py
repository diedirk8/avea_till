from odoo import fields, models


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    is_avea_store_credit = fields.Boolean(
        string="Store Credit Payment",
        help="Use this payment method for Customer Credit redemptions in the POS.",
    )

    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        if config.avea_credit_enabled:
            fields_list = fields_list + ["is_avea_store_credit"]
        return fields_list
