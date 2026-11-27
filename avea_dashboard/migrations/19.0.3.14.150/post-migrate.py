# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    product_model = env["product.template"]
    count = product_model.search_count([("available_in_pos", "=", True), ("sale_ok", "=", True)])
    if count:
        target = min(max(count + 500, 5000), 15000)
        param = env["ir.config_parameter"].sudo()
        try:
            current = int(param.get_param("point_of_sale.limited_product_count") or 5000)
        except ValueError:
            current = 5000
        if target > current:
            param.set_param("point_of_sale.limited_product_count", str(target))
    configs = env["pos.config"].search([])
    if configs:
        configs.write(
            {
                "avea_pos_auto_search_server": True,
                "avea_preload_all_pos_products": True,
            }
        )
