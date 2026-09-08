# -*- coding: utf-8 -*-
from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round

from .stock_mixin import AVEA_PRODUCT_COST_PRECISION, AVEA_SUPPLIER_COST_PRECISION

# When no reorder rule exists, treat stock at or below this qty as Low Stock.
AVEA_DEFAULT_LOW_STOCK_QTY = 5.0


class ProductTemplate(models.Model):
    _inherit = "product.template"

    avea_cost_ex_tax = fields.Float(
        string="Cost EX Tax",
        digits=AVEA_SUPPLIER_COST_PRECISION,
        help=(
            "Avea purchasing cost shown in Stock and Receive Stock. "
            "This is not updated by inventory average costing."
        ),
    )

    # ---- Pricing (Cost EX VAT / Retail INC VAT) ----
    avea_retail_ex_vat = fields.Float(
        string="Retail EX VAT",
        compute="_compute_avea_pricing",
        digits="Product Price",
    )
    avea_markup_percent = fields.Float(
        string="Markup %",
        compute="_compute_avea_pricing",
        inverse="_inverse_avea_markup_percent",
        digits=(16, 2),
    )
    avea_margin_percent = fields.Float(
        string="Margin %",
        compute="_compute_avea_pricing",
        inverse="_inverse_avea_margin_percent",
        digits=(16, 2),
    )

    # ---- Stock status ----
    avea_stock_status = fields.Selection(
        selection=[
            ("in_stock", "In Stock"),
            ("low_stock", "Low Stock"),
            ("out_of_stock", "Out of Stock"),
            ("not_tracked", "Not Tracked"),
        ],
        string="Stock Status",
        compute="_compute_avea_stock_status",
        search="_search_avea_stock_status",
    )
    avea_stock_qty = fields.Float(
        string="Current Stock",
        compute="_compute_avea_stock_qty",
        inverse="_inverse_avea_stock_qty",
        digits="Product Unit",
    )
    avea_low_stock_qty = fields.Float(
        string="Low stock at",
        compute="_compute_avea_low_stock_qty",
        inverse="_inverse_avea_low_stock_qty",
        digits="Product Unit",
        help="Warn when on-hand quantity reaches this level or below.",
    )

    # ---- Supplier (primary vendor) ----
    avea_supplier_id = fields.Many2one(
        "res.partner",
        string="Supplier",
        compute="_compute_avea_supplier",
        inverse="_inverse_avea_supplier_id",
        search="_search_avea_supplier_id",
    )
    avea_supplier_code = fields.Char(
        string="Supplier product reference",
        compute="_compute_avea_supplier",
        inverse="_inverse_avea_supplier_code",
    )
    avea_supplier_price = fields.Float(
        string="Supplier cost EX VAT",
        compute="_compute_avea_supplier",
        inverse="_inverse_avea_supplier_price",
        digits="Product Price",
    )
    avea_supplier_uom_id = fields.Many2one(
        "uom.uom",
        string="Purchase Unit of Measure",
        compute="_compute_avea_supplier",
        inverse="_inverse_avea_supplier_uom_id",
    )

    # ---- Review summary (form right panel) ----
    avea_summary_name = fields.Char(compute="_compute_avea_summary")
    avea_summary_sku = fields.Char(compute="_compute_avea_summary")
    avea_summary_category = fields.Char(compute="_compute_avea_summary")
    avea_summary_cost = fields.Char(compute="_compute_avea_summary")
    avea_summary_retail = fields.Char(compute="_compute_avea_summary")
    avea_summary_markup = fields.Char(compute="_compute_avea_summary")
    avea_summary_margin = fields.Char(compute="_compute_avea_summary")
    avea_summary_track_stock = fields.Char(compute="_compute_avea_summary")
    avea_summary_stock_qty = fields.Char(compute="_compute_avea_summary")
    avea_summary_pos = fields.Char(compute="_compute_avea_summary")
    avea_summary_pos_category = fields.Char(compute="_compute_avea_summary")

    # -------------------------------------------------------------------------
    # Tax / pricing helpers
    # -------------------------------------------------------------------------

    def _avea_sale_taxes(self):
        self.ensure_one()
        return self.taxes_id._filter_taxes_by_company(self.env.company)

    def _avea_get_cost_ex_tax(self):
        self.ensure_one()
        if self.avea_cost_ex_tax:
            return self.avea_cost_ex_tax
        return self.standard_price or 0.0

    def _avea_apply_catalog_cost(self, cost_ex):
        """Set Avea purchasing cost; sync Odoo standard cost only for standard costing."""
        self.ensure_one()
        mixin = self.env["avea.stock.mixin"]
        cost = mixin._avea_round_supplier_cost(cost_ex)
        self.avea_cost_ex_tax = cost
        if self.cost_method == "standard":
            self.standard_price = mixin._avea_round_product_cost(cost)

    def _avea_pricing_from_cost_retail(self, cost, retail_inc):
        self.ensure_one()
        mixin = self.env["avea.stock.mixin"]
        cost = mixin._avea_round_supplier_cost(cost)
        retail_inc = mixin._avea_round_product_cost(retail_inc)
        retail_ex = mixin._avea_round_product_cost(
            self._avea_retail_ex_vat_from_inc(retail_inc)
        )
        currency = self.currency_id or self.env.company.currency_id
        prec = currency.decimal_places
        if float_is_zero(cost, precision_digits=prec):
            markup = 0.0
        else:
            markup = mixin._avea_round_percent((retail_ex - cost) / cost * 100.0)
        if float_is_zero(retail_ex, precision_digits=prec):
            margin = 0.0
        else:
            margin = mixin._avea_round_percent((retail_ex - cost) / retail_ex * 100.0)
        return retail_ex, markup, margin

    def _avea_retail_ex_vat_from_inc(self, retail_inc):
        """Convert Retail INC VAT → EX VAT using the product's sales taxes."""
        self.ensure_one()
        taxes = self._avea_sale_taxes()
        currency = self.currency_id or self.env.company.currency_id
        if not taxes:
            return retail_inc or 0.0
        # price_include taxes treat the given amount as tax-included by default
        return taxes.compute_all(retail_inc or 0.0, currency)["total_excluded"]

    def _avea_retail_inc_vat_from_ex(self, retail_ex):
        """Convert Retail EX VAT → INC VAT using the product's sales taxes."""
        self.ensure_one()
        taxes = self._avea_sale_taxes()
        currency = self.currency_id or self.env.company.currency_id
        if not taxes:
            return retail_ex or 0.0
        return taxes.with_context(force_price_include=False).compute_all(
            retail_ex or 0.0, currency
        )["total_included"]

    def _avea_pricing_tuple(self):
        """Return (cost_ex, retail_inc, retail_ex, markup%, margin%)."""
        self.ensure_one()
        cost = self._avea_get_cost_ex_tax()
        retail_inc = self.list_price or 0.0
        retail_ex, markup, margin = self._avea_pricing_from_cost_retail(cost, retail_inc)
        return cost, retail_inc, retail_ex, markup, margin

    @api.depends(
        "list_price",
        "avea_cost_ex_tax",
        "standard_price",
        "taxes_id",
        "taxes_id.amount",
        "taxes_id.price_include",
    )
    def _compute_avea_pricing(self):
        for product in self:
            _cost, _inc, retail_ex, markup, margin = product._avea_pricing_tuple()
            product.avea_retail_ex_vat = retail_ex
            product.avea_markup_percent = markup
            product.avea_margin_percent = margin

    def _avea_apply_retail_ex(self, retail_ex):
        """Set list_price (INC VAT) from an EX-VAT retail target."""
        mixin = self.env["avea.stock.mixin"]
        for product in self:
            retail_inc = product._avea_retail_inc_vat_from_ex(retail_ex)
            product.list_price = mixin._avea_round_product_cost(retail_inc)

    def _inverse_avea_markup_percent(self):
        for product in self:
            cost = product._avea_get_cost_ex_tax()
            retail_ex = cost * (1.0 + (product.avea_markup_percent or 0.0) / 100.0)
            product._avea_apply_retail_ex(retail_ex)
        self._compute_avea_pricing()

    def _inverse_avea_margin_percent(self):
        for product in self:
            cost = product._avea_get_cost_ex_tax()
            margin = product.avea_margin_percent or 0.0
            if margin >= 100.0:
                raise UserError(_("Margin must be less than 100%."))
            if float_is_zero(100.0 - margin, precision_digits=4):
                raise UserError(_("Margin must be less than 100%."))
            retail_ex = cost / (1.0 - margin / 100.0) if margin < 100.0 else 0.0
            product._avea_apply_retail_ex(retail_ex)
        self._compute_avea_pricing()

    @api.onchange("avea_cost_ex_tax", "standard_price", "list_price", "taxes_id")
    def _onchange_avea_pricing_fields(self):
        # Recompute display fields immediately while editing.
        self._compute_avea_pricing()

    @api.onchange("avea_markup_percent")
    def _onchange_avea_markup_percent(self):
        if self.env.context.get("avea_pricing_guard"):
            return
        self = self.with_context(avea_pricing_guard=True)
        cost = self._avea_get_cost_ex_tax()
        retail_ex = cost * (1.0 + (self.avea_markup_percent or 0.0) / 100.0)
        self.list_price = self._avea_retail_inc_vat_from_ex(retail_ex)
        self._compute_avea_pricing()

    @api.onchange("avea_margin_percent")
    def _onchange_avea_margin_percent(self):
        if self.env.context.get("avea_pricing_guard"):
            return
        margin = self.avea_margin_percent or 0.0
        if margin >= 100.0:
            return {
                "warning": {
                    "title": _("Invalid margin"),
                    "message": _("Margin must be less than 100%."),
                }
            }
        self = self.with_context(avea_pricing_guard=True)
        cost = self._avea_get_cost_ex_tax()
        retail_ex = cost / (1.0 - margin / 100.0)
        self.list_price = self._avea_retail_inc_vat_from_ex(retail_ex)
        self._compute_avea_pricing()

    # -------------------------------------------------------------------------
    # Stock
    # -------------------------------------------------------------------------

    def _avea_low_stock_threshold(self):
        self.ensure_one()
        if self.nbr_reordering_rules and self.reordering_min_qty > 0:
            return self.reordering_min_qty
        return AVEA_DEFAULT_LOW_STOCK_QTY

    @api.depends(
        "is_storable",
        "qty_available",
        "reordering_min_qty",
        "nbr_reordering_rules",
    )
    def _compute_avea_stock_status(self):
        for product in self:
            if not product.is_storable:
                product.avea_stock_status = "not_tracked"
                continue
            qty = product.qty_available
            if float_compare(qty, 0.0, precision_digits=2) <= 0:
                product.avea_stock_status = "out_of_stock"
            elif float_compare(qty, product._avea_low_stock_threshold(), precision_digits=2) <= 0:
                product.avea_stock_status = "low_stock"
            else:
                product.avea_stock_status = "in_stock"

    def _search_avea_stock_status(self, operator, value):
        if operator not in ("=", "!="):
            raise UserError(_("Unsupported stock status search."))
        statuses = value if isinstance(value, (list, tuple)) else [value]

        def domain_for(status):
            if status == "not_tracked":
                return [("is_storable", "=", False)]
            if status == "out_of_stock":
                return [("is_storable", "=", True), ("qty_available", "<=", 0)]
            if status == "in_stock":
                # Approximate: tracked with qty above default threshold.
                # Exact rule-based low stock is refined client-side via compute.
                return [
                    ("is_storable", "=", True),
                    ("qty_available", ">", AVEA_DEFAULT_LOW_STOCK_QTY),
                ]
            if status == "low_stock":
                return [
                    ("is_storable", "=", True),
                    ("qty_available", ">", 0),
                    ("qty_available", "<=", AVEA_DEFAULT_LOW_STOCK_QTY),
                ]
            return [("id", "=", False)]

        domains = [domain_for(status) for status in statuses]
        if not domains:
            return [("id", "=", False)]
        if len(domains) == 1:
            domain = domains[0]
        else:
            domain = ["|"] * (len(domains) - 1)
            for part in domains:
                domain.extend(part)
        if operator == "!=":
            return ["!"] + domain
        return domain

    @api.depends("qty_available", "is_storable")
    def _compute_avea_stock_qty(self):
        for product in self:
            product.avea_stock_qty = product.qty_available if product.is_storable else 0.0

    def _inverse_avea_stock_qty(self):
        for product in self:
            if not product.is_storable:
                continue
            variant = product.product_variant_id
            if not variant:
                continue
            variant.qty_available = product.avea_stock_qty

    @api.depends("reordering_min_qty", "nbr_reordering_rules")
    def _compute_avea_low_stock_qty(self):
        for product in self:
            if product.nbr_reordering_rules and product.reordering_min_qty > 0:
                product.avea_low_stock_qty = product.reordering_min_qty
            else:
                product.avea_low_stock_qty = AVEA_DEFAULT_LOW_STOCK_QTY

    def _inverse_avea_low_stock_qty(self):
        Orderpoint = self.env["stock.warehouse.orderpoint"]
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        for product in self:
            if not product.is_storable or not product.product_variant_id:
                continue
            min_qty = max(product.avea_low_stock_qty or 0.0, 0.0)
            orderpoint = Orderpoint.search(
                [
                    ("product_id", "=", product.product_variant_id.id),
                    ("company_id", "=", self.env.company.id),
                ],
                limit=1,
            )
            if orderpoint:
                orderpoint.product_min_qty = min_qty
                if orderpoint.product_max_qty < min_qty:
                    orderpoint.product_max_qty = min_qty
            elif warehouse:
                Orderpoint.create(
                    {
                        "product_id": product.product_variant_id.id,
                        "warehouse_id": warehouse.id,
                        "location_id": warehouse.lot_stock_id.id,
                        "product_min_qty": min_qty,
                        "product_max_qty": min_qty,
                        "company_id": self.env.company.id,
                    }
                )

    @api.onchange("is_storable")
    def _onchange_avea_is_storable(self):
        if self.is_storable and self.type != "consu":
            self.type = "consu"
        if not self.is_storable:
            self.avea_stock_qty = 0.0

    # -------------------------------------------------------------------------
    # Supplier
    # -------------------------------------------------------------------------

    def _avea_primary_seller(self):
        self.ensure_one()
        sellers = self.seller_ids.filtered(
            lambda s: not s.company_id or s.company_id == self.env.company
        )
        return sellers[:1]

    @api.depends(
        "seller_ids",
        "seller_ids.partner_id",
        "seller_ids.product_code",
        "seller_ids.price",
        "seller_ids.product_uom_id",
    )
    def _compute_avea_supplier(self):
        for product in self:
            seller = product._avea_primary_seller()
            product.avea_supplier_id = seller.partner_id
            product.avea_supplier_code = seller.product_code
            product.avea_supplier_price = seller.price
            product.avea_supplier_uom_id = seller.product_uom_id or product.uom_id

    def _avea_ensure_primary_seller(self):
        self.ensure_one()
        seller = self._avea_primary_seller()
        if seller:
            return seller
        if not self.avea_supplier_id or not self.id:
            return self.env["product.supplierinfo"]
        return self.env["product.supplierinfo"].create(
            {
                "product_tmpl_id": self.id,
                "partner_id": self.avea_supplier_id.id,
                "price": self.avea_supplier_price or self._avea_get_cost_ex_tax() or 0.0,
                "product_uom_id": (self.avea_supplier_uom_id or self.uom_id).id,
                "product_code": self.avea_supplier_code or False,
            }
        )

    def _inverse_avea_supplier_id(self):
        for product in self:
            if not product.id:
                continue
            seller = product._avea_primary_seller()
            if not product.avea_supplier_id:
                if seller:
                    seller.unlink()
                continue
            if seller:
                seller.partner_id = product.avea_supplier_id
            else:
                product._avea_ensure_primary_seller()

    def _inverse_avea_supplier_code(self):
        for product in self:
            if not product.avea_supplier_id:
                continue
            seller = product._avea_ensure_primary_seller()
            if seller:
                seller.product_code = product.avea_supplier_code

    def _inverse_avea_supplier_price(self):
        for product in self:
            if not product.avea_supplier_id:
                continue
            seller = product._avea_ensure_primary_seller()
            if seller:
                seller.price = product.avea_supplier_price

    def _inverse_avea_supplier_uom_id(self):
        for product in self:
            if not product.avea_supplier_id:
                continue
            seller = product._avea_ensure_primary_seller()
            if seller and product.avea_supplier_uom_id:
                seller.product_uom_id = product.avea_supplier_uom_id

    def _search_avea_supplier_id(self, operator, value):
        return [("seller_ids.partner_id", operator, value)]

    # -------------------------------------------------------------------------
    # Summary panel
    # -------------------------------------------------------------------------

    @api.depends(
        "name",
        "default_code",
        "categ_id",
        "avea_cost_ex_tax",
        "standard_price",
        "list_price",
        "avea_markup_percent",
        "avea_margin_percent",
        "is_storable",
        "avea_stock_qty",
        "available_in_pos",
        "pos_categ_ids",
        "currency_id",
    )
    def _compute_avea_summary(self):
        for product in self:
            currency = product.currency_id or product.env.company.currency_id
            product.avea_summary_name = product.name or _("New stock item")
            product.avea_summary_sku = product.default_code or _("Not set")
            product.avea_summary_category = product.categ_id.display_name or _("Not set")
            product.avea_summary_cost = currency.format(product._avea_get_cost_ex_tax())
            product.avea_summary_retail = currency.format(product.list_price or 0.0)
            product.avea_summary_markup = _("%.1f%%") % (product.avea_markup_percent or 0.0)
            product.avea_summary_margin = _("%.1f%%") % (product.avea_margin_percent or 0.0)
            product.avea_summary_track_stock = _("Yes") if product.is_storable else _("No")
            if product.is_storable:
                qty = float_round(product.avea_stock_qty or 0.0, precision_digits=2)
                product.avea_summary_stock_qty = ("%s" % qty).rstrip("0").rstrip(".")
            else:
                product.avea_summary_stock_qty = _("Not tracked")
            product.avea_summary_pos = _("Yes") if product.available_in_pos else _("No")
            product.avea_summary_pos_category = (
                ", ".join(product.pos_categ_ids.mapped("name")) or _("Not set")
            )

    @api.model_create_multi
    def create(self, vals_list):
        mixin = self.env["avea.stock.mixin"]
        for vals in vals_list:
            if vals.get("avea_cost_ex_tax") is None and vals.get("standard_price") is not None:
                vals["avea_cost_ex_tax"] = mixin._avea_round_supplier_cost(
                    vals["standard_price"]
                )
            elif vals.get("standard_price") is None and vals.get("avea_cost_ex_tax") is not None:
                vals["standard_price"] = mixin._avea_round_product_cost(
                    vals["avea_cost_ex_tax"]
                )
        return super().create(vals_list)

    def write(self, vals):
        mixin = self.env["avea.stock.mixin"]
        if (
            "avea_cost_ex_tax" in vals
            and "standard_price" not in vals
            and len(self) == 1
            and self.cost_method == "standard"
        ):
            vals = dict(vals)
            vals["standard_price"] = mixin._avea_round_product_cost(vals["avea_cost_ex_tax"])
        res = super().write(vals)
        return res

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get("avea_stock_workspace"):
            if "available_in_pos" in fields_list or not fields_list:
                res.setdefault("available_in_pos", True)
            if "sale_ok" in fields_list or not fields_list:
                res.setdefault("sale_ok", True)
            if "purchase_ok" in fields_list or not fields_list:
                res.setdefault("purchase_ok", True)
            if "is_storable" in fields_list or not fields_list:
                res.setdefault("is_storable", True)
            if "type" in fields_list or not fields_list:
                res.setdefault("type", "consu")
        return res

    def _avea_pos_category_for_product_category(self, categ):
        """Match or create a POS category with the same name as the product category."""
        if not categ:
            return self.env["pos.category"]
        PosCategory = self.env["pos.category"]
        pos_categ = PosCategory.search([("name", "=", categ.name)], limit=1)
        if not pos_categ:
            pos_categ = PosCategory.create({"name": categ.name})
        return pos_categ

    @api.onchange("categ_id")
    def _onchange_avea_categ_carry_to_pos(self):
        if not self.categ_id:
            return
        pos_categ = self._avea_pos_category_for_product_category(self.categ_id)
        if pos_categ:
            self.pos_categ_ids = [(6, 0, pos_categ.ids)]
            if not self.available_in_pos and self.env.context.get("avea_stock_workspace"):
                self.available_in_pos = True

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def action_avea_open_stock_item(self):
        self.ensure_one()
        view = self.env.ref("avea_till.view_avea_stock_product_form")
        context = dict(self.env.context, avea_stock_workspace=True)
        return {
            "type": "ir.actions.act_window",
            "name": _("Stock Item"),
            "res_model": "product.template",
            "res_id": self.id,
            "view_mode": "form",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "current",
            "context": context,
        }

    @api.model
    def action_avea_open_receive_stock(self):
        return self.env["avea.stock.receive"].action_open_receive()

    @api.model
    def action_avea_open_stock_count(self):
        view = self.env.ref("avea_till.view_avea_stock_count_placeholder_form")
        return {
            "type": "ir.actions.act_window",
            "name": _("Stock Count"),
            "res_model": "avea.stock.count.placeholder",
            "view_mode": "form",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "current",
        }

    @api.model
    def action_avea_new_stock_item(self):
        quick = bool(
            self.env.context.get("avea_quick_product_add")
            or self.env.context.get("avea_return_receive_id")
        )
        view = self.env.ref(
            "avea_till.view_avea_stock_product_quick_form"
            if quick
            else "avea_till.view_avea_stock_product_form"
        )
        context = {
            "avea_stock_workspace": True,
            "default_sale_ok": True,
            "default_purchase_ok": True,
            "default_available_in_pos": True,
            "default_type": "consu",
            "default_is_storable": True,
            "default_taxes_id": [(6, 0, self.env.company.account_sale_tax_id.ids)]
            if self.env.company.account_sale_tax_id
            else [],
        }
        if quick:
            context["avea_quick_product_add"] = True
        # Preserve return-to-receive (or other) context from the caller.
        for key in (
            "avea_return_receive_id",
            "avea_quick_product_add",
            "default_name",
            "default_categ_id",
        ):
            if self.env.context.get(key):
                context[key] = self.env.context[key]
        return {
            "type": "ir.actions.act_window",
            "name": _("New Stock Item"),
            "res_model": "product.template",
            "view_mode": "form",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "new" if quick else "current",
            "context": context,
        }

    def action_avea_save_stock_item(self):
        """Save and stay on the stock item (standard workspace save)."""
        self.ensure_one()
        return self.action_avea_open_stock_item()

    def action_avea_save_and_return_receive(self):
        """Save the product, add it to the Receive Stock draft, and go back."""
        self.ensure_one()
        receive_id = self.env.context.get("avea_return_receive_id")
        if not receive_id:
            return self.action_avea_open_stock_item()
        receive = self.env["avea.stock.receive"].browse(receive_id).exists()
        if not receive or receive.state != "draft":
            raise UserError(_("The Receive Stock draft is no longer available."))
        variant = self.product_variant_id
        if not variant:
            raise UserError(_("This product could not be added to Receive Stock yet."))
        existing = receive.line_ids.filtered(lambda line: line.product_id == variant)[:1]
        if existing:
            # Keep the line; refresh cost from the product if empty.
            if not existing.price_unit:
                existing.price_unit = self._avea_get_cost_ex_tax() or 0.0
        else:
            receive.write(
                {
                    "line_ids": [
                        Command.create(
                            {
                                "product_id": variant.id,
                                "quantity": 1.0,
                                "price_unit": self._avea_get_cost_ex_tax() or 0.0,
                            }
                        )
                    ]
                }
            )
        return receive._avea_receive_action(receive)

    def action_avea_back_to_receive(self):
        """Leave the product form and return to the Receive Stock draft."""
        receive_id = self.env.context.get("avea_return_receive_id")
        if not receive_id:
            return {"type": "ir.actions.act_window_close"}
        receive = self.env["avea.stock.receive"].browse(receive_id).exists()
        if not receive:
            return self.env["avea.stock.receive"].action_open_receive()
        return receive._avea_receive_action(receive)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if self.env.context.get("avea_stock_workspace"):
                vals.setdefault("sale_ok", True)
                vals.setdefault("purchase_ok", True)
                vals.setdefault("available_in_pos", True)
                if vals.get("available_in_pos") and not vals.get("sale_ok", True):
                    vals["sale_ok"] = True
                if vals.get("is_storable"):
                    vals["type"] = "consu"
                # Carry product category onto POS category when POS cats were not set.
                if vals.get("categ_id") and not vals.get("pos_categ_ids"):
                    categ = self.env["product.category"].browse(vals["categ_id"])
                    pos_categ = self._avea_pos_category_for_product_category(categ)
                    if pos_categ:
                        vals["pos_categ_ids"] = [(6, 0, pos_categ.ids)]
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get("avea_stock_workspace") and vals.get("is_storable"):
            vals = dict(vals, type="consu")
        if (
            self.env.context.get("avea_stock_workspace")
            and vals.get("categ_id")
            and "pos_categ_ids" not in vals
        ):
            categ = self.env["product.category"].browse(vals["categ_id"])
            pos_categ = self._avea_pos_category_for_product_category(categ)
            if pos_categ:
                vals = dict(vals, pos_categ_ids=[(6, 0, pos_categ.ids)])
        return super().write(vals)
