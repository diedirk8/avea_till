# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    avea_sales_platform_pricelist_by_partner_id = fields.Json(
        string="Sales platform pricelists (POS)",
        compute="_compute_avea_sales_platform_pricelist_by_partner_id",
        help="Map of platform partner id → platform pricelist id for the POS client.",
    )

    @api.depends("company_id")
    def _compute_avea_sales_platform_pricelist_by_partner_id(self):
        Platform = self.env["avea.sales.platform"].sudo()
        for config in self:
            mapping = {}
            for platform in Platform.search(
                [
                    ("active", "=", True),
                    ("company_id", "=", config.company_id.id),
                    ("partner_id", "!=", False),
                    ("pricelist_id", "!=", False),
                ]
            ):
                mapping[str(platform.partner_id.id)] = platform.pricelist_id.id
            config.avea_sales_platform_pricelist_by_partner_id = mapping

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        extra = ["avea_sales_platform_pricelist_by_partner_id"]
        if fields_list:
            return fields_list + [field for field in extra if field not in fields_list]
        return fields_list

    def _avea_register_sales_platform_pricelist(self, pricelist):
        """Expose a platform pricelist on this till so partner selection can apply it."""
        self.ensure_one()
        if not pricelist:
            return
        vals = {}
        if pricelist not in self.available_pricelist_ids:
            vals["available_pricelist_ids"] = [(4, pricelist.id)]
        if not self.use_pricelist:
            vals["use_pricelist"] = True
        if vals:
            self.write(vals)
