# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon

from odoo.addons.avea_till.models.operations.withdraw_cash_wizard import (
    OWNER_DRAWING_ACCOUNT_CODE,
)


@tagged("post_install", "-at_install", "avea_till")
class TestAveaBusinessTransactions(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.config.write({"payment_method_ids": [(6, 0, cls.cash_pm1.ids)]})
        cls.Transaction = cls.env["avea.business.transaction"]
        cls.product = cls.create_product(
            "Transactions Product", cls.categ_basic, 100.0, 40.0
        )
        cls.drawings_account = cls.env["account.account"].search(
            [("code", "=", OWNER_DRAWING_ACCOUNT_CODE), ("company_ids", "in", cls.company.id)],
            limit=1,
        )
        cls.cash_journal = cls.company._avea_expense_journals().filtered(
            lambda journal: journal.type == "cash"
        )[:1]

    def _create_paid_order(self, *, amount=100.0, uuid="business-tx-order"):
        session = self.open_new_session(0)
        order_data = self.create_ui_order_data(
            pos_order_lines_ui_args=[(self.product, amount / self.product.lst_price)],
            payments=[(self.cash_pm1, amount)],
            uuid=uuid,
        )
        sync_result = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(sync_result["pos.order"][0]["id"])
        self.assertIn(order.state, self.env["pos.session"]._avea_paid_order_states())
        return order

    def test_pos_sale_is_one_transaction_row(self):
        order = self._create_paid_order(amount=150.0, uuid="business-tx-pos-sale")
        rows = self.Transaction.search(
            [("res_model", "=", "pos.order"), ("res_id", "=", order.id)]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.transaction_type, "pos_sale")
        self.assertAlmostEqual(rows.amount, 150.0, places=2)
        self.assertEqual(rows.payment_method_id, self.cash_pm1)

    def test_pos_sale_not_duplicated_by_payment_rows(self):
        order = self._create_paid_order(uuid="business-tx-no-dup")
        payment = order.payment_ids.filtered(lambda line: not line.is_change)[:1]
        self.assertTrue(payment)
        payment_rows = self.Transaction.search(
            [("res_model", "=", "pos.payment"), ("res_id", "=", payment.id)]
        )
        self.assertFalse(payment_rows)

    def test_search_by_order_reference(self):
        order = self._create_paid_order(uuid="business-tx-search")
        reference = order._avea_till_display_reference()
        matches = self.Transaction.search(
            [("search_text", "ilike", (reference or order.name).lower())]
        )
        self.assertTrue(matches)
        self.assertTrue(
            any(row.res_model == "pos.order" for row in matches),
            "Expected POS order in search results",
        )

    def test_open_source_record_opens_pos_order(self):
        order = self._create_paid_order(uuid="business-tx-open")
        tx = self.Transaction.search(
            [("res_model", "=", "pos.order"), ("res_id", "=", order.id)],
            limit=1,
        )
        action = tx.action_open_source_record()
        self.assertEqual(action["res_model"], "pos.order")
        self.assertEqual(action["res_id"], order.id)
        self.assertTrue(action.get("views"))

    def test_cash_withdrawal_appears_once(self):
        if not self.cash_journal or not self.drawings_account:
            self.skipTest("Cash journal or drawings account not configured")
        wizard = self.env["avea.withdraw.cash.wizard"].create(
            {
                "cash_journal_id": self.cash_journal.id,
                "withdrawal_purpose": "owner_drawing",
                "amount": 50.0,
            }
        )
        wizard.action_withdraw_cash()
        tx = self.Transaction.search(
            [("transaction_type", "=", "cash_withdrawal")],
            order="id desc",
            limit=1,
        )
        self.assertTrue(tx)
        self.assertAlmostEqual(tx.amount, 50.0, places=2)
        self.assertEqual(tx.res_model, "account.bank.statement.line")
