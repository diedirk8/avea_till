from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


class AveaStockReturnLine(models.TransientModel):
    _name = "avea.stock.return.line"
    _description = "Return Stock Line"
    _order = "id"

    return_id = fields.Many2one(
        "avea.stock.return",
        string="Return Stock",
        required=True,
        ondelete="cascade",
    )
    move_id = fields.Many2one(
        "stock.move",
        string="Stock Move",
        required=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        readonly=True,
    )
    qty_received = fields.Float(
        string="Received",
        digits="Product Unit",
        readonly=True,
    )
    qty_available = fields.Float(
        string="Available to return",
        digits="Product Unit",
        readonly=True,
    )
    quantity = fields.Float(
        string="Quantity to return",
        digits="Product Unit",
        required=True,
        default=0.0,
    )
    currency_id = fields.Many2one(related="return_id.currency_id")


class AveaStockReturn(models.TransientModel):
    _name = "avea.stock.return"
    _description = "Return Stock"
    _inherit = ["avea.stock.mixin"]

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    picking_id = fields.Many2one(
        "stock.picking",
        string="Receipt",
        domain=(
            "[('picking_type_code', '=', 'incoming'), "
            "('state', '=', 'done'), "
            "('company_id', '=', company_id)]"
        ),
    )
    partner_id = fields.Many2one(
        related="picking_id.partner_id",
        string="Supplier",
    )
    receipt_date = fields.Datetime(
        related="picking_id.date_done",
        string="Received on",
    )
    invoice_number = fields.Char(
        compute="_compute_invoice_number",
    )
    line_ids = fields.One2many(
        "avea.stock.return.line",
        "return_id",
        string="Products",
    )
    return_date = fields.Date(
        string="Return date",
        required=True,
        default=fields.Date.context_today,
    )

    @api.depends("picking_id")
    def _compute_invoice_number(self):
        for wizard in self:
            picking = wizard.picking_id
            if not picking:
                wizard.invoice_number = False
                continue
            order = picking.move_ids.purchase_line_id.order_id[:1]
            wizard.invoice_number = order.partner_ref or picking.origin or picking.name

    @api.onchange("picking_id")
    def _onchange_picking_id(self):
        self.line_ids = [Command.clear()]
        if not self.picking_id:
            return
        commands = []
        for move in self.picking_id.move_ids.filtered(lambda move: move.state == "done"):
            available = self._avea_qty_available_to_return(move)
            if float_is_zero(available, precision_rounding=move.product_uom.rounding):
                continue
            commands.append(
                Command.create(
                    {
                        "move_id": move.id,
                        "product_id": move.product_id.id,
                        "qty_received": move.quantity,
                        "qty_available": available,
                        "quantity": 0.0,
                    }
                )
            )
        self.line_ids = commands

    @api.model
    def _avea_qty_available_to_return(self, move):
        quantity = move.quantity
        for dest in move.move_dest_ids:
            if not dest.origin_returned_move_id or dest.origin_returned_move_id != move:
                continue
            if dest.state == "cancel":
                continue
            quantity -= dest.quantity
        return move.product_uom.round(quantity)

    @api.model
    def action_open_return(self):
        wizard = self.create({})
        return {
            "type": "ir.actions.act_window",
            "name": _("Return Stock"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": wizard.id,
            "view_id": self.env.ref("avea_till.view_avea_stock_return_form").id,
            "target": "current",
            "context": {"clear_breadcrumbs": True},
        }

    def action_open_receive(self):
        return self.env["avea.stock.receive"].action_open_receive()

    def action_return_stock(self):
        self.ensure_one()
        lines = self._avea_return_lines()
        return_picking = self._avea_create_return_picking(lines)
        self._avea_complete_picking(return_picking, date_done=self.return_date)
        credit = self._avea_create_supplier_credit(lines)
        return self._avea_success(return_picking, credit)

    def _avea_return_lines(self):
        self.ensure_one()
        if not self.picking_id:
            raise ValidationError(_("Choose the receipt to return."))
        lines = self.line_ids.filtered(lambda line: line.quantity > 0)
        if not lines:
            raise ValidationError(_("Enter the quantity to return for at least one product."))
        for line in lines:
            rounding = line.move_id.product_uom.rounding
            if float_compare(line.quantity, line.qty_available, precision_rounding=rounding) > 0:
                raise ValidationError(
                    _(
                        "You can return at most %(available)s of %(product)s.",
                        available=line.qty_available,
                        product=line.product_id.display_name,
                    )
                )
        return lines

    def _avea_create_return_picking(self, lines):
        self.ensure_one()
        picking = self.picking_id.sudo()
        ReturnWizard = (
            self.env["stock.return.picking"]
            .sudo()
            .with_context(
                active_id=picking.id,
                active_ids=picking.ids,
                active_model="stock.picking",
            )
        )
        wizard = ReturnWizard.create({"picking_id": picking.id})
        qty_by_move = {line.move_id.id: line.quantity for line in lines}
        for return_line in wizard.product_return_moves:
            return_line.quantity = qty_by_move.get(return_line.move_id.id, 0.0)
            if "to_refund" in return_line._fields:
                return_line.to_refund = True
        return_picking = wizard._create_return()
        if "to_refund" in return_picking.move_ids._fields:
            return_picking.move_ids.write({"to_refund": True})
        return return_picking

    def _avea_create_supplier_credit(self, lines):
        self.ensure_one()
        order = self.picking_id.sudo().move_ids.purchase_line_id.order_id[:1]
        if not order:
            return self.env["account.move"]
        credit_lines = []
        for line in lines:
            po_line = line.move_id.purchase_line_id
            if not po_line:
                continue
            credit_lines.append(
                Command.create(
                    {
                        "product_id": line.product_id.id,
                        "name": line.product_id.display_name,
                        "quantity": line.quantity,
                        "price_unit": po_line.price_unit,
                        "tax_ids": [Command.set(po_line.tax_ids.ids)],
                        "purchase_line_id": po_line.id,
                        "display_type": "product",
                    }
                )
            )
        if not credit_lines:
            return self.env["account.move"]
        journal = self.env["account.journal"].sudo().search(
            [
                ("type", "=", "purchase"),
                ("company_id", "=", self.company_id.id),
            ],
            limit=1,
        )
        credit_vals = {
            "move_type": "in_refund",
            "partner_id": (self.partner_id or order.partner_id).id,
            "invoice_date": self.return_date,
            "date": self.return_date,
            "ref": self.invoice_number or order.partner_ref,
            "invoice_origin": order.name,
            "company_id": self.company_id.id,
            "currency_id": self.currency_id.id,
            "invoice_line_ids": credit_lines,
        }
        if journal:
            credit_vals["journal_id"] = journal.id
        credit = (
            self.env["account.move"]
            .sudo()
            .with_company(self.company_id)
            .with_context(default_move_type="in_refund")
            .create(credit_vals)
        )
        if credit.state == "draft":
            credit.sudo().action_post()
        return credit

    def _avea_success(self, return_picking, credit):
        if credit:
            message = _(
                "Stock has been returned to %(supplier)s. Credit note %(credit)s.",
                supplier=self.partner_id.display_name or _("the supplier"),
                credit=credit.name,
            )
        else:
            message = _(
                "Stock has been returned%(supplier)s.",
                supplier=(
                    _(" to %s") % self.partner_id.display_name
                    if self.partner_id
                    else ""
                ),
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Stock returned"),
                "message": message,
                "type": "success",
                "next": self.action_open_return(),
            },
        }
