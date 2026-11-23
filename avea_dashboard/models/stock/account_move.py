# -*- coding: utf-8 -*-
from odoo import models


class AccountMoveStockReceive(models.Model):
    _inherit = "account.move"

    def action_post(self):
        result = super().action_post()
        bills = self.filtered(lambda move: move.move_type == "in_invoice")
        if bills:
            receives = (
                self.env["avea.stock.receive"]
                .sudo()
                .search([("state", "=", "done"), ("bill_id", "in", bills.ids)])
            )
            receives._avea_sync_charges_from_bill()
        return result
