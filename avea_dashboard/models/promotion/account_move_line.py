# Part of Avea. See LICENSE file for full copyright and licensing details.

from odoo import models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _get_discount_lines(self):
        """Treat Avea Combo Price discount lines like native loyalty discounts."""
        lines = super()._get_discount_lines()
        discount_line_ids = []
        for line in self - lines:
            pos_orders = line.move_id.sudo().pos_order_ids
            if not pos_orders:
                continue
            combo_products = pos_orders.lines.filtered("avea_combo_program_id").product_id
            if line.product_id in combo_products:
                discount_line_ids.append(line.id)
        if discount_line_ids:
            lines |= self.browse(discount_line_ids)
        return lines
