# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_till")
class TestAveaUserAccess(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls._create_user("users_mgr", "avea_till.group_avea_manager")
        cls.cashier = cls._create_user("users_cash", "avea_till.group_avea_cashier")

    @classmethod
    def _create_user(cls, suffix, group_xmlid):
        group = cls.env.ref(group_xmlid)
        return cls.env["res.users"].create(
            {
                "name": "Test %s" % suffix,
                "login": "test_%s@avea.local" % suffix,
                "email": "test_%s@avea.local" % suffix,
                "groups_id": [(6, 0, [group.id, cls.env.ref("base.group_user").id])],
            }
        )

    def test_manager_can_open_avea_users_action(self):
        action = self.manager.action_open_avea_users()
        self.assertEqual(action["res_model"], "res.users")

    def test_cashier_cannot_open_avea_users_action(self):
        with self.assertRaises(AccessError):
            self.cashier.action_open_avea_users()

    def test_role_change_to_cashier(self):
        staff = self.env["res.users"].with_user(self.manager).create(
            {
                "name": "New Staff",
                "login": "new_staff@avea.local",
                "email": "new_staff@avea.local",
                "avea_access_role": "cashier",
            }
        )
        self.assertTrue(staff.has_group("avea_till.group_avea_cashier"))
        self.assertFalse(staff.has_group("avea_till.group_avea_manager"))

    def test_cashier_extra_pos_manager_toggle(self):
        staff = self.env["res.users"].with_user(self.manager).create(
            {
                "name": "POS Lead",
                "login": "pos_lead@avea.local",
                "email": "pos_lead@avea.local",
                "avea_access_role": "cashier",
            }
        )
        staff.with_user(self.manager).write({"avea_perm_pos_manager": True})
        self.assertTrue(staff.has_group("point_of_sale.group_pos_manager"))
