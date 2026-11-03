# -*- coding: utf-8 -*-
import ast

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.avea_till.models.operations.account_account import AVEA_ACCOUNT_TYPES


@tagged("post_install", "-at_install", "avea_account_manager")
class TestAveaAccountManager(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Account = cls.env["account.account"].with_company(cls.company)
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Avea Account Manager",
                "login": "avea_account_mgr@dev.local",
                "email": "avea_account_mgr@dev.local",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [
                    Command.set([cls.env.ref("avea_till.group_avea_manager").id])
                ],
            }
        )
        cls.cashier = cls.env["res.users"].create(
            {
                "name": "Avea Account Cashier",
                "login": "avea_account_cash@dev.local",
                "email": "avea_account_cash@dev.local",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [
                    Command.set([cls.env.ref("avea_till.group_avea_cashier").id])
                ],
            }
        )

    def _workspace(self, user=None):
        env = self.env
        if user:
            env = env(user=user)
        return env["account.account"].with_company(self.company).with_context(
            avea_account_workspace=True
        )

    def _action_domain(self):
        action = self.env.ref("avea_till.action_avea_account_manager")
        raw = action.domain or "[]"
        return raw if isinstance(raw, list) else ast.literal_eval(raw)

    def _balancing_account(self):
        journals = self.company._avea_expense_journals()
        account = journals[:1].default_account_id
        if account:
            return account
        return self.Account.search(
            [
                ("company_ids", "in", self.company.id),
                ("account_type", "in", ("asset_cash", "asset_current")),
            ],
            limit=1,
        )

    def test_manager_list_is_income_and_expense_only(self):
        domain = self._action_domain()
        accounts = self.Account.search(domain)
        self.assertTrue(accounts)
        self.assertTrue(all(account.account_type in AVEA_ACCOUNT_TYPES for account in accounts))
        other = self.Account.search(
            [
                ("company_ids", "in", self.company.id),
                ("account_type", "not in", AVEA_ACCOUNT_TYPES),
            ],
            limit=1,
        )
        if other:
            self.assertNotIn(other, accounts)

    def test_manager_creates_expense_and_income_with_codes(self):
        Account = self._workspace(self.manager)
        expense = Account.create({"name": "Avea Test Electricity", "account_type": "expense"})
        income = Account.create({"name": "Avea Test Interest", "account_type": "income"})
        self.assertEqual(expense.account_type, "expense")
        self.assertEqual(expense.avea_kind, "expense")
        self.assertTrue(expense.code)
        self.assertEqual(income.account_type, "income")
        self.assertTrue(income.code)
        self.assertNotEqual(expense.code, income.code)
        domain = self._action_domain()
        listed = Account.search(domain)
        self.assertIn(expense, listed)
        self.assertIn(income, listed)
        expense_choices = self.env["account.account"].search(
            [
                ("active", "=", True),
                ("account_type", "in", ("expense", "expense_other", "expense_direct_cost")),
            ]
        )
        self.assertIn(expense, expense_choices)
        with self.assertRaises(UserError):
            Account.create({"name": "Not a bank", "account_type": "asset_cash"})

    def test_ytd_and_activity_for_posted_expense(self):
        Account = self._workspace(self.manager)
        expense = Account.create({"name": "Avea Test Rent", "account_type": "expense"})
        counterpart = self._balancing_account()
        self.assertTrue(counterpart, "Need a cash/bank account to post a test entry")
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "date": fields.Date.context_today(self.env.user),
                "journal_id": self.company._avea_expense_journals()[:1].id
                or self.env["account.journal"].search(
                    [("company_id", "=", self.company.id)], limit=1
                ).id,
                "line_ids": [
                    Command.create(
                        {
                            "account_id": expense.id,
                            "name": "Shop rent",
                            "debit": 250.0,
                            "credit": 0.0,
                        }
                    ),
                    Command.create(
                        {
                            "account_id": counterpart.id,
                            "name": "Shop rent",
                            "debit": 0.0,
                            "credit": 250.0,
                        }
                    ),
                ],
            }
        )
        move.action_post()
        expense.invalidate_recordset(
            ["avea_ytd_amount", "avea_entry_count", "avea_has_entries"]
        )
        self.assertAlmostEqual(expense.avea_ytd_amount, 250.0, places=2)
        self.assertEqual(expense.avea_entry_count, 1)
        self.assertTrue(expense.avea_has_entries)
        activity = expense.action_avea_view_activity()
        self.assertEqual(activity["res_model"], "account.move.line")
        self.assertIn(("account_id", "=", expense.id), activity["domain"])
        lines = self.env["account.move.line"].search(activity["domain"])
        rent_line = move.line_ids.filtered(lambda line: line.account_id == expense)
        self.assertIn(rent_line.id, lines.ids)
        self.assertAlmostEqual(rent_line.avea_signed_amount, 250.0, places=2)
        with self.assertRaises(UserError):
            expense.with_context(avea_account_workspace=True).write(
                {"account_type": "income"}
            )

    def test_cashier_cannot_create_workspace_account(self):
        with self.assertRaises(AccessError):
            self._workspace(self.cashier).create({"name": "Blocked expense"})

    def test_nav_includes_accounts(self):
        nav = self.manager._avea_nav_structure()
        money = next(section for section in nav["sections"] if section["id"] == "money")
        labels = [item["label"] for item in money["items"]]
        self.assertIn("Accounts", labels)
