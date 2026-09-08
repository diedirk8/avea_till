"""Backfill Avea purchasing cost from existing variant standard prices."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    mixin = env["avea.stock.mixin"]
    templates = env["product.template"].search([("avea_cost_ex_tax", "=", 0)])
    updated = 0
    for template in templates:
        cost = template.standard_price or 0.0
        if cost:
            template.avea_cost_ex_tax = mixin._avea_round_supplier_cost(cost)
            updated += 1
    if updated:
        _logger.info(
            "Backfilled avea_cost_ex_tax for %s product templates from standard_price.",
            updated,
        )
