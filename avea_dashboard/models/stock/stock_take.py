# -*- coding: utf-8 -*-
from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero, float_round
from odoo.tools.misc import formatLang, format_datetime
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
    increase_count = fields.Integer(compute="_compute_stats", string="Increases")
    decrease_count = fields.Integer(compute="_compute_stats", string="Decreases")
    total_increase_qty = fields.Float(
        compute="_compute_stats",
        string="Total Increase (units)",
        digits="Product Unit",
    )
    total_decrease_qty = fields.Float(
        compute="_compute_stats",
        string="Total Decrease (units)",
        digits="Product Unit",
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        depends=["company_id"],
    )
    total_gain_value = fields.Monetary(
        compute="_compute_stats",
        string="Stock Gain (value)",
        currency_field="currency_id",
    )
    total_loss_value = fields.Monetary(
        compute="_compute_stats",
        string="Stock Loss (value)",
        currency_field="currency_id",
    )
    net_stock_value_impact = fields.Monetary(
        compute="_compute_stats",
        string="Net Stock Value Impact",
        currency_field="currency_id",
    )
    accounting_impact_total = fields.Monetary(
        compute="_compute_stats",
        string="Accounting Impact",
        currency_field="currency_id",
    )
    has_accounting_impact = fields.Boolean(compute="_compute_stats")
    applied_at = fields.Datetime(copy=False)
    applied_by = fields.Many2one("res.users", copy=False)
    history_date = fields.Datetime(
        string="Completed",
        compute="_compute_history_date",
        store=True,
    )
    scope_label = fields.Char(
        string="Scope",
        compute="_compute_scope_label",
    )

    @api.depends("state", "applied_at", "write_date")
    def _compute_history_date(self):
        for stock_take in self:
            if stock_take.state == "applied":
                stock_take.history_date = stock_take.applied_at
            elif stock_take.state == "cancelled":
                stock_take.history_date = stock_take.write_date
            else:
                stock_take.history_date = False

    @api.depends(
        "scope_mode",
        "filter_category_id",
        "filter_supplier_id",
        "filter_product_name",
        "manual_product_ids",
    )
    def _compute_scope_label(self):
        for stock_take in self:
            stock_take.scope_label = stock_take._avea_scope_label()

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
        "line_ids.variance_value",
        "line_ids.variance_direction",
        "line_ids.accounting_value",
    )
    def _compute_stats(self):
        for stock_take in self:
            lines = stock_take.line_ids
            stock_take.line_count = len(lines)
            counted = lines.filtered("is_counted")
            stock_take.counted_count = len(counted)
            stock_take.applied_count = len(lines.filtered("is_applied"))
            stock_take.remaining_count = stock_take.line_count - stock_take.counted_count
            differences = counted.filtered(
                lambda line: line.variance_direction and line.variance_direction != "match"
            )
            stock_take.difference_count = len(differences)
            stock_take.unchanged_count = len(counted) - stock_take.difference_count
            stock_take.total_variance = sum(counted.mapped("difference_qty"))
            increases = differences.filtered(lambda line: line.variance_direction == "increase")
            decreases = differences.filtered(lambda line: line.variance_direction == "decrease")
            stock_take.increase_count = len(increases)
            stock_take.decrease_count = len(decreases)
            stock_take.total_increase_qty = sum(increases.mapped("difference_qty"))
            stock_take.total_decrease_qty = sum(abs(qty) for qty in decreases.mapped("difference_qty"))
            stock_take.total_gain_value = sum(increases.mapped("variance_value"))
            stock_take.total_loss_value = sum(abs(val) for val in decreases.mapped("variance_value"))
            stock_take.net_stock_value_impact = sum(counted.mapped("variance_value"))
            accounting_total = sum(counted.mapped("accounting_value"))
            stock_take.accounting_impact_total = accounting_total
            stock_take.has_accounting_impact = any(
                not float_is_zero(val, precision_rounding=stock_take.currency_id.rounding or 0.01)
                for val in counted.mapped("accounting_value")
            )

    @api.model
    def _avea_values_from_client(self, values):
        """Normalize OWL/RPC payloads before ``new()`` (Many2one ids must be ints)."""
        vals = dict(values or {})
        for field_name in ("filter_category_id", "filter_supplier_id"):
            raw = vals.get(field_name)
            if raw in (False, None, "", 0):
                vals[field_name] = False
            else:
                vals[field_name] = int(raw)
        if vals.get("company_id"):
            vals["company_id"] = int(vals["company_id"])
        return vals

    @api.model
    def _avea_base_product_domain(self, company=None):
        company = company or self.env.company
        return [
            ("sale_ok", "=", True),
            ("active", "=", True),
            ("is_storable", "=", True),
            ("company_id", "in", [False, company.id]),
        ]

    @api.model
    def _avea_partial_filter_domain_from_values(self, values):
        """Build the partial-count product domain from RPC / form values."""
        vals = self._avea_values_from_client(values)
        company = self.env.company
        if vals.get("company_id"):
            company = self.env["res.company"].browse(vals["company_id"])
        domain = list(self._avea_base_product_domain(company))
        name = (vals.get("filter_product_name") or "").strip()
        sku = (vals.get("filter_sku") or "").strip()
        barcode = (vals.get("filter_barcode") or "").strip()
        if name:
            domain.append(("name", "ilike", name))
        if sku:
            domain.append(("default_code", "ilike", sku))
        if barcode:
            domain.append(("barcode", "ilike", barcode))
        category_id = vals.get("filter_category_id")
        if category_id:
            domain.append(("categ_id", "child_of", category_id))
        supplier_id = vals.get("filter_supplier_id")
        if supplier_id:
            domain.append(("product_tmpl_id.avea_supplier_id", "=", supplier_id))
        stock_status = vals.get("filter_stock_status") or "all"
        if stock_status != "all":
            ProductTemplate = self.env["product.template"]
            status_domain = ProductTemplate._search_avea_stock_status("=", stock_status)
            domain.extend(status_domain)
        return domain

    def _avea_partial_filter_domain(self):
        self.ensure_one()
        return self._avea_partial_filter_domain_from_values(
            {
                "filter_product_name": self.filter_product_name,
                "filter_sku": self.filter_sku,
                "filter_barcode": self.filter_barcode,
                "filter_category_id": self.filter_category_id.id,
                "filter_supplier_id": self.filter_supplier_id.id,
                "filter_stock_status": self.filter_stock_status,
                "company_id": self.company_id.id,
            }
        )

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
        values = self._avea_values_from_client(values)
        scope_mode = values.get("scope_mode") or "everything"
        company = self.env.company
        if values.get("company_id"):
            company = self.env["res.company"].browse(values["company_id"])
        if scope_mode == "everything":
            Product = self.env["product.product"]
            return {"count": Product.search_count(self._avea_base_product_domain(company))}
        manual_ids = values.get("manual_product_ids")
        if manual_ids and manual_ids[0][0] == 6:
            return {"count": len(manual_ids[0][2])}
        Product = self.env["product.product"]
        return {
            "count": Product.search_count(self._avea_partial_filter_domain_from_values(values))
        }

    @api.model
    def product_ids_matching_partial_filters(self, values):
        """Product IDs for the current partial-count filters (bulk selection)."""
        values = self._avea_values_from_client(values)
        if values.get("scope_mode") != "partial":
            return {"product_ids": [], "count": 0}
        Product = self.env["product.product"]
        domain = self._avea_partial_filter_domain_from_values(values)
        products = Product.search(domain, order="name, id")
        return {"product_ids": products.ids, "count": len(products)}

    @api.model
    def search_products_for_selection(self, values, offset=0, limit=100):
        values = self._avea_values_from_client(values)
        if values.get("selection_offset") is not None:
            offset = values["selection_offset"]
        if values.get("selection_limit") is not None:
            limit = values["selection_limit"]
        if values.get("scope_mode") != "partial":
            return {
                "products": [],
                "count": 0,
                "offset": 0,
                "limit": 0,
                "has_more": False,
            }
        Product = self.env["product.product"]
        domain = self._avea_partial_filter_domain_from_values(values)
        total = Product.search_count(domain)
        offset = max(0, int(offset or 0))
        limit = max(1, min(int(limit or 100), 200))
        products = Product.search(domain, order="name, id", offset=offset, limit=limit)
        company = self.env.company
        if values.get("company_id"):
            company = self.env["res.company"].browse(values["company_id"])
        location_id = values.get("location_id")
        location = (
            self.env["stock.location"].browse(int(location_id))
            if location_id
            else self._avea_default_stock_location(company)
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
        return {
            "products": rows,
            "count": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(products) < total,
        }

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

    def _avea_archive_product(self, product):
        product.ensure_one()
        product.product_tmpl_id.write({"active": False})

    @api.model
    def action_zero_and_archive_product(self, product_id):
        """Zero on-hand stock at the default location and archive (partial count helper)."""
        product = self.env["product.product"].browse(product_id).exists()
        if not product:
            raise UserError(_("Product not found."))
        if not product.is_storable:
            raise UserError(_("%s is not a stock product.", product.display_name))
        location = self._avea_default_stock_location(self.env.company)
        current_qty = product.with_context(location=location.id).qty_available
        if not float_is_zero(current_qty, precision_rounding=product.uom_id.rounding):
            self._avea_apply_inventory_count(
                product,
                location,
                0.0,
                origin=AVEA_STOCK_TAKE_ORIGIN,
            )
        self._avea_archive_product(product)
        return {"product_id": product.id, "archived": True}

    def action_zero_and_archive_line(self, line_id):
        """Count zero, apply inventory, and archive during a partial stock take."""
        self.ensure_one()
        if self.scope_mode != "partial":
            raise UserError(_("Zero & Archive is only available on partial stock takes."))
        if self.state not in ("counting", "review"):
            raise UserError(_("This stock take is not active."))
        line = self.line_ids.browse(line_id)
        if not line or line.stock_take_id != self:
            raise UserError(_("That product is not part of this stock take."))
        if line.is_applied:
            raise UserError(_("This product has already been updated."))
        line._avea_set_counted_qty(0.0)
        line._avea_apply_count()
        self._avea_archive_product(line.product_id)
        if self.state == "review" and self.remaining_count == 0:
            pass
        return self._avea_workspace_payload()

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

    @api.model
    def action_open_stock_take_history(self):
        view_id = self.env.ref("avea_till.view_avea_stock_take_history_list").id
        form_id = self.env.ref("avea_till.view_avea_stock_take_history_form").id
        return {
            "type": "ir.actions.act_window",
            "name": _("Stock take history"),
            "res_model": self._name,
            "view_mode": "list,form",
            "views": [(view_id, "list"), (form_id, "form")],
            "domain": [("state", "in", ("applied", "cancelled"))],
            "search_view_id": self.env.ref(
                "avea_till.view_avea_stock_take_history_search"
            ).id,
            "target": "main",
            "context": {
                "clear_breadcrumbs": True,
                "create": False,
                "avea_stock_history_readonly": True,
            },
        }

    def action_back_to_stock_take_history(self):
        return self.action_open_stock_take_history()

    def action_print_stock_take_report(self):
        self.ensure_one()
        report = self.env.ref("avea_till.action_report_avea_stock_take")
        return report.report_action(self)

    def _avea_backfill_line_report_data(self):
        for stock_take in self:
            for line in stock_take.line_ids.filtered("is_applied"):
                vals = {}
                if not line.unit_cost:
                    vals["unit_cost"] = (
                        line.product_id.product_tmpl_id._avea_get_cost_ex_tax() or 0.0
                    )
                move = line.stock_move_id or line._avea_find_inventory_move(stock_take)
                if move and not line.stock_move_id:
                    vals["stock_move_id"] = move.id
                if move:
                    vals.setdefault(
                        "accounting_value", line._avea_accounting_value_from_move(move)
                    )
                if vals:
                    line.write(vals)

    def _avea_format_qty(self, qty, uom=None):
        rounding = (uom or self.env["uom.uom"]).rounding if uom else 0.01
        return float_round(qty or 0.0, precision_rounding=rounding)

    def _avea_report_line_rows(self, lines):
        currency = self.company_id.currency_id
        rows = []
        for line in lines.sorted(lambda item: (item.sequence, item.id)):
            rows.append(
                {
                    "product": line.product_id.display_name,
                    "sku": line.default_code or "",
                    "barcode": line.barcode or "",
                    "category": line.categ_id.display_name if line.categ_id else "",
                    "supplier": line.supplier_id.display_name if line.supplier_id else "",
                    "uom": line.product_uom_id.name,
                    "expected_qty": line.expected_qty,
                    "counted_qty": line.counted_qty,
                    "difference_qty": line.difference_qty,
                    "unit_cost": line.unit_cost,
                    "variance_value": line.variance_value,
                    "accounting_value": line.accounting_value,
                    "variance_direction": line.variance_direction,
                    "variance_label": dict(line._fields["variance_direction"].selection).get(
                        line.variance_direction, ""
                    ),
                    "variance_value_display": formatLang(
                        self.env,
                        line.variance_value,
                        currency_obj=currency,
                    ),
                    "unit_cost_display": formatLang(
                        self.env,
                        line.unit_cost,
                        currency_obj=currency,
                    ),
                }
            )
        return rows

    def get_stock_take_report_payload(self):
        """Structured data for the stock take PDF/HTML report."""
        self.ensure_one()
        currency = self.company_id.currency_id
        lines = self.line_ids.filtered("is_counted")
        variances = lines.filtered(
            lambda line: line.variance_direction and line.variance_direction != "match"
        )
        increases = variances.filtered(lambda line: line.variance_direction == "increase")
        decreases = variances.filtered(lambda line: line.variance_direction == "decrease")
        matches = lines.filtered(lambda line: line.variance_direction == "match")
        valuation_note = _(
            "Stock value impact uses each product's Avea unit cost (ex tax) at the time of apply. "
            "Accounting entries appear only when inventory valuation posts automatically "
            "(real-time valuation). Periodic valuation may not post journal entries on count."
        )
        return {
            "reference": self.name,
            "state_label": dict(self._fields["state"].selection).get(self.state, self.state),
            "completed": format_datetime(self.env, self.history_date) if self.history_date else "",
            "applied_at": format_datetime(self.env, self.applied_at) if self.applied_at else "",
            "scope": self.scope_label,
            "counting_mode": dict(self._fields["counting_mode"].selection).get(
                self.counting_mode, self.counting_mode
            ),
            "location": self.location_id.display_name,
            "responsible": self.user_id.display_name,
            "applied_by": self.applied_by.display_name if self.applied_by else "",
            "line_count": self.line_count,
            "difference_count": self.difference_count,
            "unchanged_count": self.unchanged_count,
            "increase_count": self.increase_count,
            "decrease_count": self.decrease_count,
            "total_variance": self.total_variance,
            "total_increase_qty": self.total_increase_qty,
            "total_decrease_qty": self.total_decrease_qty,
            "total_gain_value": self.total_gain_value,
            "total_loss_value": self.total_loss_value,
            "net_stock_value_impact": self.net_stock_value_impact,
            "accounting_impact_total": self.accounting_impact_total,
            "has_accounting_impact": self.has_accounting_impact,
            "valuation_note": valuation_note,
            "currency": currency,
            "variance_lines": self._avea_report_line_rows(variances),
            "increase_lines": self._avea_report_line_rows(increases),
            "decrease_lines": self._avea_report_line_rows(decreases),
            "match_lines": self._avea_report_line_rows(matches),
            "all_lines": self._avea_report_line_rows(lines),
            "money": lambda amount: formatLang(self.env, amount, currency_obj=currency),
        }


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
    stock_move_id = fields.Many2one("stock.move", string="Inventory Move", copy=False)
    categ_id = fields.Many2one(related="product_id.categ_id", string="Category", store=True)
    supplier_id = fields.Many2one(
        related="product_id.product_tmpl_id.avea_supplier_id",
        string="Supplier",
        store=True,
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    unit_cost = fields.Float(
        string="Unit Cost (ex tax)",
        digits="Product Price",
        copy=False,
        help="Avea unit cost captured when the count was applied.",
    )
    variance_value = fields.Monetary(
        string="Stock Value Impact",
        compute="_compute_variance_value",
        store=True,
        currency_field="currency_id",
    )
    accounting_value = fields.Monetary(
        string="Accounting Impact",
        currency_field="currency_id",
        copy=False,
        help="Journal impact when Odoo posts inventory valuation for this adjustment.",
    )
    variance_direction = fields.Selection(
        selection=[
            ("match", "Correct"),
            ("increase", "Increase"),
            ("decrease", "Decrease"),
        ],
        string="Result",
        compute="_compute_variance_direction",
        store=True,
    )

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

    @api.depends("difference_qty", "unit_cost", "is_counted", "product_id")
    def _compute_variance_value(self):
        for line in self:
            if not line.is_counted:
                line.variance_value = 0.0
                continue
            cost = line.unit_cost or line.product_id.product_tmpl_id._avea_get_cost_ex_tax()
            line.variance_value = (line.difference_qty or 0.0) * (cost or 0.0)

    @api.depends("difference_qty", "is_counted", "product_uom_id")
    def _compute_variance_direction(self):
        for line in self:
            if not line.is_counted:
                line.variance_direction = False
                continue
            rounding = line.product_uom_id.rounding or 0.01
            if float_is_zero(line.difference_qty, precision_rounding=rounding):
                line.variance_direction = "match"
            elif line.difference_qty > 0:
                line.variance_direction = "increase"
            else:
                line.variance_direction = "decrease"

    def _avea_find_inventory_move(self, stock_take):
        self.ensure_one()
        return self.env["stock.move"].search(
            [
                ("product_id", "=", self.product_id.id),
                ("reference", "=", stock_take.name),
                ("state", "=", "done"),
            ],
            order="id desc",
            limit=1,
        )

    def _avea_accounting_value_from_move(self, move):
        if not move or not move.account_move_id:
            return 0.0
        move = move.sudo()
        company = move.company_id
        stock_accounts = set()
        for field_name in ("account_stock_valuation_id", "account_stock_expense_id"):
            account = getattr(company, field_name, False)
            if account:
                stock_accounts.add(account.id)
        if not stock_accounts:
            return 0.0
        impact = 0.0
        for aml in move.account_move_id.line_ids:
            if aml.account_id.id not in stock_accounts:
                continue
            impact += aml.debit - aml.credit
        return impact

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
        unit_cost = product.product_tmpl_id._avea_get_cost_ex_tax() or 0.0
        move = self._avea_find_inventory_move(stock_take)
        accounting_value = self._avea_accounting_value_from_move(move)
        self.write(
            {
                "is_applied": True,
                "applied_at": fields.Datetime.now(),
                "applied_by": self.env.user.id,
                "system_qty_at_apply": current_qty,
                "stock_quant_id": quant.id,
                "stock_move_id": move.id if move else False,
                "unit_cost": unit_cost,
                "accounting_value": accounting_value,
                "expected_qty": current_qty,
                "difference_qty": self.counted_qty - current_qty,
            }
        )
