"""Backfill Receive history from Avea purchase orders."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    created = env["avea.stock.receive"]._avea_backfill_receive_history()
    _logger.info("Avea Receive history backfill: %s row(s) created.", created)
