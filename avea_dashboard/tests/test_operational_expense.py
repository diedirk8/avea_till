# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_till")
class TestAveaOperationalExpense(TransactionCase):
    def _expense_account_id(self):
        return (
            self.env["account.account"]
            .search(
                [
                    ("company_ids", "in", self.env.company.id),
                    ("account_type", "in", ("expense", "expense_other")),
                ],
                limit=1,
            )
            .id
        )

    def test_resolve_partner_requires_selection(self):
        wizard = self.env["avea.operational.expense.wizard"].create(
            {
                "description": "Test",
                "amount": 10.0,
                "expense_account_id": self._expense_account_id(),
            }
        )
        with self.assertRaises(UserError):
            wizard._avea_resolve_partner()

    def test_name_create_supplier_from_expense_context(self):
        Partner = self.env["res.partner"].with_context(
            avea_operational_expense_supplier=True
        )
        partner_id, display_name = Partner.name_create("Expense Wizard Supplier")
        partner = Partner.browse(partner_id)
        self.assertEqual(display_name, partner.display_name)
        self.assertEqual(partner.name, "Expense Wizard Supplier")
        self.assertGreaterEqual(partner.supplier_rank, 1)
