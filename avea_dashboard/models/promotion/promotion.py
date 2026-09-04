from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError


class AveaPromotion(models.Model):
    _name = "avea.promotion"
    _description = "Avea Promotion"
    _order = "date_from desc, name, id desc"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    description = fields.Text(string="Description")
    date_from = fields.Date(string="From")
    date_to = fields.Date(string="To")
    open_ended = fields.Boolean(
        string="Open ended",
        default=False,
        help="No end date — the promotion stays active until you turn it off.",
    )
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        required=True,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        depends=["company_id"],
    )

    product_scope = fields.Selection(
        [
            ("all", "All products"),
            ("category", "Category"),
            ("products", "Specific products"),
        ],
        string="Products",
        required=True,
        default="all",
    )
    product_category_id = fields.Many2one("product.category", string="Category")
    product_ids = fields.Many2many("product.product", string="Products")

    deal_type = fields.Selection(
        [
            ("percent_off", "% off"),
            ("fixed_amount", "Fixed amount off"),
            ("buy_x_get_y", "Buy X Get Y"),
            ("spend_x_save", "Spend X Save"),
            ("combo_price", "Combo Price"),
            ("extra_loyalty_points", "Extra Loyalty Points"),
        ],
        string="Deal",
        required=True,
        default="percent_off",
    )
    discount_percent = fields.Float(string="Discount %")
    discount_amount = fields.Monetary(string="Amount off", currency_field="currency_id")
    spend_minimum = fields.Monetary(string="Spend at least", currency_field="currency_id")
    buy_quantity = fields.Float(string="Buy quantity", default=2)
    get_quantity = fields.Float(string="Free quantity", default=1)
    get_product_id = fields.Many2one(
        "product.product",
        string="Free product",
        help="Leave empty to give the same product for free.",
    )
    combo_line_ids = fields.One2many(
        "avea.promotion.combo.line",
        "promotion_id",
        string="Combo products",
        copy=True,
    )
    combo_price = fields.Monetary(
        string="Combo price",
        currency_field="currency_id",
        help="Fixed price for one complete set of the combo products.",
    )
    loyalty_points = fields.Float(
        string="Points",
        help="How many extra loyalty points customers earn.",
    )
    loyalty_points_mode = fields.Selection(
        [
            ("money", "Per currency spent"),
            ("order", "Per order"),
            ("unit", "Per product"),
        ],
        string="Points mode",
        default="money",
    )
    promo_code = fields.Char(
        string="Promo code",
        help="Optional. Cashiers enter this code at the till if set.",
    )
    pos_config_ids = fields.Many2many(
        "pos.config",
        string="Point of Sale",
        help="Leave empty to apply on all tills.",
    )

    program_id = fields.Many2one("loyalty.program", readonly=True, copy=False)
    deal_summary = fields.Char(compute="_compute_summary_panel")
    summary_name = fields.Char(related="name", readonly=True)
    summary_status = fields.Char(compute="_compute_summary_panel")
    summary_date_range = fields.Char(compute="_compute_summary_panel")
    summary_products = fields.Char(compute="_compute_summary_panel")
    summary_promo_code = fields.Char(related="promo_code", readonly=True)
    summary_blurb = fields.Text(compute="_compute_summary_panel")
    pos_order_count = fields.Integer(related="program_id.pos_order_count", string="POS orders")

    @api.depends(
        "name",
        "active",
        "description",
        "date_from",
        "date_to",
        "open_ended",
        "deal_type",
        "discount_percent",
        "discount_amount",
        "spend_minimum",
        "buy_quantity",
        "get_quantity",
        "get_product_id",
        "combo_line_ids",
        "combo_line_ids.product_id",
        "combo_line_ids.quantity",
        "combo_price",
        "loyalty_points",
        "loyalty_points_mode",
        "promo_code",
        "product_scope",
        "product_category_id",
        "product_ids",
        "currency_id",
    )
    def _compute_summary_panel(self):
        for promotion in self:
            promotion.deal_summary = promotion._format_deal_line()
            promotion.summary_status = _("Active") if promotion.active else _("Inactive")
            promotion.summary_date_range = promotion._format_date_range()
            promotion.summary_products = promotion._format_products_label()
            promotion.summary_blurb = promotion._format_summary_blurb()

    def _format_combo_parts(self):
        self.ensure_one()
        parts = []
        for line in self.combo_line_ids:
            qty = line.quantity
            qty_display = int(qty) if float(qty) == int(float(qty)) else qty
            name = line.product_id.display_name or _("Product")
            parts.append(f"{qty_display} × {name}")
        return parts

    def _format_deal_line(self):
        self.ensure_one()
        symbol = self.currency_id.symbol or ""
        if self.deal_type == "percent_off":
            return _("%(percent)s%% off", percent=self.discount_percent or 0)
        if self.deal_type == "fixed_amount":
            return _("%(amount)s off", amount=f"{symbol} {self.discount_amount:.2f}")
        if self.deal_type == "buy_x_get_y":
            return _(
                "Buy %(buy)s get %(free)s free",
                buy=int(self.buy_quantity or 0),
                free=int(self.get_quantity or 0),
            )
        if self.deal_type == "spend_x_save":
            return _(
                "Spend %(spend)s save %(save)s",
                spend=f"{symbol} {self.spend_minimum:.2f}",
                save=f"{symbol} {self.discount_amount:.2f}",
            )
        if self.deal_type == "combo_price":
            parts = self._format_combo_parts()
            price = f"{symbol} {self.combo_price:.2f}"
            if parts:
                return _("Combo %(parts)s for %(price)s", parts=" + ".join(parts), price=price)
            return _("Combo for %(price)s", price=price)
        mode_labels = dict(self._fields["loyalty_points_mode"].selection)
        return _(
            "%(points)s pts (%(mode)s)",
            points=self.loyalty_points or 0,
            mode=mode_labels.get(self.loyalty_points_mode, ""),
        )

    def _format_date_range(self):
        self.ensure_one()
        if self.open_ended:
            if self.date_from:
                return _("From %(date)s · Open ended", date=self.date_from)
            return _("Open ended")
        if self.date_from and self.date_to:
            return f"{self.date_from} – {self.date_to}"
        if self.date_from:
            return _("From %(date)s", date=self.date_from)
        if self.date_to:
            return _("Until %(date)s", date=self.date_to)
        return _("No date limit")

    @api.onchange("open_ended")
    def _onchange_open_ended(self):
        if self.open_ended:
            self.date_to = False

    @api.onchange("date_to")
    def _onchange_date_to(self):
        if self.date_to:
            self.open_ended = False

    def _format_products_label(self):
        self.ensure_one()
        if self.deal_type == "combo_price":
            parts = self._format_combo_parts()
            return " + ".join(parts) if parts else _("Combo products")
        if self.product_scope == "all":
            return _("All products")
        if self.product_scope == "category":
            return self.product_category_id.display_name or _("Category")
        if not self.product_ids:
            return _("Specific products")
        if len(self.product_ids) == 1:
            return self.product_ids.display_name
        return _("%(count)s products", count=len(self.product_ids))

    def _format_summary_blurb(self):
        self.ensure_one()
        if self.deal_type == "combo_price":
            parts = self._format_combo_parts()
            symbol = self.currency_id.symbol or ""
            price = f"{symbol} {self.combo_price:.2f}"
            if parts:
                blurb = _("Buy %(parts)s for %(price)s.", parts=" + ".join(parts), price=price)
            else:
                blurb = _("Buy the combo products for %(price)s.", price=price)
        elif self.deal_type == "extra_loyalty_points":
            deal = self._format_deal_line()
            products = self._format_products_label()
            blurb = _("Customers earn %(deal)s on %(products)s.", deal=deal, products=products)
        elif self.deal_type == "buy_x_get_y":
            products = self._format_products_label()
            free = self.get_product_id.display_name if self.get_product_id else _("the same product")
            blurb = _(
                "Buy %(buy)s of %(products)s and get %(free_qty)s × %(free)s free.",
                buy=int(self.buy_quantity or 0),
                products=products,
                free_qty=int(self.get_quantity or 0),
                free=free,
            )
        else:
            deal = self._format_deal_line()
            products = self._format_products_label()
            blurb = _("%(deal)s on %(products)s.", deal=deal, products=products)
        if self.promo_code:
            blurb = _("%(blurb)s Cashiers enter code %(code)s at the till.", blurb=blurb, code=self.promo_code)
        else:
            blurb = _("%(blurb)s Applies automatically at the till.", blurb=blurb)
        if self.description:
            blurb = f"{blurb}\n{self.description}"
        return blurb

    @api.onchange("deal_type")
    def _onchange_deal_type(self):
        if self.deal_type == "combo_price":
            self.product_scope = "products"
            self.product_category_id = False
            if not self.combo_line_ids:
                self.combo_line_ids = [Command.create({"quantity": 1.0})]

    @api.constrains(
        "deal_type",
        "discount_percent",
        "discount_amount",
        "spend_minimum",
        "buy_quantity",
        "get_quantity",
        "loyalty_points",
        "product_scope",
        "product_category_id",
        "product_ids",
        "combo_line_ids",
        "combo_price",
        "promo_code",
    )
    def _check_promotion_values(self):
        for promotion in self:
            promotion._validate_promotion_values()

    def _validate_promotion_values(self):
        self.ensure_one()
        if self.deal_type == "combo_price":
            if not self.combo_line_ids:
                raise ValidationError(_("Add at least one product to the combo."))
            if any(not line.product_id for line in self.combo_line_ids):
                raise ValidationError(_("Choose a product for every combo line."))
            if self.currency_id.compare_amounts(self.combo_price, 0) <= 0:
                raise ValidationError(_("Enter a combo price greater than zero."))
        elif self.product_scope == "category" and not self.product_category_id:
            raise ValidationError(_("Choose a product category."))
        elif self.product_scope == "products" and not self.product_ids:
            raise ValidationError(_("Choose at least one product."))
        if self.deal_type == "percent_off":
            if self.discount_percent <= 0 or self.discount_percent > 100:
                raise ValidationError(_("Enter a discount between 0 and 100%."))
        elif self.deal_type == "fixed_amount":
            if self.currency_id.compare_amounts(self.discount_amount, 0) <= 0:
                raise ValidationError(_("Enter an amount off greater than zero."))
        elif self.deal_type == "spend_x_save":
            if self.currency_id.compare_amounts(self.spend_minimum, 0) <= 0:
                raise ValidationError(_("Enter a minimum spend greater than zero."))
            if self.currency_id.compare_amounts(self.discount_amount, 0) <= 0:
                raise ValidationError(_("Enter a saving amount greater than zero."))
        elif self.deal_type == "buy_x_get_y":
            if self.buy_quantity < 1:
                raise ValidationError(_("Buy quantity must be at least 1."))
            if self.get_quantity < 1:
                raise ValidationError(_("Free quantity must be at least 1."))
            if self.product_scope == "all":
                raise ValidationError(_("Choose specific products or a category for Buy X Get Y."))
        elif self.deal_type == "extra_loyalty_points":
            if self.loyalty_points <= 0:
                raise ValidationError(_("Enter a points amount greater than zero."))
        if self.promo_code and " " in self.promo_code.strip():
            raise ValidationError(_("Promo codes cannot contain spaces."))

    def _rule_scope_vals(self):
        self.ensure_one()
        vals = {"minimum_qty": 0}
        if self.product_scope == "category":
            vals["product_category_id"] = self.product_category_id.id
        elif self.product_scope == "products":
            vals["product_ids"] = [Command.set(self.product_ids.ids)]
        return vals

    def _reward_scope_vals(self):
        self.ensure_one()
        vals = {}
        if self.product_scope == "all":
            vals["discount_applicability"] = "order"
        elif self.product_scope == "category":
            vals.update(
                {
                    "discount_applicability": "specific",
                    "discount_product_category_id": self.product_category_id.id,
                }
            )
        else:
            vals.update(
                {
                    "discount_applicability": "specific",
                    "discount_product_ids": [Command.set(self.product_ids.ids)],
                }
            )
        return vals

    def _prepare_loyalty_program_vals(self):
        self.ensure_one()
        self._validate_promotion_values()
        rule_vals = self._rule_scope_vals()
        reward_vals = {}
        program_type = "promotion"
        trigger = "with_code" if self.promo_code else "auto"
        applies_on = "current"

        if self.promo_code:
            program_type = "promo_code"
            rule_vals.update({"code": self.promo_code.strip(), "mode": "with_code"})
        else:
            rule_vals["mode"] = "auto"

        if self.deal_type == "percent_off":
            rule_vals.update({"reward_point_amount": 1, "reward_point_mode": "order"})
            reward_vals = {
                "required_points": 1,
                "discount": self.discount_percent,
                "discount_mode": "percent",
                **self._reward_scope_vals(),
            }
        elif self.deal_type == "fixed_amount":
            rule_vals.update({"reward_point_amount": 1, "reward_point_mode": "order"})
            reward_vals = {
                "required_points": 1,
                "discount": self.discount_amount,
                "discount_mode": "per_order",
                **self._reward_scope_vals(),
            }
        elif self.deal_type == "spend_x_save":
            rule_vals.update(
                {
                    "reward_point_amount": 1,
                    "reward_point_mode": "order",
                    "minimum_amount": self.spend_minimum,
                }
            )
            reward_vals = {
                "required_points": 1,
                "discount": self.discount_amount,
                "discount_mode": "per_order",
                "discount_applicability": "order",
            }
        elif self.deal_type == "buy_x_get_y":
            program_type = "buy_x_get_y"
            trigger = "auto"
            buy_qty = int(self.buy_quantity)
            product = self.product_ids[:1] or self.env["product.product"].search(
                [
                    ("sale_ok", "=", True),
                    ("categ_id", "child_of", self.product_category_id.id),
                ],
                limit=1,
            )
            if not product:
                raise ValidationError(_("No saleable product found for this promotion."))
            free_product = self.get_product_id or product
            rule_vals.update(
                {
                    "minimum_qty": buy_qty,
                    "reward_point_mode": "unit",
                    "reward_point_amount": 1,
                    "mode": "auto",
                }
            )
            if self.product_scope == "products":
                rule_vals["product_ids"] = [Command.set(self.product_ids.ids)]
            elif self.product_scope == "category":
                rule_vals["product_category_id"] = self.product_category_id.id
            reward_vals = {
                "reward_type": "product",
                "reward_product_id": free_product.id,
                "reward_product_qty": int(self.get_quantity),
                "required_points": buy_qty,
            }
        elif self.deal_type == "combo_price":
            # Native loyalty cannot express multi-product fixed combo pricing with
            # per-line quantities. Publish a POS-visible program shell only; Avea POS
            # applies the real combo discount. Keep the shell unclaimable so Odoo
            # never auto-applies the placeholder 0.01 reward.
            program_type = "promo_code" if self.promo_code else "promotion"
            trigger = "with_code" if self.promo_code else "auto"
            product_ids = self.combo_line_ids.mapped("product_id").ids
            rule_vals.update(
                {
                    "product_ids": [Command.set(product_ids)],
                    # Never award points in practice — Avea applies combo pricing in POS.
                    "minimum_qty": 999999,
                    "minimum_amount": 0,
                    "reward_point_mode": "order",
                    "reward_point_amount": 1,
                    "mode": "with_code" if self.promo_code else "auto",
                }
            )
            if self.promo_code:
                rule_vals["code"] = self.promo_code.strip()
            reward_vals = {
                "required_points": 999999,
                "discount": 0.01,
                "discount_mode": "per_order",
                "discount_applicability": "specific",
                "discount_product_ids": [Command.set(product_ids)],
            }
        else:
            program_type = "loyalty"
            applies_on = "both"
            trigger = "auto"
            rule_vals.update(
                {
                    "reward_point_amount": self.loyalty_points,
                    "reward_point_mode": self.loyalty_points_mode,
                    "mode": "auto",
                }
            )
            reward_vals = {
                "required_points": 1,
                "discount": 1,
                "discount_mode": "per_point",
                "discount_applicability": "order",
            }

        pos_configs = [Command.set(self.pos_config_ids.ids)] if self.pos_config_ids else [Command.clear()]
        combo_components = []
        if self.deal_type == "combo_price":
            combo_components = [
                {
                    "product_id": line.product_id.id,
                    "quantity": line.quantity,
                    "name": line.product_id.display_name,
                }
                for line in self.combo_line_ids
            ]
        return {
            "name": self.name,
            "active": self.active,
            "company_id": self.company_id.id,
            "currency_id": self.currency_id.id,
            "program_type": program_type,
            "trigger": trigger,
            "applies_on": applies_on,
            "date_from": self.date_from,
            "date_to": False if self.open_ended else self.date_to,
            "pos_ok": True,
            "pos_config_ids": pos_configs,
            "portal_visible": program_type == "loyalty",
            "avea_is_combo": self.deal_type == "combo_price",
            "avea_combo_price": self.combo_price if self.deal_type == "combo_price" else 0.0,
            "avea_combo_components": combo_components,
            "avea_promotion_id": self.id,
            "rule_ids": [Command.clear(), Command.create(rule_vals)],
            "reward_ids": [Command.clear(), Command.create(reward_vals)],
        }

    def _sync_loyalty_program(self):
        Program = self.env["loyalty.program"].sudo()
        for promotion in self:
            vals = promotion._prepare_loyalty_program_vals()
            if promotion.program_id:
                promotion.program_id.write(vals)
            else:
                promotion.program_id = Program.create(vals)
            promotion._rename_combo_discount_product()

    def _rename_combo_discount_product(self):
        """Use the promotion name on the loyalty discount product shown in POS."""
        self.ensure_one()
        if self.deal_type != "combo_price" or not self.program_id:
            return
        product = self.program_id.reward_ids.discount_line_product_id[:1]
        if product and product.name != self.name:
            product.sudo().write({"name": self.name})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("open_ended"):
                vals["date_to"] = False
        promotions = super().create(vals_list)
        promotions._sync_loyalty_program()
        return promotions

    def write(self, vals):
        vals = dict(vals)
        if vals.get("open_ended"):
            vals["date_to"] = False
        res = super().write(vals)
        sync_fields = {
            "name",
            "active",
            "description",
            "date_from",
            "date_to",
            "open_ended",
            "company_id",
            "product_scope",
            "product_category_id",
            "product_ids",
            "deal_type",
            "discount_percent",
            "discount_amount",
            "spend_minimum",
            "buy_quantity",
            "get_quantity",
            "get_product_id",
            "combo_line_ids",
            "combo_price",
            "loyalty_points",
            "loyalty_points_mode",
            "promo_code",
            "pos_config_ids",
        }
        if sync_fields.intersection(vals):
            self._sync_loyalty_program()
        return res

    def unlink(self):
        programs = self.program_id
        if programs:
            programs.sudo().write({"active": False})
            programs.sudo().unlink()
        return super().unlink()
