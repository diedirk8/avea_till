def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    env["pos.config"]._avea_credit_enable_all_pos_configs()
    env["res.company"]._avea_credit_setup_all_companies()

    credit_manager = env.ref("avea_till.group_avea_credit_manager", raise_if_not_found=False)
    if credit_manager:
        pos_manager = env.ref("point_of_sale.group_pos_manager", raise_if_not_found=False)
        if pos_manager and credit_manager not in pos_manager.implied_ids:
            pos_manager.write({"implied_ids": [(4, credit_manager.id)]})
        admin = env.ref("base.user_admin", raise_if_not_found=False)
        if admin and credit_manager not in admin.group_ids:
            admin.write({"group_ids": [(4, credit_manager.id)]})
