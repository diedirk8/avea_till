# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_round


class AveaSalesPlatform(models.Model):
    _name = "avea.sales.platform"
    _description = "Avea Sales Platform"
    _order = "name, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related="company_id.currency_id", depends=["company_id"])
    partner_id = fields.Many2one(
        "res.partner",
        string="Platform customer",
        required=True,
        ondelete="restrict",
        copy=False,
        help="Odoo contact used for this sales platform (commission / settlements).",
    )
    pricelist_id = fields.Many2one(
        "product.pricelist",
        string="Platform pricelist",
        required=True,
        ondelete="restrict",
        copy=False,
    )
    commission_percent = fields.Float(
        string="Commission %",
        required=True,
        default=10.0,
        help="Platform commission as a percentage of the platform selling price.",
    )
    commission_vat = fields.Boolean(
        string="VAT on commission",
        default=True,
        help="When set, VAT on the commission fee is included in the platform price calculation.",
    )
    price_rounding_rule = fields.Selection(
        [
            ("none", "No rounding (2 decimals)"),
            ("nearest_5", "Nearest R5"),
            ("nearest_9", "Nearest R9"),
            ("nearest_10", "Nearest R10"),
            ("nearest_10_then_9", "Nearest R10, then R9 ending"),
        ],
        string="Price rounding",
        required=True,
        default="nearest_9",
    )
    notes = fields.Text(string="Notes")
    settings_json = fields.Json(
        string="Platform settings",
        default=dict,
        help="Reserved for future platform-specific configuration.",
    )
    last_price_update = fields.Datetime(readonly=True)
    pricelist_item_count = fields.Integer(compute="_compute_pricelist_item_count")

    lookup_product_id = fields.Many2one(
        "product.product",
        string="Lookup product",
        domain="[('sale_ok', '=', True), ('active', '=', True)]",
    )
    lookup_retail_price_inc = fields.Monetary(
        string="Retail price (incl. tax)",
        compute="_compute_price_lookup",
        currency_field="currency_id",
    )
    lookup_platform_price_inc = fields.Monetary(
        string="Platform price (incl. tax)",
        compute="_compute_price_lookup",
        currency_field="currency_id",
    )
    lookup_commission_amount_inc = fields.Monetary(
        string="Commission (incl. tax)",
        compute="_compute_price_lookup",
        currency_field="currency_id",
    )

    _sql_constraints = [
        (
            "avea_sales_platform_pricelist_uniq",
            "unique(pricelist_id)",
            "Each platform pricelist can only belong to one sales platform.",
        ),
    ]

    @api.constrains("commission_percent")
    def _check_commission_percent(self):
        for platform in self:
            if platform.commission_percent < 0 or platform.commission_percent >= 100:
                raise ValidationError(_("Commission must be between 0 and 100% (exclusive of 100%)."))

    @api.depends("pricelist_id", "pricelist_id.item_ids")
    def _compute_pricelist_item_count(self):
        for platform in self:
            platform.pricelist_item_count = len(platform.pricelist_id.item_ids) if platform.pricelist_id else 0

    @api.depends(
        "lookup_product_id",
        "commission_percent",
        "commission_vat",
        "price_rounding_rule",
        "pricelist_id",
    )
    def _compute_price_lookup(self):
        for platform in self:
            platform.lookup_retail_price_inc = 0.0
            platform.lookup_platform_price_inc = 0.0
            platform.lookup_commission_amount_inc = 0.0
            product = platform.lookup_product_id
            if not product:
                continue
            retail_inc = product.product_tmpl_id.list_price or 0.0
            platform.lookup_retail_price_inc = retail_inc
            platform.lookup_platform_price_inc = platform._avea_platform_price_from_retail(retail_inc)
            platform.lookup_commission_amount_inc = (
                platform.lookup_platform_price_inc - retail_inc
                if platform.lookup_platform_price_inc
                else 0.0
            )

    @api.model
    def _avea_default_commission_vat_rate(self, company=None):
        company = company or self.env.company
        tax = company.account_sale_tax_id
        if tax:
            return tax.amount / 100.0
        return 0.15

    def _avea_effective_commission_rate(self):
        self.ensure_one()
        rate = (self.commission_percent or 0.0) / 100.0
        if self.commission_vat:
            rate *= 1.0 + self._avea_default_commission_vat_rate(self.company_id)
        return rate

    def _avea_platform_price_from_retail(self, retail_inc):
        """Derive platform list price from Avea shelf retail (list_price, tax included)."""
        self.ensure_one()
        retail_inc = retail_inc or 0.0
        if float_compare(retail_inc, 0.0, precision_digits=2) <= 0:
            return 0.0
        effective = self._avea_effective_commission_rate()
        if effective >= 1.0:
            raise UserError(_("Commission rate is too high to calculate a platform price."))
        raw = retail_inc / (1.0 - effective) if effective > 0 else retail_inc
        return self._avea_apply_price_rounding(raw)

    def _avea_apply_price_rounding(self, price):
        self.ensure_one()
        rule = self.price_rounding_rule or "none"
        if rule == "none":
            return float_round(price, precision_digits=2)
        if rule == "nearest_5":
            return round(price / 5.0) * 5.0
        if rule == "nearest_10":
            return round(price / 10.0) * 10.0
        if rule == "nearest_9":
            if price <= 0:
                return 0.0
            lower = round(price / 10.0) * 10.0 - 1.0
            upper = lower + 10.0
            if lower < 9.0:
                lower = 9.0
                upper = 19.0
            return lower if abs(price - lower) <= abs(price - upper) else upper
        if rule == "nearest_10_then_9":
            base = round(price / 10.0) * 10.0
            rounded = base - 1.0
            return max(rounded, 9.0)
        return float_round(price, precision_digits=2)

    def _avea_product_templates_for_pricing(self):
        self.ensure_one()
        return self.env["product.template"].search(
            [
                ("sale_ok", "=", True),
                ("active", "=", True),
                ("company_id", "in", [False, self.company_id.id]),
            ]
        )

    def _avea_upsert_pricelist_item(self, template, price):
        self.ensure_one()
        PricelistItem = self.env["product.pricelist.item"]
        item = PricelistItem.search(
            [
                ("pricelist_id", "=", self.pricelist_id.id),
                ("applied_on", "=", "1_product"),
                ("product_tmpl_id", "=", template.id),
            ],
            limit=1,
        )
        vals = {
            "pricelist_id": self.pricelist_id.id,
            "applied_on": "1_product",
            "product_tmpl_id": template.id,
            "compute_price": "fixed",
            "fixed_price": price,
        }
        if item:
            item.write(vals)
            return "updated"
        PricelistItem.create(vals)
        return "created"

    def action_update_platform_prices(self):
        self.ensure_one()
        if not self.pricelist_id:
            raise UserError(_("This platform does not have a pricelist yet."))
        created = 0
        updated = 0
        skipped = 0
        for template in self._avea_product_templates_for_pricing():
            retail_inc = template.list_price or 0.0
            if float_compare(retail_inc, 0.0, precision_digits=2) <= 0:
                skipped += 1
                continue
            price = self._avea_platform_price_from_retail(retail_inc)
            result = self._avea_upsert_pricelist_item(template, price)
            if result == "created":
                created += 1
            else:
                updated += 1
        self.last_price_update = fields.Datetime.now()
        message = _(
            "Platform prices updated: %(created)s created, %(updated)s updated, %(skipped)s skipped (no retail price).",
            created=created,
            updated=updated,
            skipped=skipped,
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Platform prices"),
                "message": message,
                "type": "success",
                "sticky": False,
            },
        }

    def action_open_pricelist(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Platform pricelist"),
            "res_model": "product.pricelist",
            "res_id": self.pricelist_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_partner(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Platform customer"),
            "res_model": "res.partner",
            "res_id": self.partner_id.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model
    def _avea_create_partner(self, name, company):
        return self.env["res.partner"].create(
            {
                "name": name,
                "company_id": company.id,
                "customer_rank": 1,
                "comment": _("Avea sales platform contact (auto-created)."),
            }
        )

    def _avea_create_pricelist(self):
        self.ensure_one()
        return self.env["product.pricelist"].create(
            {
                "name": _("%s — Platform prices", self.name),
                "company_id": self.company_id.id,
                "currency_id": self.currency_id.id,
                "avea_sales_platform_id": self.id,
            }
        )

    @api.model_create_multi
    def create(self, vals_list):
        Partner = self.env["res.partner"]
        Pricelist = self.env["product.pricelist"]
        for vals in vals_list:
            company = self.env["res.company"].browse(vals.get("company_id") or self.env.company.id)
            if not vals.get("partner_id"):
                vals["partner_id"] = Partner.create(
                    {
                        "name": vals.get("name"),
                        "company_id": company.id,
                        "customer_rank": 1,
                        "comment": _("Avea sales platform contact (auto-created)."),
                    }
                ).id
            if not vals.get("pricelist_id"):
                vals["pricelist_id"] = Pricelist.create(
                    {
                        "name": _("%s — Platform prices", vals.get("name")),
                        "company_id": company.id,
                        "currency_id": company.currency_id.id,
                    }
                ).id
        records = super().create(vals_list)
        for platform in records:
            if platform.pricelist_id and not platform.pricelist_id.avea_sales_platform_id:
                platform.pricelist_id.avea_sales_platform_id = platform.id
        return records

    def write(self, vals):
        res = super().write(vals)
        if "name" in vals:
            for platform in self:
                if platform.partner_id and platform.partner_id.name != platform.name:
                    platform.partner_id.name = platform.name
                if platform.pricelist_id:
                    platform.pricelist_id.name = _("%s — Platform prices", platform.name)
        return res
