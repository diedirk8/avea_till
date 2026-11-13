# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AveaStockProductMerge(models.TransientModel):
    _name = "avea.stock.product.merge"
    _description = "Merge Stock Products"

    product_tmpl_ids = fields.Many2many(
        "product.template",
        string="Products to merge",
        required=True,
    )
    dst_product_tmpl_id = fields.Many2one(
        "product.template",
        string="Keep this product",
        required=True,
        domain="[('id', 'in', product_tmpl_ids)]",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get("active_ids") or []
        if active_ids:
            res["product_tmpl_ids"] = [(6, 0, active_ids)]
            res["dst_product_tmpl_id"] = active_ids[0]
        return res

    def _avea_repoint_product(self, src_product, dst_product):
        """Move references from one variant to another where the field exists."""
        if src_product == dst_product:
            return
        repoint_specs = [
            ("sale.order.line", "product_id"),
            ("purchase.order.line", "product_id"),
            ("stock.move", "product_id"),
            ("stock.move.line", "product_id"),
            ("stock.quant", "product_id"),
            ("account.move.line", "product_id"),
            ("pos.order.line", "product_id"),
        ]
        for model_name, field_name in repoint_specs:
            Model = self.env.get(model_name)
            if not Model or field_name not in Model._fields:
                continue
            records = Model.sudo().search([(field_name, "=", src_product.id)])
            if records:
                records.write({field_name: dst_product.id})

    def _avea_merge_single_variant_templates(self, dst, sources):
        dst_variant = dst.product_variant_ids[:1]
        if not dst_variant:
            raise UserError(_("The destination product has no variant."))
        for src in sources:
            if len(src.product_variant_ids) != 1:
                raise UserError(
                    _(
                        "“%(name)s” has multiple variants. "
                        "Merge is only supported for single-variant products.",
                        name=src.display_name,
                    )
                )
            src_variant = src.product_variant_ids[:1]
            self._avea_repoint_product(src_variant, dst_variant)
            src.sudo().write({"active": False})

    def action_merge_products(self):
        self.ensure_one()
        if len(self.product_tmpl_ids) < 2:
            raise UserError(_("Select at least two products to merge."))
        dst = self.dst_product_tmpl_id
        if dst not in self.product_tmpl_ids:
            raise UserError(_("Choose the product to keep from the selected list."))
        sources = self.product_tmpl_ids - dst
        self._avea_merge_single_variant_templates(dst, sources)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Products merged"),
                "message": _(
                    "%(count)s product(s) merged into “%(name)s”. "
                    "Duplicates were archived.",
                    count=len(sources),
                    name=dst.display_name,
                ),
                "type": "success",
                "next": dst.action_avea_open_stock_item(),
            },
        }
