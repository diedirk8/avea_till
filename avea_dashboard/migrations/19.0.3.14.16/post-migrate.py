"""Link receive history rows to stock receipts and refresh receipt labels."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    Receive = env["avea.stock.receive"]
    updated = Receive._avea_sync_missing_picking_links()
    Receive.search([("state", "=", "done")])._compute_receipt_display()
    _logger.info("Avea Receive history receipt links: %s row(s) updated.", updated)
