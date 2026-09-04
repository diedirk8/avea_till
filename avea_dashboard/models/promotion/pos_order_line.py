from odoo import api, fields, models


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    avea_combo_program_id = fields.Integer(
        string="Avea Combo Program",
        help="Loyalty program id for an Avea Combo Price discount line.",
        copy=False,
    )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        fields_list.append("avea_combo_program_id")
        return fields_list
