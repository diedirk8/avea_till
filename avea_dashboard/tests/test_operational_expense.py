# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_till")
class TestAveaOperationalExpense(TransactionCase):
    def test_resolve_partner_requires_selection(self):
        wizard = self.env["avea.operational.expense.wizard"].create(
            {
                "description": "Test",
                "amount": 10.0,
                "expense_account_id": self.env["account.account"]
                .search(
                    [
                        ("company_ids", "in", self.env.company.id),
                        ("account_type", "in", ("expense", "expense_other")),
                    ],
                    limit=1,
                )
                .id,
            }
        )
        with self.assertRaises(UserError):
            wizard._avea_resolve_partner()

    def test_resolve_partner_creates_new_supplier(self):
        wizard = self.env["avea.operational.expense.wizard"].create(
            {
                "add_new_supplier": True,
                "new_supplier_name": "Expense Wizard Supplier",
                "description": "Test",
                "amount": 10.0,
                "expense_account_id": self.env["account.account"]
                .search(
                    [
                        ("company_ids", "in", self.env.company.id),
                        ("account_type", "in", ("expense", "expense_other")),
                    ],
                    limit=1,
                )
                .id,
            }
        )
        partner = wizard._avea_resolve_partner()
        self.assertEqual(partner.name, "Expense Wizard Supplier")
        self.assertGreaterEqual(partner.supplier_rank, 1)
        self.assertFalse(wizard.add_new_supplier)

    def test_resolve_partner_requires_name_when_adding(self):
        wizard = self.env["avea.operational.expense.wizard"].create(
            {
                "add_new_supplier": True,
                "description": "Test",
                "amount": 10.0,
                "expense_account_id": self.env["account.account"]
                .search(
                    [
                        ("company_ids", "in", self.env.company.id),
                        ("account_type", "in", ("expense", "expense_other")),
                    ],
                    limit=1,
                )
                .id,
            }
        )
        with self.assertRaises(ValidationError):
            wizard._avea_resolve_partner()
