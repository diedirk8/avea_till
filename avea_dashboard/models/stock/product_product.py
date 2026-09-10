# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models

_AVEA_BRACKET_REF_RE = re.compile(r"^\[(?P<ref>[^\]]+)\]\s*(?P<name>.*)$")


class ProductProduct(models.Model):
    _inherit = "product.product"

    avea_markup_percent = fields.Float(
        related="product_tmpl_id.avea_markup_percent",
        readonly=False,
    )
    avea_margin_percent = fields.Float(
        related="product_tmpl_id.avea_margin_percent",
        readonly=False,
    )
    avea_supplier_id = fields.Many2one(
        related="product_tmpl_id.avea_supplier_id",
        readonly=False,
    )
    is_storable = fields.Boolean(
        related="product_tmpl_id.is_storable",
        readonly=False,
    )
    avea_cost_ex_tax = fields.Float(
        related="product_tmpl_id.avea_cost_ex_tax",
        readonly=False,
    )

    def _avea_plain_name(self):
        """Full product title without the internal reference/SKU prefix."""
        self.ensure_one()
        reference = (self.default_code or "").strip()
        raw = (self.display_name or self.name or "").strip()
        if not raw:
            return ""
        match = _AVEA_BRACKET_REF_RE.match(raw)
        if match:
            name = (match.group("name") or "").strip()
            return name or raw
        if reference and raw.startswith(f"[{reference}]"):
            stripped = raw[len(f"[{reference}]") :].strip()
            return stripped or raw
        return raw

    @api.model
    def get_formview_id(self, access_uid=None):
        """Use the Avea compact popup when creating/editing from Receive Stock."""
        if self.env.context.get("avea_receive_id") or self.env.context.get(
            "avea_stock_receive_create"
        ):
            return self.env.ref(
                "avea_till.view_avea_stock_product_variant_quick_form"
            ).id
        return super().get_formview_id(access_uid=access_uid)

    @api.model
    def name_create(self, name):
        """From Receive Stock typing: create an Avea-ready stock item quickly."""
        if self.env.context.get("avea_receive_id") or self.env.context.get(
            "avea_stock_receive_create"
        ):
            template = (
                self.env["product.template"]
                .with_context(avea_stock_workspace=True)
                .create(
                    {
                        "name": name,
                        "available_in_pos": True,
                        "sale_ok": True,
                        "purchase_ok": True,
                        "is_storable": True,
                        "type": "consu",
                    }
                )
            )
            variant = template.product_variant_id
            return variant.id, variant.display_name
        return super().name_create(name)

    def get_formview_action(self, access_uid=None):
        """Open the Avea Stock Item form when creating/editing from Receive Stock."""
        if self.env.context.get("avea_receive_id") or self.env.context.get(
            "avea_stock_receive_create"
        ):
            receive_id = self.env.context.get("avea_receive_id")
            templates = self.mapped("product_tmpl_id")
            if len(templates) == 1 and templates.id:
                action = templates.action_avea_open_stock_item()
                if receive_id:
                    action = dict(action)
                    context = dict(action.get("context") or {})
                    context["avea_return_receive_id"] = receive_id
                    action["context"] = context
                return action
            action = (
                self.env["product.template"]
                .with_context(avea_quick_product_add=True)
                .action_avea_new_stock_item()
            )
            if receive_id:
                action = dict(action)
                context = dict(action.get("context") or {})
                context.update(
                    {
                        "avea_return_receive_id": receive_id,
                        "avea_quick_product_add": True,
                    }
                )
                action["context"] = context
                action["target"] = "new"
            return action
        return super().get_formview_action(access_uid=access_uid)
