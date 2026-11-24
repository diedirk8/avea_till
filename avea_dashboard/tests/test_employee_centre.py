# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon

from odoo.addons.avea_till.models.operations.withdraw_cash_wizard import (
    SALARY_WAGES_ACCOUNT_CODE,
)


@tagged("post_install", "-at_install", "avea_till")
class TestAveaEmployeeCentre(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Avea Employee Manager",
                "login": "avea_employee_mgr@dev.local",
                "email": "avea_employee_mgr@dev.local",
                "company_id": cls.env.company.id,
                "company_ids": [Command.set([cls.env.company.id])],
                "group_ids": [
                    Command.set([cls.env.ref("avea_till.group_avea_manager").id])
                ],
            }
        )
        cls.salary_account = cls.env["account.account"].search(
            [("code", "=", SALARY_WAGES_ACCOUNT_CODE), ("company_ids", "in", cls.env.company.id)],
            limit=1,
        )
        journals = cls.env.company._avea_expense_journals()
        cls.cash_journal = journals.filtered(lambda rec: rec.type == "cash")[:1] or journals[:1]

    def test_create_from_workspace_sets_employee_flag(self):
        partner = (
            self.env["res.partner"]
            .with_context(avea_employee_workspace=True)
            .create({"name": "Emily Mokoena"})
        )
        self.assertTrue(partner.avea_is_employee)
        self.assertFalse(partner.is_company)
        self.assertEqual(partner.supplier_rank, 0)

    def test_product_shell_uses_avea_employee_form(self):
        partner = self.env["res.partner"].create(
            {"name": "Shell Employee", "avea_is_employee": True, "is_company": False}
        )
        view_id = partner.with_user(self.manager).get_formview_id()
        expected = self.env.ref("avea_till.view_avea_employee_form").id
        self.assertEqual(view_id, expected)

    def test_customer_form_still_wins_for_shoppers(self):
        partner = self.env["res.partner"].create(
            {"name": "Shopper Not Employee", "customer_rank": 1}
        )
        view_id = partner.with_user(self.manager).get_formview_id()
        expected = self.env.ref("avea_till.view_avea_customer_form").id
        self.assertEqual(view_id, expected)

    def test_employee_workspace_opens_employee_form_even_if_also_customer(self):
        partner = self.env["res.partner"].create(
            {
                "name": "Staff Who Shops",
                "customer_rank": 1,
                "avea_is_employee": True,
            }
        )
        view_id = partner.with_user(self.manager).with_context(
            avea_employee_workspace=True
        ).get_formview_id()
        expected = self.env.ref("avea_till.view_avea_employee_form").id
        self.assertEqual(view_id, expected)

    def test_name_create_employee_from_staff_context(self):
        Partner = self.env["res.partner"].with_context(avea_staff_payee=True)
        partner_id, display_name = Partner.name_create("Mg Ferus Temp")
        partner = Partner.browse(partner_id)
        self.assertEqual(display_name, partner.display_name)
        self.assertTrue(partner.avea_is_employee)
        self.assertFalse(partner.is_company)
        self.assertEqual(partner.supplier_rank, 0)

    def test_name_search_prefers_employees(self):
        employee = self.env["res.partner"].create(
            {"name": "Unique Staff Payee", "avea_is_employee": True, "is_company": False}
        )
        Partner = self.env["res.partner"].with_context(avea_staff_payee=True)
        results = Partner.name_search("Unique Staff", domain=[], operator="ilike", limit=8)
        ids = [row[0] for row in results]
        self.assertIn(employee.id, ids)

    def test_expense_salary_posts_against_employee_not_supplier(self):
        if not self.salary_account or not self.cash_journal:
            self.skipTest("Salary account or cash journal missing")
        employee = self.env["res.partner"].create(
            {"name": "Salary Person", "avea_is_employee": True, "is_company": False}
        )
        wizard = self.env["avea.operational.expense.wizard"].create(
            {
                "what_for": "salary",
                "partner_id": employee.id,
                "description": "September salary",
                "amount": 4935.0,
                "expense_date": "2026-09-30",
                "paid_from_journal_id": self.cash_journal.id,
            }
        )
        wizard.action_record_expense()
        employee.invalidate_recordset()
        self.assertTrue(employee.avea_is_employee)
        self.assertEqual(employee.supplier_rank, 0)
        line = self.env["account.bank.statement.line"].search(
            [
                ("avea_employee_id", "=", employee.id),
                ("avea_staff_pay_kind", "=", "salary"),
            ],
            limit=1,
        )
        self.assertTrue(line)
        self.assertEqual(line.partner_id, employee)
        self.assertFalse(line.avea_is_supplier_payment)
        self.assertAlmostEqual(employee.avea_employee_paid_total, 4935.0, places=2)

    def test_expense_advance_then_salary_counts_advance(self):
        if not self.salary_account or not self.cash_journal:
            self.skipTest("Salary account or cash journal missing")
        employee = self.env["res.partner"].create(
            {"name": "Advance Then Salary", "avea_is_employee": True, "is_company": False}
        )
        self.env["avea.operational.expense.wizard"].create(
            {
                "what_for": "advance",
                "partner_id": employee.id,
                "description": "Mid-month advance",
                "amount": 1000.0,
                "expense_date": "2026-09-15",
                "paid_from_journal_id": self.cash_journal.id,
            }
        ).action_record_expense()
        employee.invalidate_recordset()
        self.assertAlmostEqual(employee.avea_employee_advance_outstanding, 1000.0, places=2)
        self.env["avea.operational.expense.wizard"].create(
            {
                "what_for": "salary",
                "partner_id": employee.id,
                "description": "Month-end salary",
                "amount": 4000.0,
                "expense_date": "2026-09-30",
                "paid_from_journal_id": self.cash_journal.id,
            }
        ).action_record_expense()
        employee.invalidate_recordset()
        self.assertAlmostEqual(employee.avea_employee_advance_outstanding, 0.0, places=2)
        self.assertAlmostEqual(employee.avea_employee_paid_total, 5000.0, places=2)
        pays = employee.avea_employee_pay_ids
        self.assertEqual(len(pays), 2)
        kinds = set(pays.mapped("avea_staff_pay_kind"))
        self.assertEqual(kinds, {"advance", "salary"})
        salary = pays.filtered(lambda line: line.avea_staff_pay_kind == "salary")
        self.assertAlmostEqual(salary.avea_staff_advance_deducted, 1000.0, places=2)
        self.assertAlmostEqual(salary.avea_staff_salary_total, 5000.0, places=2)

    def test_usual_salary_shows_cash_still_due_after_advance(self):
        if not self.salary_account or not self.cash_journal:
            self.skipTest("Salary account or cash journal missing")
        employee = self.env["res.partner"].create(
            {
                "name": "Usual Salary Staff",
                "avea_is_employee": True,
                "is_company": False,
                "avea_employee_usual_salary": 5000.0,
                "avea_employee_job_title": "Cashier",
                "avea_employee_pay_frequency": "monthly",
                "avea_employee_number": "0004",
                "avea_employee_id_number": "8305040995081",
            }
        )
        employee.invalidate_recordset()
        self.assertAlmostEqual(employee.avea_employee_cash_due, 5000.0, places=2)
        self.env["avea.operational.expense.wizard"].create(
            {
                "what_for": "advance",
                "partner_id": employee.id,
                "description": "Mid-month",
                "amount": 1000.0,
                "expense_date": "2026-09-15",
                "paid_from_journal_id": self.cash_journal.id,
            }
        ).action_record_expense()
        employee.invalidate_recordset()
        self.assertAlmostEqual(employee.avea_employee_advance_outstanding, 1000.0, places=2)
        self.assertAlmostEqual(employee.avea_employee_cash_due, 4000.0, places=2)

    def test_pay_history_action_lists_staff_payments(self):
        action = self.env["account.bank.statement.line"].action_avea_employee_pay_history()
        self.assertEqual(action["res_model"], "account.bank.statement.line")
        self.assertTrue(action.get("domain"))

    def test_record_salary_action_prefills_employee(self):
        employee = self.env["res.partner"].create(
            {"name": "Prefill Staff", "avea_is_employee": True, "is_company": False}
        )
        action = employee.action_avea_record_employee_salary()
        self.assertEqual(action["res_model"], "avea.withdraw.cash.wizard")
        self.assertEqual(action["context"]["default_employee_id"], employee.id)
        self.assertEqual(action["context"]["default_withdrawal_purpose"], "salary_wages")

    def test_salary_without_employee_is_rejected(self):
        if not self.cash_journal:
            self.skipTest("No cash journal")
        with self.assertRaises(ValidationError):
            self.env["avea.withdraw.cash.wizard"].create(
                {
                    "cash_journal_id": self.cash_journal.id,
                    "withdrawal_purpose": "staff_advance",
                    "amount": 100.0,
                }
            )
