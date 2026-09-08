# -*- coding: utf-8 -*-
from odoo import api, models


class ProductProduct(models.Model):
    _inherit = "product.product"

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
            "avea_stock_workspace"
        ):
            receive_id = self.env.context.get("avea_receive_id")
            templates = self.mapped("product_tmpl_id")
            if len(templates) == 1 and templates.id:
                action = templates.action_avea_open_stock_item()
            else:
                action = self.env["product.template"].action_avea_new_stock_item()
            if receive_id:
                action = dict(action)
                context = dict(action.get("context") or {})
                context["avea_return_receive_id"] = receive_id
                action["context"] = context
            return action
        return super().get_formview_action(access_uid=access_uid)
