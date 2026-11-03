# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    avea_pricelist_preview_price = fields.Monetary(
        string="This list",
        compute="_compute_avea_pricelist_preview",
        currency_field="avea_pricelist_preview_currency_id",
    )
    avea_pricelist_preview_shelf = fields.Monetary(
        string="Shelf",
        compute="_compute_avea_pricelist_preview",
        currency_field="avea_pricelist_preview_currency_id",
    )
    avea_pricelist_preview_cost = fields.Monetary(
        string="Cost",
        compute="_compute_avea_pricelist_preview",
        currency_field="avea_pricelist_preview_currency_id",
    )
    avea_pricelist_preview_rule = fields.Char(
        string="Rule",
        compute="_compute_avea_pricelist_preview",
    )
    avea_pricelist_preview_currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_avea_pricelist_preview",
    )

    @api.depends("list_price", "standard_price", "product_variant_id", "currency_id")
    @api.depends_context("avea_pricelist_id")
    def _compute_avea_pricelist_preview(self):
        pricelist = self.env["product.pricelist"].browse(
            self.env.context.get("avea_pricelist_id") or 0
        ).exists()
        currency = (
            pricelist.currency_id
            if pricelist
            else (self.env.company.currency_id or self.env["res.currency"])
        )
        results = {}
        if pricelist:
            variants = self.mapped("product_variant_id")
            if variants:
                results = pricelist._compute_price_rule(variants, 1.0)
        Item = self.env["product.pricelist.item"]
        for template in self:
            variant = template.product_variant_id
            shelf = template.list_price or 0.0
            cost = template.standard_price or 0.0
            price, rule_id = (
                results.get(variant.id, (shelf, False)) if variant else (shelf, False)
            )
            template.avea_pricelist_preview_price = price or 0.0
            template.avea_pricelist_preview_shelf = shelf
            template.avea_pricelist_preview_cost = cost
            template.avea_pricelist_preview_currency_id = (
                currency.id if currency else template.currency_id.id
            )
            template.avea_pricelist_preview_rule = template._avea_preview_rule_label(
                Item.browse(rule_id) if rule_id else Item
            )

    def _avea_preview_rule_label(self, rule):
        self.ensure_one()
        if not rule:
            return _("No matching rule — shelf price")
        result = (rule.avea_result or "").strip()
        if rule.applied_on == "3_global":
            scope = _("All products")
        elif rule.applied_on == "2_product_category":
            scope = rule.categ_id.display_name or _("Category")
        elif rule.applied_on == "1_product":
            scope = rule.product_tmpl_id.display_name or _("Product")
        else:
            scope = rule.product_id.display_name or _("Variant")
        level = rule.avea_priority or 0
        if result:
            return _(
                "Level %(level)s · %(scope)s · %(result)s",
                level=level,
                scope=scope,
                result=result,
            )
        return _("Level %(level)s · %(scope)s", level=level, scope=scope)
