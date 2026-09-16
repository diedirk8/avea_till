# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.avea_till.models.operations.withdraw_cash_wizard import (
    OWNER_DRAWING_ACCOUNT_CODE,
    SALARY_WAGES_ACCOUNT_CODE,
)


@tagged("post_install", "-at_install", "avea_till")
class TestAveaWithdrawCash(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Wizard = cls.env["avea.withdraw.cash.wizard"]
        cls.salary_account = cls._require_account(
            SALARY_WAGES_ACCOUNT_CODE, "Distribution Salaries and Wages"
        )
        cls.drawings_account = cls._require_account(
            OWNER_DRAWING_ACCOUNT_CODE, "Drawings"
        )
        cls.other_expense_account = cls.env["account.account"].search(
            [
                ("company_ids", "in", cls.company.id),
                ("account_type", "in", ("expense", "expense_other", "expense_direct_cost")),
                ("id", "!=", cls.salary_account.id),
            ],
            limit=1,
        )
        cls.cash_journal = cls._require_cash_journal()

    @classmethod
    def _require_account(cls, code, label):
        account = cls.env["account.account"].search(
            [("code", "=", code), ("company_ids", "in", cls.company.id)],
            limit=1,
        )
        if not account:
            raise AssertionError(f"Missing test account {code} ({label})")
        return account

    @classmethod
    def _require_cash_journal(cls):
        journals = cls.company._avea_expense_journals()
        journal = journals.filtered(lambda rec: rec.type == "cash")[:1]
        if not journal:
            raise AssertionError("No cash journal configured for Avea expense accounts")
        if not journal.default_account_id:
            raise AssertionError("Cash journal has no default account")
        return journal

    def _create_wizard(self, **values):
        defaults = {
            "cash_journal_id": self.cash_journal.id,
            "amount": 100.0,
            "withdrawal_date": "2026-09-15",
        }
        defaults.update(values)
        return self.Wizard.create(defaults)

    def test_owner_drawing_posts_to_drawings_account(self):
        cash_account = self.cash_journal.default_account_id
        before = cash_account.current_balance
        wizard = self._create_wizard(withdrawal_purpose="owner_drawing")
        wizard.action_withdraw_cash()
        cash_account.invalidate_recordset(["current_balance"])
        self.assertAlmostEqual(cash_account.current_balance, before - 100.0, places=2)
        line = self.env["account.bank.statement.line"].search(
            [
                ("journal_id", "=", self.cash_journal.id),
                ("payment_ref", "ilike", "Owner Drawing"),
            ],
            order="id desc",
            limit=1,
        )
        self.assertTrue(line)
        counterpart = line.move_id.line_ids.filtered(
            lambda move_line: move_line.account_id == self.drawings_account
        )
        self.assertTrue(counterpart)

    def test_salary_wages_posts_to_salary_account(self):
        wizard = self._create_wizard(
            withdrawal_purpose="salary_wages",
            reference_name="Weekly wages",
        )
        wizard.action_withdraw_cash()
        line = self.env["account.bank.statement.line"].search(
            [
                ("journal_id", "=", self.cash_journal.id),
                ("payment_ref", "=", "Weekly wages"),
            ],
            limit=1,
        )
        self.assertTrue(line)
        counterpart = line.move_id.line_ids.filtered(
            lambda move_line: move_line.account_id == self.salary_account
        )
        self.assertTrue(counterpart)

    def test_staff_advance_posts_to_salary_account_with_reference(self):
        wizard = self._create_wizard(
            withdrawal_purpose="staff_advance",
            reference_name="John - salary advance",
        )
        wizard.action_withdraw_cash()
        line = self.env["account.bank.statement.line"].search(
            [
                ("journal_id", "=", self.cash_journal.id),
                ("payment_ref", "=", "John - salary advance"),
            ],
            limit=1,
        )
        self.assertTrue(line)
        self.assertEqual(line.partner_id, self.company.partner_id)
        counterpart = line.move_id.line_ids.filtered(
            lambda move_line: move_line.account_id == self.salary_account
        )
        self.assertTrue(counterpart)
        self.assertIn("John - salary advance", line.move_id.narration)

    def test_other_expense_uses_selected_account(self):
        self.assertTrue(self.other_expense_account)
        wizard = self._create_wizard(
            withdrawal_purpose="other_expense",
            expense_account_id=self.other_expense_account.id,
            reference_name="Petrol",
        )
        wizard.action_withdraw_cash()
        line = self.env["account.bank.statement.line"].search(
            [("journal_id", "=", self.cash_journal.id), ("payment_ref", "=", "Petrol")],
            limit=1,
        )
        self.assertTrue(line)
        counterpart = line.move_id.line_ids.filtered(
            lambda move_line: move_line.account_id == self.other_expense_account
        )
        self.assertTrue(counterpart)

    def test_amount_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self._create_wizard(amount=0.0)

    def test_withdrawal_appears_once_in_business_transactions(self):
        wizard = self._create_wizard(
            withdrawal_purpose="owner_drawing",
            reference_name="Safe withdrawal test",
            amount=75.0,
        )
        wizard.action_withdraw_cash()
        statement_line = self.env["account.bank.statement.line"].search(
            [
                ("journal_id", "=", self.cash_journal.id),
                ("payment_ref", "=", "Safe withdrawal test"),
            ],
            limit=1,
        )
        self.assertTrue(statement_line)
        self.env.flush_all()
        rows = self.env["avea.business.transaction"].search(
            [
                ("res_model", "=", "account.bank.statement.line"),
                ("res_id", "=", statement_line.id),
            ]
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.transaction_type, "cash_withdrawal")
        self.assertAlmostEqual(row.amount, 75.0, places=2)
        self.assertEqual(row.reference, "Safe withdrawal test")
        self.assertLess(
            abs((row.transaction_datetime - statement_line.create_date).total_seconds()),
            1,
        )

    def test_all_posted_withdrawals_appear_once_in_business_transactions(self):
        withdrawal_lines = self.env["account.bank.statement.line"].sudo().search(
            [
                ("journal_id", "in", self.company._avea_expense_journals().ids),
                ("move_id.narration", "ilike", "Recorded from Avea. Withdrawn"),
            ]
        )
        self.assertTrue(withdrawal_lines)
        for line in withdrawal_lines:
            if line.move_id.state != "posted":
                continue
            rows = self.env["avea.business.transaction"].search(
                [
                    ("res_model", "=", "account.bank.statement.line"),
                    ("res_id", "=", line.id),
                ]
            )
            self.assertEqual(
                len(rows),
                1,
                f"Expected one business transaction for withdrawal line {line.id}",
            )
            self.assertEqual(rows.transaction_type, "cash_withdrawal")
