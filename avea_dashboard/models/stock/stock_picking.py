from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    _rec_names_search = ["name", "avea_supplier_invoice_ref", "partner_id.name", "origin"]

    @api.model
    def search(self, domain, offset=0, limit=None, order=None):
        if order is None and self.env.context.get("avea_return_stock_receipt_order"):
            order = "date_done desc, id desc"
        return super().search(domain, offset=offset, limit=limit, order=order)

    avea_supplier_invoice_ref = fields.Char(
        string="Supplier invoice",
        compute="_compute_avea_supplier_invoice_ref",
        store=True,
        index=True,
    )

    @api.depends(
        "move_ids.purchase_line_id.order_id.partner_ref",
        "move_ids.purchase_line_id.order_id.invoice_ids.ref",
        "origin",
    )
    def _compute_avea_supplier_invoice_ref(self):
        for picking in self:
            picking.avea_supplier_invoice_ref = picking._avea_supplier_invoice_ref_value()

    def _avea_supplier_invoice_ref_value(self):
        self.ensure_one()
        order = self.move_ids.purchase_line_id.order_id[:1]
        if order and order.partner_ref:
            return order.partner_ref.strip()
        if order:
            bill = order.invoice_ids.filtered(
                lambda move: move.move_type == "in_invoice" and move.ref
            )[:1]
            if bill:
                return bill.ref.strip()
        if self.origin and self.origin not in (self.name or "",):
            return self.origin
        return False

    @api.depends("name", "partner_id", "avea_supplier_invoice_ref", "date_done", "state", "picking_type_code")
    def _compute_display_name(self):
        super()._compute_display_name()
        for picking in self:
            if picking.picking_type_code != "incoming" or picking.state != "done":
                continue
            parts = [picking.name]
            if picking.avea_supplier_invoice_ref:
                parts.append(picking.avea_supplier_invoice_ref)
            if picking.partner_id:
                parts.append(picking.partner_id.display_name)
            picking.display_name = " — ".join(parts)

    @api.model
    def _avea_find_receipt_for_return(self, invoice_number, partner=False, company=None):
        """Match a done incoming receipt by supplier invoice number."""
        term = (invoice_number or "").strip()
        if not term:
            return self.env["stock.picking"]
        company = company or self.env.company
        base_domain = [
            ("picking_type_code", "=", "incoming"),
            ("state", "=", "done"),
            ("company_id", "=", company.id),
        ]
        if partner:
            base_domain.append(("partner_id", "=", partner.id))

        def _prefer_exact(pickings):
            if not pickings:
                return pickings
            exact = pickings.filtered(
                lambda picking: (picking.avea_supplier_invoice_ref or "").lower() == term.lower()
            )
            return exact[:1] or pickings[:1]

        pickings = self.search(
            base_domain + [("avea_supplier_invoice_ref", "ilike", term)],
            order="date_done desc",
        )
        if pickings:
            return _prefer_exact(pickings)

        orders = self.env["purchase.order"].search(
            [
                ("company_id", "=", company.id),
                ("partner_ref", "ilike", term),
            ]
        )
        if orders:
            pickings = self.search(
                base_domain
                + [("move_ids.purchase_line_id.order_id", "in", orders.ids)],
                order="date_done desc",
            )
            if pickings:
                return _prefer_exact(pickings)

        bills = self.env["account.move"].search(
            [
                ("company_id", "=", company.id),
                ("move_type", "=", "in_invoice"),
                ("ref", "ilike", term),
            ],
            order="invoice_date desc",
        )
        if bills:
            po_ids = bills.mapped("invoice_line_ids.purchase_line_id.order_id").ids
            if po_ids:
                pickings = self.search(
                    base_domain
                    + [("move_ids.purchase_line_id.order_id", "in", po_ids)],
                    order="date_done desc",
                )
                if pickings:
                    return _prefer_exact(pickings)
        return self.env["stock.picking"]
