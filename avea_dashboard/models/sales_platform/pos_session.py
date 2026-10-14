# -*- coding: utf-8 -*-
from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def avea_load_pricelist_items_for_products(self, product_tmpl_ids, product_ids):
        """Load pricelist records/items for the given products (e.g. after selecting a platform)."""
        self.ensure_one()
        return self.get_pos_ui_product_pricelist_item_by_product(
            product_tmpl_ids or [],
            product_ids or [],
            self.config_id.id,
        )
