# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Remap existing promotions so product-scoped amount-off applies per unit."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    promotions = env["avea.promotion"].with_context(active_test=False).search([])
    if promotions:
        promotions._sync_loyalty_program()
