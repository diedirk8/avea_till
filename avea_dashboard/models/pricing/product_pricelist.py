# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ProductPricelist(models.Model):
    _inherit = "product.pricelist"

    avea_pos_available = fields.Boolean(
        string="Available on till",
        default=False,
        help=(
            "When active, this price list is added to every point of sale for the "
            "same company so staff can sell at these prices when a customer uses it."
        ),
    )
    avea_item_count = fields.Integer(
        string="Rules",
        compute="_compute_avea_stats",
    )
    avea_customer_count = fields.Integer(
        string="Customers",
        compute="_compute_avea_stats",
    )
    avea_rule_summary = fields.Char(
        string="What it does",
        compute="_compute_avea_stats",
    )
    avea_notes = fields.Text(string="Notes")

    def _avea_partner_domain_on_pricelist(self):
        """Partners with this list explicitly assigned (Odoo 19 stores it on specific_property_product_pricelist)."""
        self.ensure_one()
        return [("specific_property_product_pricelist", "=", self.id)]

    @api.depends(
        "item_ids",
        "item_ids.applied_on",
        "item_ids.compute_price",
        "item_ids.price",
        "item_ids.name",
    )
    def _compute_avea_stats(self):
        Partner = self.env["res.partner"]
        for pricelist in self:
            pricelist.avea_item_count = len(pricelist.item_ids)
            summaries = [
                (line.price or line.name or "").strip()
                for line in pricelist.item_ids
            ]
            pricelist.avea_rule_summary = "; ".join(part for part in summaries if part)
            partner_domain = pricelist._avea_partner_domain_on_pricelist()
            if pricelist.company_id:
                pricelist.avea_customer_count = Partner.with_company(
                    pricelist.company_id
                ).search_count(partner_domain)
            else:
                pricelist.avea_customer_count = Partner.search_count(partner_domain)

    @api.constrains("avea_sales_platform_id", "avea_pos_available")
    def _check_avea_platform_pos_flag(self):
        for pricelist in self:
            if pricelist.avea_sales_platform_id and pricelist.avea_pos_available:
                raise ValidationError(
                    _(
                        "Sales platform price lists are managed under Sales Platforms. "
                        "Turn off “Available on till” here."
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._avea_sync_pos_registration()
        return records

    def write(self, vals):
        res = super().write(vals)
        if {"avea_pos_available", "active"} & set(vals):
            self._avea_sync_pos_registration()
        return res

    def unlink(self):
        if any(pricelist.avea_sales_platform_id for pricelist in self):
            raise UserError(
                _(
                    "This price list belongs to a sales platform. "
                    "Archive or change it from Sales Platforms instead."
                )
            )
        return super().unlink()

    def _avea_product_templates_for_lines(self):
        self.ensure_one()
        return self.env["product.template"].search(
            [
                ("sale_ok", "=", True),
                ("active", "=", True),
                ("company_id", "in", [False, self.company_id.id]),
            ]
        )

    def _avea_upsert_fixed_line(self, template, price):
        self.ensure_one()
        if self.avea_sales_platform_id:
            raise UserError(_("Edit platform prices from Sales Platforms."))
        Item = self.env["product.pricelist.item"]
        item = Item.search(
            [
                ("pricelist_id", "=", self.id),
                ("applied_on", "=", "1_product"),
                ("product_tmpl_id", "=", template.id),
            ],
            limit=1,
        )
        vals = {
            "pricelist_id": self.id,
            "applied_on": "1_product",
            "product_tmpl_id": template.id,
            "compute_price": "fixed",
            "fixed_price": price,
        }
        if item:
            item.write(vals)
            return "updated"
        Item.create(vals)
        return "created"

    def _avea_sync_pos_registration(self):
        PosConfig = self.env["pos.config"]
        for pricelist in self:
            if pricelist.avea_sales_platform_id:
                continue
            if not pricelist.company_id:
                continue
            configs = PosConfig.search([("company_id", "=", pricelist.company_id.id)])
            if pricelist.active and pricelist.avea_pos_available:
                for config in configs:
                    config._avea_register_sales_platform_pricelist(pricelist)

    def action_avea_fill_from_shelf(self):
        self.ensure_one()
        created = updated = 0
        for template in self._avea_product_templates_for_lines():
            price = template.list_price or 0.0
            if self._avea_upsert_fixed_line(template, price) == "created":
                created += 1
            else:
                updated += 1
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Lines filled from retail prices"),
                "message": _(
                    "%(created)s new lines and %(updated)s updated from current shelf prices. "
                    "Retail product prices were not changed.",
                    created=created,
                    updated=updated,
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def action_avea_view_customers(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Customers on %(name)s", name=self.display_name),
            "res_model": "res.partner",
            "view_mode": "list,form",
            "domain": self._avea_partner_domain_on_pricelist(),
            "context": {
                "default_property_product_pricelist": self.id,
                "default_specific_property_product_pricelist": self.id,
            },
        }
