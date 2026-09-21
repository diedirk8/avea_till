# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


ODOO_ROOT_XMLIDS = {
    "mail.menu_root_discuss",
    "contacts.menu_contacts",
    "sale.sale_menu_root",
    "spreadsheet_dashboard.spreadsheet_dashboard_menu_root",
    "point_of_sale.menu_point_root",
    "account.menu_finance",
    "purchase.menu_purchase_root",
    "stock.menu_stock_root",
    "hr.menu_hr_root",
    "base.menu_management",
    "base.menu_administration",
    "base.menu_tests",
}

CASHIER_MENUS = {
    "avea_till.menu_avea_root",
    "avea_till.menu_avea_pos_sell",
    "avea_till.menu_avea_till",
    "avea_till.menu_avea_session_dashboard",
}

MANAGER_EXTRA_MENUS = {
    "avea_till.menu_avea_business_section",
    "avea_till.menu_avea_stock",
    "avea_till.menu_avea_operations",
    "avea_till.menu_avea_promotion",
    "avea_till.menu_avea_cash_up",
    "avea_till.menu_avea_customer_credit",
    "avea_till.menu_avea_settings",
    "avea_till.menu_avea_sales_ledger",
}


@tagged("post_install", "-at_install", "avea_till")
class TestAveaUxRoles(TestPoSCommon):
    """Owner / Manager / Cashier shell, menus, home action, and Sell."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.owner = cls._create_role_user("owner", "avea_till.group_avea_owner")
        cls.manager = cls._create_role_user("manager", "avea_till.group_avea_manager")
        cls.cashier = cls._create_role_user("cashier", "avea_till.group_avea_cashier")

    @classmethod
    def _create_role_user(cls, role, xmlid):
        return cls.env["res.users"].create(
            {
                "name": "Avea UX %s" % role.title(),
                "login": "avea_ux_%s@dev.local" % role,
                "email": "avea_ux_%s@dev.local" % role,
                "company_id": cls.env.company.id,
                "company_ids": [Command.set([cls.env.company.id])],
                "group_ids": [Command.set([cls.env.ref(xmlid).id])],
            }
        )

    def _menu_xmlids(self, user):
        menus = self.env["ir.ui.menu"].with_user(user).load_menus(False)
        return {
            menus[menu_id]["xmlid"]
            for menu_id in menus
            if menu_id != "root" and menus[menu_id].get("xmlid")
        }

    def _root_xmlids(self, user):
        menus = self.env["ir.ui.menu"].with_user(user).load_menus(False)
        return {
            menus[menu_id]["xmlid"]
            for menu_id in menus["root"]["children"]
            if menus[menu_id].get("xmlid")
        }

    def test_roles_compose_existing_capabilities(self):
        self.assertTrue(self.cashier.has_group("point_of_sale.group_pos_user"))
        self.assertTrue(self.cashier.has_group("stock.group_stock_user"))
        self.assertTrue(self.cashier.has_group("avea_till.group_avea_cash_up_user"))
        self.assertFalse(self.cashier.has_group("point_of_sale.group_pos_manager"))
        self.assertFalse(self.cashier.has_group("avea_till.group_avea_credit_manager"))
        self.assertFalse(self.cashier.has_group("avea_till.group_avea_correct_payment"))
        self.assertFalse(self.cashier.has_group("base.group_system"))

        for user in (self.manager, self.owner):
            self.assertTrue(user.has_group("avea_till.group_avea_cashier"))
            self.assertTrue(user.has_group("point_of_sale.group_pos_manager"))
            self.assertTrue(user.has_group("avea_till.group_avea_cash_up_manager"))
            self.assertTrue(user.has_group("avea_till.group_avea_credit_manager"))
            self.assertTrue(user.has_group("avea_till.group_avea_correct_payment"))
            self.assertFalse(user.has_group("base.group_system"))

        self.assertTrue(self.owner.has_group("avea_till.group_avea_manager"))

    def test_normal_users_only_see_avea_root(self):
        for user in (self.cashier, self.manager, self.owner):
            roots = self._root_xmlids(user)
            self.assertEqual(roots, {"avea_till.menu_avea_root"})
            self.assertFalse(roots & ODOO_ROOT_XMLIDS)

    def test_system_user_still_sees_odoo_menus(self):
        admin = self.env.ref("base.user_admin")
        roots = self._root_xmlids(admin)
        self.assertIn("avea_till.menu_avea_root", roots)
        self.assertTrue(roots & ODOO_ROOT_XMLIDS)

    def test_cashier_nav_is_sell_and_sessions(self):
        xmlids = self._menu_xmlids(self.cashier)
        self.assertTrue(CASHIER_MENUS <= xmlids)
        self.assertFalse(xmlids & MANAGER_EXTRA_MENUS)
        self.assertNotIn("avea_till.menu_avea_configuration", xmlids)

    def test_manager_and_owner_see_full_avea_nav(self):
        for user in (self.manager, self.owner):
            xmlids = self._menu_xmlids(user)
            self.assertTrue(CASHIER_MENUS <= xmlids)
            self.assertTrue(MANAGER_EXTRA_MENUS <= xmlids)
            self.assertNotIn("point_of_sale.menu_point_root", xmlids)

    def test_product_shell_flag_for_normal_users(self):
        for user in (self.cashier, self.manager, self.owner):
            self.assertTrue(user._avea_uses_product_shell())
        self.assertFalse(self.env.ref("base.user_admin")._avea_uses_product_shell())

    def test_admin_keeps_odoo_shell_despite_avea_groups(self):
        admin = self.env.ref("base.user_admin")
        self.assertTrue(admin.has_group("avea_till.group_avea_cashier"))
        self.assertFalse(admin._avea_uses_product_shell())

    def test_web_home_action_is_avea_dashboard(self):
        overview = self.env.ref("avea_till.action_avea_business_overview")
        sessions = self.env.ref("avea_till.action_avea_session_dashboard")
        self.assertEqual(self.cashier._avea_home_action().id, sessions.id)
        self.assertEqual(self.manager._avea_home_action().id, overview.id)
        self.assertEqual(self.owner._avea_home_action().id, overview.id)
        self.assertEqual(self.cashier.action_id.id, sessions.id)
        self.assertEqual(self.manager.action_id.id, overview.id)
        self.assertFalse(self.env.ref("base.user_admin")._avea_home_action())

    def test_sell_opens_existing_pos(self):
        action = (
            self.env["pos.config"].with_user(self.cashier).action_avea_open_pos()
        )
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertIn("/pos/ui/%s" % self.config.id, action["url"])
