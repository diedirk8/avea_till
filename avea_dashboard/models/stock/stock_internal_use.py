from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero

from .stock_mixin import AVEA_INTERNAL_USE_ORIGIN


class AveaStockInternalUseLine(models.TransientModel):
    _name = "avea.stock.internal_use.line"
    _description = "Use Stock Line"
    _order = "id"

    use_id = fields.Many2one(
        "avea.stock.internal_use",
        string="Use Stock",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(related="use_id.company_id")
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        domain="[('is_storable', '=', True)]",
    )
    product_tracking = fields.Selection(related="product_id.tracking")
    lot_id = fields.Many2one(
        "stock.lot",
        string="Lot / serial",
        domain="[('product_id', '=', product_id)]",
        check_company=True,
    )
    quantity = fields.Float(
        string="Quantity",
        digits="Product Unit",
        required=True,
        default=1.0,
    )
    qty_available = fields.Float(
        string="On hand",
        digits="Product Unit",
        compute="_compute_qty_available",
    )

    @api.depends("product_id", "lot_id", "use_id.location_id", "company_id")
    def _compute_qty_available(self):
        for line in self:
            if not line.product_id or not line.use_id.location_id:
                line.qty_available = 0.0
                continue
            line.qty_available = line.product_id.with_context(
                location=line.use_id.location_id.id,
                lot_id=line.lot_id.id if line.lot_id else False,
            ).qty_available

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for line in self:
            line.lot_id = False

class AveaStockInternalUse(models.TransientModel):
    _name = "avea.stock.internal_use"
    _description = "Use Stock"
    _inherit = ["avea.stock.mixin"]

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    location_id = fields.Many2one(
        "stock.location",
        string="From location",
        required=True,
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_id)]",
        compute="_compute_location_id",
        store=True,
        readonly=False,
        precompute=True,
    )
    use_date = fields.Date(
        string="Date",
        required=True,
        default=fields.Date.context_today,
    )
    notes = fields.Char(
        string="Notes",
        help="Optional reference, e.g. demo cage or staff feeding.",
    )
    reason_tag_ids = fields.Many2many(
        "stock.scrap.reason.tag",
        string="Reason",
        help="Same reason tags as Odoo inventory scrap / internal use.",
    )
    line_ids = fields.One2many(
        "avea.stock.internal_use.line",
        "use_id",
        string="Products",
    )

    @api.depends("company_id")
    def _compute_location_id(self):
        for wizard in self:
            if wizard.location_id and wizard.location_id.company_id == wizard.company_id:
                continue
            wizard.location_id = self._avea_default_stock_location(wizard.company_id)

    @api.model
    def _avea_form_action(self, wizard):
        view_id = self.env.ref("avea_till.view_avea_stock_internal_use_form").id
        return {
            "type": "ir.actions.act_window",
            "name": _("Use Stock"),
            "res_model": self._name,
            "view_mode": "form",
            "views": [(view_id, "form")],
            "view_id": view_id,
            "res_id": wizard.id,
            "target": "main",
            "context": {"clear_breadcrumbs": True},
        }

    @api.model
    def action_open_internal_use(self):
        wizard = self.create({})
        return self._avea_form_action(wizard)

    def _avea_lines_to_use(self):
        self.ensure_one()
        lines = self.line_ids.filtered(
            lambda line: line.product_id and line.quantity > 0
        )
        if not lines:
            raise ValidationError(_("Add at least one product with a quantity to use."))
        for line in lines:
            rounding = line.product_id.uom_id.rounding
            if float_is_zero(line.quantity, precision_rounding=rounding):
                continue
            if line.product_id.tracking != "none" and not line.lot_id:
                raise ValidationError(
                    _(
                        "Choose a lot or serial number for %(product)s.",
                        product=line.product_id.display_name,
                    )
                )
            available = line.qty_available
            if float_compare(line.quantity, available, precision_rounding=rounding) > 0:
                raise ValidationError(
                    _(
                        "Only %(available)s of %(product)s is available at %(location)s.",
                        available=available,
                        product=line.product_id.display_name,
                        location=self.location_id.display_name,
                    )
                )
        return lines

    def _avea_create_scrap(self, line):
        self.ensure_one()
        Scrap = self.env["stock.scrap"].sudo().with_company(self.company_id)
        origin = AVEA_INTERNAL_USE_ORIGIN
        if self.notes:
            origin = f"{origin}: {self.notes}"
        scrap_vals = {
            "company_id": self.company_id.id,
            "product_id": line.product_id.id,
            "scrap_qty": line.quantity,
            "location_id": self.location_id.id,
            "origin": origin,
            "scrap_reason_tag_ids": [Command.set(self.reason_tag_ids.ids)],
        }
        if line.lot_id:
            scrap_vals["lot_id"] = line.lot_id.id
        scrap = Scrap.create(scrap_vals)
        if not scrap.check_available_qty():
            raise ValidationError(
                _(
                    "Not enough %(product)s on hand to use %(qty)s.",
                    product=line.product_id.display_name,
                    qty=line.quantity,
                )
            )
        scrap.do_scrap()
        return scrap

    def _avea_create_history(self, lines, scrap_records):
        self.ensure_one()
        return self.env["avea.stock.internal_use.history"].sudo().create(
            {
                "name": self.env["ir.sequence"].next_by_code("avea.stock.internal_use")
                or _("New"),
                "company_id": self.company_id.id,
                "user_id": self.env.user.id,
                "location_id": self.location_id.id,
                "use_date": self.use_date,
                "notes": self.notes,
                "reason_tag_ids": [Command.set(self.reason_tag_ids.ids)],
                "scrap_ids": [Command.set(scrap_records.ids)],
                "line_ids": [
                    Command.create(
                        {
                            "product_id": line.product_id.id,
                            "quantity": line.quantity,
                            "lot_id": line.lot_id.id if line.lot_id else False,
                            "scrap_id": scrap.id,
                        }
                    )
                    for line, scrap in zip(lines, scrap_records, strict=True)
                ],
            }
        )

    def action_use_stock(self):
        self.ensure_one()
        lines = self._avea_lines_to_use()
        scrap_records = self.env["stock.scrap"]
        for line in lines:
            scrap_records |= self._avea_create_scrap(line)
        history = self._avea_create_history(lines, scrap_records)
        product_count = len(lines)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Stock used"),
                "message": _(
                    "%(count)s product line(s) removed from stock (%(ref)s).",
                    count=product_count,
                    ref=history.name,
                ),
                "type": "success",
                "next": self.action_open_internal_use(),
            },
        }


class AveaStockInternalUseHistoryLine(models.Model):
    _name = "avea.stock.internal_use.history.line"
    _description = "Use Stock History Line"
    _order = "id"

    history_id = fields.Many2one(
        "avea.stock.internal_use.history",
        string="Use Stock",
        required=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one("product.product", string="Product", required=True)
    quantity = fields.Float(string="Quantity used", digits="Product Unit", required=True)
    lot_id = fields.Many2one("stock.lot", string="Lot / serial", ondelete="set null")
    scrap_id = fields.Many2one("stock.scrap", string="Scrap record", ondelete="set null")


class AveaStockInternalUseHistory(models.Model):
    _name = "avea.stock.internal_use.history"
    _description = "Use Stock History"
    _inherit = ["avea.stock.mixin"]
    _order = "use_date desc, id desc"

    name = fields.Char(string="Reference", required=True, readonly=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Recorded by",
        required=True,
        default=lambda self: self.env.user,
    )
    location_id = fields.Many2one(
        "stock.location",
        string="From location",
        required=True,
        ondelete="restrict",
    )
    use_date = fields.Date(string="Date", required=True)
    notes = fields.Char(string="Notes")
    reason_tag_ids = fields.Many2many("stock.scrap.reason.tag", string="Reason")
    scrap_ids = fields.Many2many("stock.scrap", string="Odoo scrap records", readonly=True)
    line_ids = fields.One2many(
        "avea.stock.internal_use.history.line",
        "history_id",
        string="Products",
    )
    product_count = fields.Integer(compute="_compute_totals")
    quantity_total = fields.Float(
        string="Total quantity",
        digits="Product Unit",
        compute="_compute_totals",
    )
    summary = fields.Char(compute="_compute_summary")

    @api.depends("line_ids.product_id", "line_ids.quantity")
    def _compute_totals(self):
        for history in self:
            lines = history.line_ids
            history.product_count = len(lines)
            history.quantity_total = sum(lines.mapped("quantity"))

    @api.depends("name", "product_count", "quantity_total")
    def _compute_summary(self):
        for history in self:
            history.summary = _(
                "%(ref)s — %(count)s product(s), %(qty)s units",
                ref=history.name,
                count=history.product_count,
                qty=history.quantity_total,
            )

    def action_open_history(self):
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "avea_till.action_avea_stock_internal_use_history"
        )
        action["target"] = "main"
        action["context"] = dict(self.env.context, clear_breadcrumbs=True)
        return action

    def action_back_to_internal_use_history(self):
        return self.action_open_history()

    def action_open_scrap_records(self):
        self.ensure_one()
        if not self.scrap_ids:
            return False
        action = self.env["ir.actions.act_window"]._for_xml_id("stock.action_stock_scrap")
        action["domain"] = [("id", "in", self.scrap_ids.ids)]
        action["views"] = [
            (view_id, view_type)
            for view_id, view_type in action.get("views", [])
            if view_type == "list"
        ] or action.get("views")
        return action
