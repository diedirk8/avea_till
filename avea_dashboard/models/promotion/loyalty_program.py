from odoo import api, fields, models


class LoyaltyProgram(models.Model):
    _inherit = "loyalty.program"

    avea_is_combo = fields.Boolean(string="Avea Combo Price", default=False)
    avea_combo_price = fields.Float(string="Avea Combo Price", digits="Product Price")
    avea_combo_components = fields.Json(string="Avea Combo Components", default=list)
    avea_promotion_id = fields.Many2one("avea.promotion", ondelete="set null", copy=False)

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        fields_list += [
            "avea_is_combo",
            "avea_combo_price",
            "avea_combo_components",
            "avea_promotion_id",
        ]
        return fields_list
