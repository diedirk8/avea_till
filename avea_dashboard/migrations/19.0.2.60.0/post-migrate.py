from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    correct_payment = env.ref(
        "avea_till.group_avea_correct_payment", raise_if_not_found=False
    )
    pos_manager = env.ref("point_of_sale.group_pos_manager", raise_if_not_found=False)
    if (
        correct_payment
        and pos_manager
        and correct_payment not in pos_manager.implied_ids
    ):
        pos_manager.write({"implied_ids": [(4, correct_payment.id)]})
