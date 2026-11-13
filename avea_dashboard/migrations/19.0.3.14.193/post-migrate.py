# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Set Apply on from product scope, then remap loyalty without deleting rewards."""
    cr.execute(
        """
        UPDATE avea_promotion
           SET apply_on = CASE
                WHEN deal_type IN ('percent_off', 'fixed_amount')
                 AND product_scope IN ('products', 'category')
                THEN 'product'
                ELSE 'ticket'
           END
        """
    )
    env = api.Environment(cr, SUPERUSER_ID, {})
    env.invalidate_all()
    promotions = env["avea.promotion"].with_context(active_test=False).search([])
    if promotions:
        promotions._sync_loyalty_program()
