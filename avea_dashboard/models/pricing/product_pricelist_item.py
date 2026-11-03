# -*- coding: utf-8 -*-
from odoo import _, api, fields, models

_PRIORITY_BY_APPLIED_ON = {
    "0_product_variant": 1,
    "1_product": 2,
    "2_product_category": 3,
    "3_global": 10,
}


def _avea_format_number(amount):
    text = ("%.2f" % (amount or 0.0)).rstrip("0").rstrip(".")
    return text or "0"


class ProductPricelistItem(models.Model):
    _inherit = "product.pricelist.item"

    avea_priority = fields.Integer(
        string="Level",
        default=0,
        help="1 is applied first. Use a low level for exceptions and a high level (10) for All products.",
    )
    avea_method = fields.Selection(
        selection=[
            ("cost_plus", "Cost + markup %"),
            ("off_sales", "% off shelf price"),
            ("fixed", "Fixed price"),
        ],
        string="How",
        compute="_compute_avea_method_amount",
        inverse="_inverse_avea_method_amount",
    )
    avea_amount = fields.Float(
        string="Amount",
        digits=(16, 2),
        compute="_compute_avea_method_amount",
        inverse="_inverse_avea_method_amount",
        help="Markup %, discount %, or the fixed price — depending on How.",
    )
    avea_result = fields.Char(
        string="Result",
        compute="_compute_avea_method_amount",
    )

    def init(self):
        super().init()
        self.env.cr.execute(
            """
            UPDATE product_pricelist_item
               SET avea_priority = CASE applied_on
                    WHEN '0_product_variant' THEN 1
                    WHEN '1_product' THEN 2
                    WHEN '2_product_category' THEN 3
                    ELSE 10
               END
             WHERE avea_priority IS NULL OR avea_priority = 0
            """
        )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("avea_priority"):
                applied = vals.get("applied_on", "3_global")
                vals["avea_priority"] = _PRIORITY_BY_APPLIED_ON.get(applied, 10)
        return super().create(vals_list)

    @api.onchange("applied_on")
    def _onchange_avea_applied_on_priority(self):
        self.avea_priority = _PRIORITY_BY_APPLIED_ON.get(self.applied_on, 10)

    @api.onchange("avea_method", "avea_amount")
    def _onchange_avea_method_amount(self):
        self._inverse_avea_method_amount()

    @api.depends(
        "compute_price",
        "base",
        "percent_price",
        "price_markup",
        "price_discount",
        "fixed_price",
        "currency_id",
        "currency_id.symbol",
    )
    def _compute_avea_method_amount(self):
        for item in self:
            if item.compute_price == "fixed":
                item.avea_method = "fixed"
                item.avea_amount = item.fixed_price
            elif item.compute_price == "formula" and item.base == "standard_price":
                item.avea_method = "cost_plus"
                item.avea_amount = item.price_markup
            else:
                item.avea_method = "off_sales"
                if item.compute_price == "percentage":
                    item.avea_amount = item.percent_price
                else:
                    item.avea_amount = item.price_discount
            item.avea_result = item._avea_result_text()

    def _avea_result_text(self):
        self.ensure_one()
        amount = _avea_format_number(self.avea_amount)
        method = self.avea_method
        if method == "cost_plus":
            return _("%s%% on top of cost") % amount
        if method == "off_sales":
            return _("%s%% off the shelf price") % amount
        symbol = (self.currency_id.symbol or "").strip()
        if symbol:
            return _("Fixed %s %s") % (amount, symbol)
        return _("Fixed %s") % amount

    def _inverse_avea_method_amount(self):
        for item in self:
            method = item.avea_method or "cost_plus"
            amount = item.avea_amount or 0.0
            if method == "fixed":
                item.compute_price = "fixed"
                item.fixed_price = amount
            elif method == "cost_plus":
                item.compute_price = "formula"
                item.base = "standard_price"
                item.price_markup = amount
                item.price_discount = 0.0
                item.percent_price = 0.0
            else:
                item.compute_price = "percentage"
                item.percent_price = amount
                item.price_discount = 0.0
                item.price_markup = 0.0

    def _avea_sort_key(self):
        self.ensure_one()
        priority = self.avea_priority or _PRIORITY_BY_APPLIED_ON.get(self.applied_on, 10)
        return (priority, self.applied_on or "9", -(self.id or 0))
