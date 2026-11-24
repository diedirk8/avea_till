# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaEmployeeAccess(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = cls._create_user("owner", "avea_till.group_avea_owner")
        cls.manager = cls._create_user("manager", "avea_till.group_avea_manager")
        cls.cashier = cls._create_user("cashier", "avea_till.group_avea_cashier")
        cls.employee = cls.env["res.partner"].create(
            {
                "name": "Private Staff",
                "avea_is_employee": True,
                "is_company": False,
                "avea_employee_id_number": "8305040995081",
                "avea_employee_usual_salary": 6500.0,
            }
        )

    @classmethod
    def _create_user(cls, role, xmlid):
        return cls.env["res.users"].create(
            {
                "name": "Avea Emp Access %s" % role.title(),
                "login": "avea_emp_access_%s@dev.local" % role,
                "email": "avea_emp_access_%s@dev.local" % role,
                "company_id": cls.env.company.id,
                "company_ids": [Command.set([cls.env.company.id])],
                "group_ids": [Command.set([cls.env.ref(xmlid).id])],
            }
        )

    def test_owner_has_employee_access_manager_does_not(self):
        Users = self.env["res.users"]
        self.assertTrue(Users._avea_can_access_employees(self.owner))
        self.assertFalse(Users._avea_can_access_employees(self.manager))
        self.assertFalse(Users._avea_can_access_employees(self.cashier))
        self.assertTrue(self.owner.avea_perm_employees)
        self.assertFalse(self.manager.avea_perm_employees)

    def test_manager_cannot_open_employee_actions(self):
        with self.assertRaises(AccessError):
            self.employee.with_user(self.manager).action_avea_open_employee()
        with self.assertRaises(AccessError):
            self.env["account.bank.statement.line"].with_user(
                self.manager
            ).action_avea_employee_pay_history()

    def test_manager_cannot_read_id_number(self):
        with self.assertRaises(AccessError):
            self.employee.with_user(self.manager).read(["avea_employee_id_number"])

    def test_granting_employees_toggle_unlocks_manager(self):
        self.manager.with_user(self.owner).write({"avea_perm_employees": True})
        self.manager.invalidate_recordset()
        self.assertTrue(
            self.env["res.users"]._avea_can_access_employees(self.manager)
        )
        action = self.employee.with_user(self.manager).action_avea_open_employee()
        self.assertEqual(action["res_id"], self.employee.id)
        values = self.employee.with_user(self.manager).read(["avea_employee_id_number"])
        self.assertEqual(values[0]["avea_employee_id_number"], "8305040995081")

    def test_manager_withdraw_hides_salary_options(self):
        options = dict(
            self.env["avea.withdraw.cash.wizard"]
            .with_user(self.manager)
            ._selection_withdrawal_purpose()
        )
        self.assertNotIn("salary_wages", options)
        self.assertNotIn("staff_advance", options)
        owner_options = dict(
            self.env["avea.withdraw.cash.wizard"]
            .with_user(self.owner)
            ._selection_withdrawal_purpose()
        )
        self.assertIn("salary_wages", owner_options)
        self.assertIn("staff_advance", owner_options)
