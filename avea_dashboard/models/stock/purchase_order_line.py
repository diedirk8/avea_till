from odoo import fields, models

from .stock_mixin import AVEA_SUPPLIER_COST_PRECISION


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    price_unit = fields.Float(digits=AVEA_SUPPLIER_COST_PRECISION)
