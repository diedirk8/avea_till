"""Assign Avea role profiles to existing POS users."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    env["res.users"]._avea_assign_default_roles()
    _logger.info("Assigned default Avea Owner/Manager/Cashier role profiles.")
