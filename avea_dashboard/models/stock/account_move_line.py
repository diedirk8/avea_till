# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    # Marks vendor-bill lines created from Receive Stock additional charges.
    # Kept as expense today; a future Landed Costs feature can select these.
    avea_additional_charge = fields.Boolean(
        string="Avea additional charge",
        default=False,
        copy=False,
        help="True when this bill line came from Receive Stock additional charges "
        "(not allocated into inventory cost).",
    )
