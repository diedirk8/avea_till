from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cash_up_manager = env.ref(
        "avea_till.group_avea_cash_up_manager", raise_if_not_found=False
    )
    pos_manager = env.ref("point_of_sale.group_pos_manager", raise_if_not_found=False)
    if cash_up_manager and pos_manager and cash_up_manager not in pos_manager.implied_ids:
        pos_manager.write({"implied_ids": [(4, cash_up_manager.id)]})
