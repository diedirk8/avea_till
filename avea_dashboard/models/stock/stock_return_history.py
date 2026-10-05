from odoo import _, api, fields, models


class AveaStockReturnHistoryLine(models.Model):
    _name = "avea.stock.return.history.line"
    _description = "Return Stock History Line"
    _order = "id"

    history_id = fields.Many2one(
        "avea.stock.return.history",
        string="Return",
        required=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one("product.product", string="Product", required=True)
    quantity = fields.Float(string="Quantity returned", digits="Product Unit", required=True)
    move_id = fields.Many2one("stock.move", string="Original move", ondelete="set null")
    currency_id = fields.Many2one(related="history_id.currency_id")


class AveaStockReturnHistory(models.Model):
    _name = "avea.stock.return.history"
    _description = "Return Stock History"
    _inherit = ["avea.stock.mixin"]
    _order = "return_date desc, id desc"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Returned by",
        required=True,
        default=lambda self: self.env.user,
    )
    partner_id = fields.Many2one("res.partner", string="Supplier", required=True)
    receipt_picking_id = fields.Many2one(
        "stock.picking",
        string="Original receipt",
        required=True,
        ondelete="restrict",
    )
    return_picking_id = fields.Many2one(
        "stock.picking",
        string="Return transfer",
        ondelete="set null",
    )
    credit_id = fields.Many2one(
        "account.move",
        string="Vendor credit note",
        ondelete="set null",
    )
    invoice_number = fields.Char(string="Supplier invoice")
    return_date = fields.Date(string="Return date", required=True)
    line_ids = fields.One2many(
        "avea.stock.return.history.line",
        "history_id",
        string="Products",
    )
    product_count = fields.Integer(compute="_compute_totals")
    quantity_total = fields.Float(
        string="Total quantity",
        digits="Product Unit",
        compute="_compute_totals",
    )
    credit_total = fields.Monetary(
        string="Credit amount",
        currency_field="currency_id",
        compute="_compute_credit_total",
    )
    credit_residual = fields.Monetary(
        string="Credit still available",
        currency_field="currency_id",
        compute="_compute_credit_total",
    )
    summary = fields.Char(compute="_compute_summary")

    @api.depends("line_ids.product_id", "line_ids.quantity")
    def _compute_totals(self):
        for history in self:
            lines = history.line_ids
            history.product_count = len(lines)
            history.quantity_total = sum(lines.mapped("quantity"))

    @api.depends("credit_id", "credit_id.amount_total", "credit_id.amount_residual")
    def _compute_credit_total(self):
        for history in self:
            credit = history.credit_id
            if not credit:
                history.credit_total = 0.0
                history.credit_residual = 0.0
                continue
            history.credit_total = abs(credit.amount_total)
            history.credit_residual = abs(credit.amount_residual)

    @api.depends("partner_id", "receipt_picking_id", "return_date", "product_count")
    def _compute_summary(self):
        for history in self:
            history.summary = _(
                "%(supplier)s — %(receipt)s — %(count)s product(s)",
                supplier=history.partner_id.display_name or "",
                receipt=history.receipt_picking_id.name or "",
                count=history.product_count,
            )

    def action_open_return_transfer(self):
        self.ensure_one()
        if not self.return_picking_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Return transfer"),
            "res_model": "stock.picking",
            "view_mode": "form",
            "res_id": self.return_picking_id.id,
            "target": "new",
        }

    def action_open_credit_note(self):
        self.ensure_one()
        if not self.credit_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Vendor credit note"),
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.credit_id.id,
            "target": "new",
        }

    def action_open_original_receipt(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Receipt"),
            "res_model": "stock.picking",
            "view_mode": "form",
            "res_id": self.receipt_picking_id.id,
            "target": "new",
        }

    @api.model
    def action_open_history(self):
        view_id = self.env.ref("avea_till.view_avea_stock_return_history_list").id
        return {
            "type": "ir.actions.act_window",
            "name": _("Return history"),
            "res_model": self._name,
            "view_mode": "list,form",
            "views": [(view_id, "list"), (False, "form")],
            "target": "main",
            "context": {"clear_breadcrumbs": True},
        }
