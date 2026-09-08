from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    avea_order_date = fields.Datetime(
        string="Sale date",
        related="order_id.date_order",
        store=True,
        index=True,
        readonly=True,
    )
    avea_order_partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        related="order_id.partner_id",
        store=True,
        index=True,
        readonly=True,
    )
    avea_order_reference = fields.Char(
        string="Order #",
        compute="_compute_avea_order_reference",
        store=True,
        index=True,
        readonly=True,
    )
    avea_product_display = fields.Char(
        string="Product name",
        compute="_compute_avea_product_display",
        store=True,
        index=True,
        readonly=True,
    )

    @api.depends("order_id.pos_reference", "order_id.name")
    def _compute_avea_order_reference(self):
        for line in self:
            order = line.order_id
            if not order:
                line.avea_order_reference = False
                continue
            reference = order._avea_till_display_reference()
            line.avea_order_reference = reference or str(order.id)

    @api.depends("full_product_name", "product_id.display_name")
    def _compute_avea_product_display(self):
        for line in self:
            line.avea_product_display = (
                line.full_product_name
                or line.product_id.display_name
                or line.product_id.name
                or ""
            )

    @api.model
    def _avea_sales_ledger_domain(self):
        """Completed POS sale lines across all sessions (source: pos.order.line)."""
        paid_states = self.env["pos.session"]._avea_paid_order_states()
        return [
            ("order_id.state", "in", paid_states),
            ("product_id", "!=", False),
            ("product_id.type", "not in", ("service", "combo")),
            ("combo_line_ids", "=", False),
            ("qty", "!=", 0.0),
        ]

    @api.model
    def _avea_sales_ledger_search_domain(self, *, product=None, customer=None, order_ref=None, date_from=None, date_to=None):
        """Build filter domain for tests and programmatic search."""
        domain = list(self._avea_sales_ledger_domain())
        if product:
            domain += [
                "|",
                ("product_id", "ilike", product),
                ("full_product_name", "ilike", product),
            ]
        if customer:
            domain.append(("avea_order_partner_id", "ilike", customer))
        if order_ref:
            domain += [
                "|",
                ("avea_order_reference", "ilike", order_ref),
                ("order_id.name", "ilike", order_ref),
            ]
        if date_from:
            domain.append(("avea_order_date", ">=", date_from))
        if date_to:
            domain.append(("avea_order_date", "<=", date_to))
        return domain

    def action_avea_open_pos_order(self):
        self.ensure_one()
        order = self.order_id
        if not order:
            raise UserError(_("This sale line is not linked to an order."))
        return {
            "type": "ir.actions.act_window",
            "name": _("POS Order"),
            "res_model": "pos.order",
            "res_id": order.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    @api.model
    def action_avea_open_sales_ledger(self):
        """Open the global Sales Ledger with the standard completed-sale domain."""
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "avea_till.action_avea_sales_ledger_window"
        )
        action["domain"] = self._avea_sales_ledger_domain()
        return action
