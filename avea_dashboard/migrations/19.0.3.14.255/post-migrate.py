# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Copy postage/courier vendor-bill lines onto existing receive charges."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    receives = env["avea.stock.receive"].search(
        [("state", "=", "done"), ("bill_id", "!=", False)]
    )
    receives._avea_sync_charges_from_bill()
