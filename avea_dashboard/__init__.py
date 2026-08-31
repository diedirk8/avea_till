from . import models
from . import report
from .models.till import till_dashboard  # register avea.till.dashboard


def post_init_hook(env):
    env["pos.config"]._avea_credit_enable_all_pos_configs()
    env["res.company"]._avea_credit_setup_all_companies()
    env["res.company"].search([])._avea_ensure_owner_wizard_journal_defaults()
    _avea_credit_assign_default_groups(env)
    _avea_cash_up_assign_default_groups(env)
    _avea_correct_payment_assign_default_groups(env)


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


def _avea_cash_up_assign_default_groups(env):
    cash_up_manager = env.ref(
        "avea_till.group_avea_cash_up_manager", raise_if_not_found=False
    )
    if not cash_up_manager:
        return
    pos_manager = env.ref("point_of_sale.group_pos_manager", raise_if_not_found=False)
    if pos_manager and cash_up_manager not in pos_manager.implied_ids:
        pos_manager.write({"implied_ids": [(4, cash_up_manager.id)]})
    admin = env.ref("base.user_admin", raise_if_not_found=False)
    if admin and cash_up_manager not in admin.group_ids:
        admin.write({"group_ids": [(4, cash_up_manager.id)]})


def _avea_correct_payment_assign_default_groups(env):
    correct_payment = env.ref(
        "avea_till.group_avea_correct_payment", raise_if_not_found=False
    )
    if not correct_payment:
        return
    pos_manager = env.ref("point_of_sale.group_pos_manager", raise_if_not_found=False)
    if pos_manager and correct_payment not in pos_manager.implied_ids:
        pos_manager.write({"implied_ids": [(4, correct_payment.id)]})
    admin = env.ref("base.user_admin", raise_if_not_found=False)
    if admin and correct_payment not in admin.group_ids:
        admin.write({"group_ids": [(4, correct_payment.id)]})
