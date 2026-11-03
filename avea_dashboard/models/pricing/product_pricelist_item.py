# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductPricelistItem(models.Model):
    _inherit = "product.pricelist.item"

    avea_layer = fields.Selection(
        selection=[
            ("1_base", "1. All products"),
            ("2_category", "2. Category"),
            ("3_product", "3. Product"),
            ("4_variant", "4. Variant"),
        ],
        string="Level",
        compute="_compute_avea_layer",
        help=(
            "More specific rows win. Keep an All products rule as the default, "
            "then add a Category or Product row for exceptions."
        ),
    )

    @api.depends("applied_on")
    def _compute_avea_layer(self):
        mapping = {
            "3_global": "1_base",
            "2_product_category": "2_category",
            "1_product": "3_product",
            "0_product_variant": "4_variant",
        }
        for item in self:
            item.avea_layer = mapping.get(item.applied_on, "1_base")
