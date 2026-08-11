from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    avea_credit_enabled = fields.Boolean(
        string="Customer Credit",
        default=True,
        help="Allow cashiers to accept Store Credit as a POS payment method.",
    )

    @api.model
    def _avea_credit_enable_all_pos_configs(self):
        configs = self.search([("avea_credit_enabled", "=", False)])
        if configs:
            configs.write({"avea_credit_enabled": True})
        return True

    @api.model_create_multi
    def create(self, vals_list):
        configs = super().create(vals_list)
        configs._avea_credit_on_configs_changed()
        return configs

    def write(self, vals):
        res = super().write(vals)
        if "avea_credit_enabled" in vals:
            self._avea_credit_on_configs_changed()
        return res

    def _avea_credit_on_configs_changed(self):
        enabled = self.filtered("avea_credit_enabled")
        if not enabled:
            return True
        enabled.company_id._avea_credit_ensure_accounting_setup()
        return True
