from . import models
from . import report
from .models.till import till_dashboard  # register avea.till.dashboard


def post_init_hook(env):
    env["pos.config"]._avea_credit_enable_all_pos_configs()
    env["res.company"]._avea_credit_setup_all_companies()
    _avea_credit_assign_default_groups(env)


def _avea_credit_assign_default_groups(env):
    credit_manager = env.ref("avea_till.group_avea_credit_manager", raise_if_not_found=False)
    if not credit_manager:
        return
    pos_manager = env.ref("point_of_sale.group_pos_manager", raise_if_not_found=False)
    if pos_manager and credit_manager not in pos_manager.implied_ids:
        pos_manager.write({"implied_ids": [(4, credit_manager.id)]})
    admin = env.ref("base.user_admin", raise_if_not_found=False)
    if admin and credit_manager not in admin.group_ids:
        admin.write({"group_ids": [(4, credit_manager.id)]})
