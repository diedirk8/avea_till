# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductPricelist(models.Model):
    _inherit = "product.pricelist"

    avea_sales_platform_id = fields.Many2one(
        "avea.sales.platform",
        string="Avea Sales Platform",
        ondelete="cascade",
        copy=False,
        index=True,
    )
