# -*- coding: utf-8 -*-
from odoo import _, fields, models


class AveaStockCountPlaceholder(models.TransientModel):
    """Placeholder until the dedicated Stock Count workspace ships."""

    _name = "avea.stock.count.placeholder"
    _description = "Avea Stock Count (Coming Soon)"

    note = fields.Html(
        default=lambda self: _(
            "<p>Stock Count will let you pick a category, count products on the shelf, "
            "and update Odoo inventory — without using stock adjustment screens.</p>"
            "<p>For now, use <strong>Receive Stock</strong> when goods arrive, "
            "or ask your administrator if you need a one-off inventory correction.</p>"
        ),
        readonly=True,
    )

    def action_open_receive_stock(self):
        return self.env["avea.stock.receive"].action_open_receive()
