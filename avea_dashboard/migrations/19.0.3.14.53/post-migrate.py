"""Refresh customer visit rhythm after gap and label rule changes."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    partners = env["res.partner"].search([("customer_rank", ">", 0)])
    if not partners:
        return
    partners._compute_avea_visit_pattern()
    _logger.info(
        "Avea customer visit rhythm recomputed for %s customer(s).",
        len(partners),
    )
