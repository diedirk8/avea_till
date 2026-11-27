# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_till")
class TestAveaMoneyTransfer(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        journals = cls.env.company._avea_transfer_journals()
        cls.safe = journals.filtered(
            lambda journal: "safe" in (journal.name or "").lower()
        )[:1] or journals.filtered(lambda journal: journal.type == "cash")[:1]
        cls.petty = journals.filtered(
            lambda journal: "petty" in (journal.name or "").lower()
        )[:1]
        if not cls.petty:
            cls.petty = (journals - cls.safe).filtered(
                lambda journal: journal.type == "cash"
            )[:1]
        if not cls.petty:
            cls.petty = (journals - cls.safe)[:1]

    def test_account_balances_view_is_not_odoo_journal_items(self):
        if not self.safe:
            return
        wizard = self.env["avea.account.balance.wizard"].create({})
        wizard._avea_populate_lines()
        line = wizard.line_ids.filtered(lambda item: item.journal_id == self.safe)[:1]
        self.assertTrue(line, "Cash Safe should appear on Account Balances")
        action = line.action_open_transactions()
        self.assertEqual(action["res_model"], "account.move.line")
        self.assertNotIn("journal_type", action.get("context") or {})
        self.assertEqual(action["context"]["avea_money_journal_id"], self.safe.id)
        self.assertIn(("account_id", "=", self.safe.default_account_id.id), action["domain"])
        views = [view[0] for view in action["views"]]
        self.assertIn(
            self.env.ref("avea_till.view_avea_account_activity_list").id, views
        )

    def test_transfer_from_cash_safe_shows_on_petty_cash(self):
        if not self.safe or not self.petty or self.safe == self.petty:
            return
        reference = "Zzqx Safe To Petty"
        wizard = self.env["avea.money.transfer.wizard"].create(
            {
                "from_journal_id": self.safe.id,
                "to_journal_id": self.petty.id,
                "amount": 37.5,
                "reference": reference,
            }
        )
        action = wizard.action_confirm_transfer()
        self.assertEqual(action["type"], "ir.actions.client")
        next_action = action["params"]["next"]
        self.assertEqual(next_action["res_model"], "account.move.line")
        self.assertEqual(
            next_action["context"]["avea_money_journal_id"], self.petty.id
        )
        petty_lines = self.env["account.move.line"].search(
            [
                ("account_id", "=", self.petty.default_account_id.id),
                ("parent_state", "=", "posted"),
                ("name", "=", reference),
            ]
        )
        self.assertTrue(petty_lines)
        self.assertAlmostEqual(sum(petty_lines.mapped("debit")), 37.5, places=2)
        safe_lines = self.env["account.move.line"].search(
            [
                ("account_id", "=", self.safe.default_account_id.id),
                ("parent_state", "=", "posted"),
                ("name", "=", reference),
            ]
        )
        self.assertTrue(safe_lines)
        self.assertAlmostEqual(sum(safe_lines.mapped("credit")), 37.5, places=2)
        viewed = self.env["account.move.line"].search(next_action["domain"])
        self.assertTrue(set(petty_lines.ids) <= set(viewed.ids))

    def test_transfer_from_balances_row_prefills_from_account(self):
        if not self.safe:
            return
        wizard = self.env["avea.account.balance.wizard"].create({})
        wizard._avea_populate_lines()
        line = wizard.line_ids.filtered(lambda item: item.journal_id == self.safe)[:1]
        self.assertTrue(line)
        action = line.action_open_transfer()
        self.assertEqual(action["res_model"], "avea.money.transfer.wizard")
        self.assertEqual(action["context"]["default_from_journal_id"], self.safe.id)
        self.assertNotIn("journal_type", action.get("context") or {})
