# -*- coding: utf-8 -*-
from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError, ValidationError
from .stock_mixin import AVEA_STOCK_TAKE_ORIGIN


class AveaStockTake(models.Model):
    _name = "avea.stock.take"
    _description = "Avea Stock Take"
    _inherit = ["avea.stock.mixin"]
    _order = "id desc"

    name = fields.Char(string="Reference", required=True, copy=False, default=lambda self: _("New Stock Take"))
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("counting", "Counting"),
            ("review", "Ready for Review"),
            ("applied", "Applied"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        copy=False,
    )
    scope_mode = fields.Selection(
        selection=[
            ("everything", "Everything"),
            ("partial", "Choose What to Count"),
        ],
        string="Scope",
        default="everything",
        required=True,
    )
    counting_mode = fields.Selection(
        selection=[
            ("review", "Review Before Updating"),
            ("immediate", "Count & Update As You Go"),
        ],
        string="Counting Mode",
        default="review",
        required=True,
    )
    filter_product_name = fields.Char(string="Product Name")
    filter_sku = fields.Char(string="SKU / Reference")
    filter_barcode = fields.Char(string="Barcode")
    filter_category_id = fields.Many2one("product.category", string="Category")
    filter_supplier_id = fields.Many2one(
        "res.partner",
        string="Supplier",
        domain="[('supplier_rank', '>', 0)]",
    )
    filter_stock_status = fields.Selection(
        selection=[
            ("all", "All"),
            ("in_stock", "In Stock"),
            ("low_stock", "Low Stock"),
            ("out_of_stock", "Out of Stock"),
        ],
        string="Stock Status",
        default="all",
    )
    manual_product_ids = fields.Many2many(
        "product.product",
        "avea_stock_take_manual_product_rel",
        "stock_take_id",
        "product_id",
        string="Selected Products",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    location_id = fields.Many2one(
        "stock.location",
        string="Stock Location",
        required=True,
        domain="[('usage', '=', 'internal')]",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Responsible",
        required=True,
        default=lambda self: self.env.user,
    )
    line_ids = fields.One2many(
        "avea.stock.take.line",
        "stock_take_id",
        string="Lines",
    )
    line_count = fields.Integer(compute="_compute_stats", string="Products to Count")
    counted_count = fields.Integer(compute="_compute_stats", string="Counted")
    applied_count = fields.Integer(compute="_compute_stats", string="Updated")
    remaining_count = fields.Integer(compute="_compute_stats", string="Remaining")
    difference_count = fields.Integer(compute="_compute_stats", string="With Differences")
    unchanged_count = fields.Integer(compute="_compute_stats", string="No Difference")
    total_variance = fields.Float(compute="_compute_stats", digits="Product Unit")
    applied_at = fields.Datetime(copy=False)
    applied_by = fields.Many2one("res.users", copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New Stock Take")) == _("New Stock Take"):
                vals["name"] = self.env["ir.sequence"].next_by_code("avea.stock.take") or _("New Stock Take")
            if not vals.get("location_id"):
                vals["location_id"] = self._avea_default_stock_location(
                    self.env["res.company"].browse(vals.get("company_id")) if vals.get("company_id") else self.env.company
                ).id
        return super().create(vals_list)

    @api.depends(
        "line_ids",
        "line_ids.is_counted",
        "line_ids.is_applied",
        "line_ids.difference_qty",
    )
    def _compute_stats(self):
        for stock_take in self:
            lines = stock_take.line_ids
            stock_take.line_count = len(lines)
            counted = lines.filtered("is_counted")
            stock_take.counted_count = len(counted)
            stock_take.applied_count = len(lines.filtered("is_applied"))
            stock_take.remaining_count = stock_take.line_count - stock_take.counted_count
            differences = counted.filtered(lambda line: not line.product_uom_id.is_zero(line.difference_qty))
            stock_take.difference_count = len(differences)
            stock_take.unchanged_count = len(counted) - stock_take.difference_count
            stock_take.total_variance = sum(counted.mapped("difference_qty"))

    @api.model
    def _avea_base_product_domain(self, company=None):
        company = company or self.env.company
        return [
            ("sale_ok", "=", True),
            ("active", "=", True),
            ("is_storable", "=", True),
            ("company_id", "in", [False, company.id]),
        ]

    def _avea_partial_filter_domain(self):
        self.ensure_one()
        domain = list(self._avea_base_product_domain(self.company_id))
        name = (self.filter_product_name or "").strip()
        sku = (self.filter_sku or "").strip()
        barcode = (self.filter_barcode or "").strip()
        if name:
            domain.append(("name", "ilike", name))
        if sku:
            domain.append(("default_code", "ilike", sku))
        if barcode:
            domain.append(("barcode", "ilike", barcode))
        if self.filter_category_id:
            domain.append(("categ_id", "child_of", self.filter_category_id.id))
        if self.filter_supplier_id:
            domain.append(
                ("product_tmpl_id.avea_supplier_id", "=", self.filter_supplier_id.id)
            )
        if self.filter_stock_status and self.filter_stock_status != "all":
            ProductTemplate = self.env["product.template"]
            status_domain = ProductTemplate._search_avea_stock_status("=", self.filter_stock_status)
            domain.extend(status_domain)
        return domain

    def _avea_filter_domain(self):
        self.ensure_one()
        if self.scope_mode == "everything":
            return list(self._avea_base_product_domain(self.company_id))
        if self.manual_product_ids:
            domain = list(self._avea_base_product_domain(self.company_id))
            domain.append(("id", "in", self.manual_product_ids.ids))
            return domain
        return self._avea_partial_filter_domain()

    def _avea_products_for_scope(self):
        self.ensure_one()
        Product = self.env["product.product"]
        return Product.search(self._avea_filter_domain(), order="name, id")

    @api.model
    def preview_product_count(self, values):
        stock_take = self.new(values)
        stock_take.company_id = values.get("company_id") or self.env.company.id
        if stock_take.scope_mode == "everything":
            Product = self.env["product.product"]
            return {
                "count": Product.search_count(
                    stock_take._avea_base_product_domain(stock_take.company_id)
                )
            }
        if stock_take.manual_product_ids:
            return {"count": len(stock_take.manual_product_ids)}
        Product = self.env["product.product"]
        return {"count": Product.search_count(stock_take._avea_partial_filter_domain())}

    @api.model
    def search_products_for_selection(self, values, limit=500):
        stock_take = self.new(values)
        stock_take.company_id = values.get("company_id") or self.env.company.id
        if stock_take.scope_mode != "partial":
            return {"products": [], "count": 0, "truncated": False}
        Product = self.env["product.product"]
        domain = stock_take._avea_partial_filter_domain()
        total = Product.search_count(domain)
        limit = max(1, min(int(limit or 500), 1000))
        products = Product.search(domain, order="name, id", limit=limit)
        location = stock_take.location_id or self._avea_default_stock_location(
            stock_take.company_id
        )
        rows = []
        for product in products:
            rows.append(
                {
                    "id": product.id,
                    "name": product.display_name,
                    "default_code": product.default_code or "",
                    "barcode": product.barcode or "",
                    "category_name": product.categ_id.display_name if product.categ_id else "",
                    "supplier_name": product.avea_supplier_id.display_name
                    if product.avea_supplier_id
                    else "",
                    "qty_available": product.with_context(location=location.id).qty_available,
                }
            )
        return {"products": rows, "count": total, "truncated": total > limit}

    def _avea_populate_lines(self):
        self.ensure_one()
        products = self._avea_products_for_scope()
        if not products:
            raise UserError(_("No products match this stock take scope."))
        commands = [Command.clear()]
        for sequence, product in enumerate(products, start=1):
            expected = product.with_context(location=self.location_id.id).qty_available
            commands.append(
                Command.create(
                    {
                        "sequence": sequence * 10,
                        "product_id": product.id,
                        "expected_qty": expected,
                    }
                )
            )
        self.line_ids = commands

    def _avea_partial_has_filters(self):
        self.ensure_one()
        return bool(
            (self.filter_product_name or "").strip()
            or (self.filter_sku or "").strip()
            or (self.filter_barcode or "").strip()
            or self.filter_category_id
            or self.filter_supplier_id
            or (self.filter_stock_status and self.filter_stock_status != "all")
        )

    def action_start_counting(self):
        self.ensure_one()
        if self.state not in ("draft", "counting"):
            raise UserError(_("This stock take can no longer be started."))
        if self.scope_mode == "partial" and not self.manual_product_ids:
            raise UserError(
                _("Select at least one product for a partial stock take.")
            )
        if not self.line_ids:
            self._avea_populate_lines()
        self.state = "counting"
        return self._avea_workspace_payload()

    def action_record_count(self, line_id, counted_qty):
        self.ensure_one()
        if self.state != "counting":
            raise UserError(_("This stock take is not in counting mode."))
        line = self.line_ids.browse(line_id)
        if not line or line.stock_take_id != self:
            raise UserError(_("That product is not part of this stock take."))
        line._avea_set_counted_qty(counted_qty)
        if self.counting_mode == "review":
            return self._avea_workspace_payload()
        return self.action_confirm_line(line_id)

    def action_confirm_line(self, line_id):
        self.ensure_one()
        if self.state != "counting":
            raise UserError(_("This stock take is not in counting mode."))
        if self.counting_mode != "immediate":
            raise UserError(_("Individual updates are only available in Count & Update mode."))
        line = self.line_ids.browse(line_id)
        if not line or line.stock_take_id != self:
            raise UserError(_("That product is not part of this stock take."))
        if not line.is_counted:
            raise UserError(_("Enter a counted quantity before confirming."))
        if line.is_applied:
            raise UserError(_("This product has already been updated."))
        line._avea_apply_count()
        if self.remaining_count == 0:
            self._avea_finalize_applied()
        return self._avea_workspace_payload()

    def action_prepare_review(self):
        self.ensure_one()
        if self.state != "counting":
            raise UserError(_("Only an active stock take can be reviewed."))
        if self.counting_mode != "review":
            raise UserError(_("Review is only used in Review Before Updating mode."))
        uncounted = self.line_ids.filtered(lambda line: not line.is_counted)
        if uncounted:
            raise UserError(
                _("%s product(s) still need to be counted before review.", len(uncounted))
            )
        for line in self.line_ids:
            line.expected_qty = line.product_id.with_context(
                location=self.location_id.id
            ).qty_available
        self.state = "review"
        return self._avea_workspace_payload()

    def action_apply_stock_take(self):
        self.ensure_one()
        if self.state != "review":
            raise UserError(_("This stock take is not ready to apply."))
        if self.counting_mode != "review":
            raise UserError(_("Bulk apply is only used in Review Before Updating mode."))
        uncounted = self.line_ids.filtered(lambda line: not line.is_counted)
        if uncounted:
            raise UserError(
                _("%s product(s) still need to be counted before applying.", len(uncounted))
            )
        for line in self.line_ids:
            if not line.is_applied:
                line._avea_apply_count()
        self._avea_finalize_applied()
        return self._avea_workspace_payload()

    def action_reopen_counting(self):
        self.ensure_one()
        if self.state != "review":
            raise UserError(_("Only a stock take awaiting review can return to counting."))
        self.state = "counting"
        return self._avea_workspace_payload()

    def action_cancel_stock_take(self):
        self.ensure_one()
        if self.state == "applied":
            raise UserError(_("An applied stock take cannot be cancelled."))
        self.state = "cancelled"
        return self._avea_open_client_action(new=True)

    def _avea_finalize_applied(self):
        self.ensure_one()
        self.write(
            {
                "state": "applied",
                "applied_at": fields.Datetime.now(),
                "applied_by": self.env.user.id,
            }
        )

    def _avea_line_payload(self, line):
        return {
            "id": line.id,
            "product_id": line.product_id.id,
            "product_name": line.product_name,
            "default_code": line.default_code or "",
            "barcode": line.barcode or "",
            "is_counted": line.is_counted,
            "is_applied": line.is_applied,
            "counted_qty": line.counted_qty,
            "expected_qty": line.expected_qty if self.state in ("review", "applied") or line.is_applied else None,
            "difference_qty": line.difference_qty if self.state in ("review", "applied") or line.is_applied else None,
            "show_expected": self.state in ("review", "applied") or (self.counting_mode == "immediate" and line.is_applied),
        }

    def _avea_workspace_payload(self):
        self.ensure_one()
        lines = self.line_ids.sorted(lambda line: (not line.is_counted, line.sequence, line.id))
        return {
            "stock_take_id": self.id,
            "name": self.name,
            "state": self.state,
            "scope_mode": self.scope_mode,
            "counting_mode": self.counting_mode,
            "line_count": self.line_count,
            "counted_count": self.counted_count,
            "applied_count": self.applied_count,
            "remaining_count": self.remaining_count,
            "difference_count": self.difference_count,
            "unchanged_count": self.unchanged_count,
            "total_variance": self.total_variance,
            "filter_product_name": self.filter_product_name or "",
            "filter_sku": self.filter_sku or "",
            "filter_barcode": self.filter_barcode or "",
            "filter_category_id": self.filter_category_id.id,
            "filter_category_name": self.filter_category_id.display_name if self.filter_category_id else "",
            "filter_supplier_id": self.filter_supplier_id.id,
            "filter_supplier_name": self.filter_supplier_id.display_name if self.filter_supplier_id else "",
            "filter_stock_status": self.filter_stock_status,
            "manual_product_ids": self.manual_product_ids.ids,
            "lines": [self._avea_line_payload(line) for line in lines],
            "scope_label": self._avea_scope_label(),
        }

    def _avea_scope_label(self):
        self.ensure_one()
        if self.scope_mode == "everything":
            return _("Everything")
        parts = []
        if self.filter_category_id:
            parts.append(self.filter_category_id.display_name)
        if self.filter_supplier_id:
            parts.append(self.filter_supplier_id.display_name)
        if self.filter_product_name:
            parts.append(self.filter_product_name)
        if self.manual_product_ids and not parts:
            return _("%s selected products", len(self.manual_product_ids))
        return ", ".join(parts) if parts else _("Selected filters")

    def get_workspace_state(self):
        self.ensure_one()
        return self._avea_workspace_payload()

    @api.model
    def get_filter_options(self):
        suppliers = self.env["res.partner"].search_read(
            [("supplier_rank", ">", 0)],
            ["id", "display_name"],
            order="name",
            limit=500,
        )
        categories = self.env["product.category"].search_read(
            [],
            ["id", "display_name"],
            order="name",
            limit=500,
        )
        return {
            "suppliers": suppliers,
            "categories": categories,
            "stock_statuses": [
                {"value": "all", "label": _("All")},
                {"value": "in_stock", "label": _("In Stock")},
                {"value": "low_stock", "label": _("Low Stock")},
                {"value": "out_of_stock", "label": _("Out of Stock")},
            ],
        }

    @api.model
    def create_stock_take(self, values):
        stock_take = self.create(values)
        return stock_take._avea_workspace_payload()

    def _avea_open_client_action(self, new=False):
        return {
            "type": "ir.actions.client",
            "tag": "avea_stock_take",
            "name": _("Stock Take"),
            "params": {
                "stock_take_id": False if new else self.id,
            },
            "target": "current",
        }

    @api.model
    def action_open_stock_take(self):
        existing = self.search(
            [
                ("user_id", "=", self.env.uid),
                ("state", "in", ["draft", "counting", "review"]),
            ],
            order="write_date desc, id desc",
            limit=1,
        )
        if existing:
            return existing._avea_open_client_action()
        return self._avea_open_client_action(new=True)


class AveaStockTakeLine(models.Model):
    _name = "avea.stock.take.line"
    _description = "Avea Stock Take Line"
    _order = "sequence, id"

    stock_take_id = fields.Many2one(
        "avea.stock.take",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        ondelete="restrict",
    )
    product_name = fields.Char(related="product_id.display_name", string="Product")
    default_code = fields.Char(related="product_id.default_code", string="SKU")
    barcode = fields.Char(related="product_id.barcode", string="Barcode")
    product_uom_id = fields.Many2one(related="product_id.uom_id")
    company_id = fields.Many2one(related="stock_take_id.company_id", store=True)
    location_id = fields.Many2one(related="stock_take_id.location_id", store=True)
    expected_qty = fields.Float(string="Expected", digits="Product Unit")
    counted_qty = fields.Float(string="Counted", digits="Product Unit")
    difference_qty = fields.Float(
        string="Difference",
        compute="_compute_difference_qty",
        digits="Product Unit",
        store=True,
    )
    is_counted = fields.Boolean(string="Counted", default=False)
    is_applied = fields.Boolean(string="Applied", default=False, copy=False)
    applied_at = fields.Datetime(copy=False)
    applied_by = fields.Many2one("res.users", copy=False)
    system_qty_at_apply = fields.Float(
        string="System Qty at Apply",
        digits="Product Unit",
        copy=False,
    )
    stock_quant_id = fields.Many2one("stock.quant", copy=False)

    _sql_constraints = [
        (
            "avea_stock_take_line_product_unique",
            "unique(stock_take_id, product_id)",
            "Each product can only appear once in a stock take.",
        ),
    ]

    @api.depends("expected_qty", "counted_qty", "is_counted")
    def _compute_difference_qty(self):
        for line in self:
            if line.is_counted:
                line.difference_qty = (line.counted_qty or 0.0) - (line.expected_qty or 0.0)
            else:
                line.difference_qty = 0.0

    def _avea_set_counted_qty(self, counted_qty):
        self.ensure_one()
        qty = float(counted_qty or 0.0)
        if qty < 0:
            raise ValidationError(_("Counted quantity cannot be negative."))
        self.write(
            {
                "counted_qty": qty,
                "is_counted": True,
            }
        )

    def _avea_apply_count(self):
        self.ensure_one()
        stock_take = self.stock_take_id
        if stock_take.state == "applied":
            raise UserError(_("This stock take has already been applied."))
        if not self.is_counted:
            raise UserError(_("This product has not been counted yet."))
        if self.is_applied:
            return
        product = self.product_id
        if not product.active or not product.is_storable:
            raise UserError(
                _("%s is no longer available to count.", product.display_name)
            )
        location = stock_take.location_id
        current_qty = product.with_context(location=location.id).qty_available
        quant = stock_take._avea_apply_inventory_count(
            product,
            location,
            self.counted_qty,
            origin=stock_take.name,
        )
        self.write(
            {
                "is_applied": True,
                "applied_at": fields.Datetime.now(),
                "applied_by": self.env.user.id,
                "system_qty_at_apply": current_qty,
                "stock_quant_id": quant.id,
                "expected_qty": current_qty,
                "difference_qty": self.counted_qty - current_qty,
            }
        )
