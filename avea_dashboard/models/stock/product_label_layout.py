# -*- coding: utf-8 -*-
from odoo import api, models

_AVEA_DIRECT_LABEL_PRINT_PARAM = "avea_till.direct_product_label_print"


class ProductLabelLayout(models.TransientModel):
    _inherit = "product.label.layout"

    @api.model
    def _avea_direct_label_print_enabled(self):
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(_AVEA_DIRECT_LABEL_PRINT_PARAM)
            == "1"
        )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self._avea_direct_label_print_enabled() and "print_format" in fields_list:
            res["print_format"] = "dymo"
        return res

    def process(self):
        report_action = super().process()
        if not self._avea_direct_label_print_enabled() or self.print_format != "dymo":
            return report_action
        ctx = dict(report_action.get("context") or {})
        ctx["avea_direct_label_print"] = True
        report_action["context"] = ctx
        return report_action
