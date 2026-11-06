"""Register sales platform pricelists on POS configs (existing installs)."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    env["avea.sales.platform"].search([])._avea_apply_pos_integration()
    _logger.info("Registered Avea sales platform pricelists on POS configs.")
