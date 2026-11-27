# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Re-apply Apply on after a stale ORM cache left product deals on ticket total."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env.invalidate_all()
    promotions = env["avea.promotion"].with_context(active_test=False).search([])
    product_promos = promotions.filtered(
        lambda promo: promo.deal_type in ("percent_off", "fixed_amount")
        and promo.product_scope in ("products", "category")
    )
    ticket_promos = promotions - product_promos
    if product_promos:
        product_promos.write({"apply_on": "product"})
    if ticket_promos:
        ticket_promos.write({"apply_on": "ticket"})
