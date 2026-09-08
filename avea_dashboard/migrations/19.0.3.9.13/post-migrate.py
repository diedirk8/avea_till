"""Backfill Sales Ledger product reference/name split."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env["pos.order.line"].search([])
    if not lines:
        return
    lines._compute_avea_product_display()
    _logger.info(
        "Recomputed Sales Ledger product reference/name for %s POS order lines.",
        len(lines),
    )
