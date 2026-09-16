# -*- coding: utf-8 -*-
from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaCashUpPaymentReconciliation(TestPoSCommon):
    """Cash Up payment-method counting, variance, and receipt payload."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.CashUp = cls.env["avea.cash.up"]
        cls.company = cls.env.company
        cls.product = cls.create_product(
            "Cash Up Product", cls.categ_basic, 100.0, 50.0
        )
        cls.card_pm = cls.bank_pm1
        cls.eft_pm = cls.env["pos.payment.method"].create(
            {
                "name": "EFT Transfer",
                "type": "bank",
                "journal_id": cls.bank_pm1.journal_id.id,
                "company_id": cls.company.id,
            }
        )
        cls.config.write({"avea_credit_enabled": True})
        company = cls.company.sudo()
        company._avea_credit_setup_all_companies()
        cls.store_credit_pm = company._avea_credit_ensure_store_credit_payment_method(
            company._avea_credit_ensure_store_credit_journal(),
            company._avea_credit_ref("liability_account"),
        )
        cls.config.write(
            {
                "payment_method_ids": [
                    Command.link(cls.cash_pm1.id),
                    Command.link(cls.card_pm.id),
                    Command.link(cls.eft_pm.id),
                    Command.link(cls.store_credit_pm.id),
                ]
            }
        )
        cls._setup_cash_safe_journal()

    @classmethod
    def _setup_cash_safe_journal(cls):
        safe_journal = cls.env["account.journal"].search(
            [
                ("company_id", "=", cls.company.id),
                ("type", "=", "cash"),
                ("name", "ilike", "Cash Up Safe Test"),
            ],
            limit=1,
        )
        if not safe_journal:
            safe_journal = cls.env["account.journal"].create(
                {
                    "name": "Cash Up Safe Test",
                    "type": "cash",
                    "company_id": cls.company.id,
                    "code": "CUSF",
                }
            )
        cls.company.sudo().write({"avea_cash_safe_journal_id": safe_journal.id})

    def _open_session(self, opening_cash=0.0):
        return self.open_new_session(opening_cash)

    def _sync_order(self, session, *, lines, payments=None, uuid="cash-up-order"):
        total = sum(qty * product.lst_price for product, qty in lines)
        if payments is None:
            payments = [(self.cash_pm1, total)]
        order_data = self.create_ui_order_data(
            pos_order_lines_ui_args=lines,
            payments=payments,
            uuid=uuid,
        )
        sync = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(sync["pos.order"][0]["id"])
        self.assertEqual(order.state, "paid")
        return order

    def _reconciliation(self, session, counted_cash=None, counted_payments=None):
        if counted_cash is None:
            counted_cash = session.cash_register_balance_end
        return self.CashUp._avea_payment_reconciliation(
            session,
            counted_cash,
            counted_payments,
        )

    def _receipt(self, session, amounts, reconciliation, **kwargs):
        return self.CashUp._avea_receipt_payload(
            session,
            amounts,
            "Test Cashier",
            reconciliation,
            **kwargs,
        )

    def _create_stored_cash_up(self, session, amounts, reconciliation, **kwargs):
        has_variance = self.CashUp._avea_has_payment_variance(
            reconciliation,
            session.currency_id,
            cash_difference=amounts["difference"],
        )
        return self.CashUp.with_context(avea_cash_up_setup=True).create(
            {
                "name": session.name,
                "session_id": session.id,
                "user_id": self.env.user.id,
                "cashier_name": kwargs.get("cashier_name", "Test Cashier"),
                "cash_up_date": fields.Datetime.now(),
                "opening_cash": amounts["opening"],
                "expected_cash": amounts["expected"],
                "counted_cash": amounts["counted"],
                "difference": amounts["difference"],
                "cash_to_bag": amounts["cash_to_bag"],
                "remaining_cash": amounts["remaining"],
                "variance_reason": kwargs.get("variance_reason") or False,
                "transaction_count": kwargs.get("transaction_count", 0),
                "has_variance": has_variance,
                "total_payments_expected": reconciliation["total_expected"],
                "total_payments_counted": reconciliation["total_counted"],
                "total_payments_difference": reconciliation["total_difference"],
                "payment_line_ids": [
                    (
                        0,
                        0,
                        {
                            "payment_kind": line["kind"],
                            "sequence": line["sequence"],
                            "expected": line["expected"],
                            "counted": line["counted"],
                            "difference": line["difference"],
                        },
                    )
                    for line in reconciliation["lines"]
                ],
                "state": "confirmed",
            }
        )

    def test_expected_cash_card_eft_store_credit_and_other(self):
        session = self._open_session(100.0)
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.cash_pm1, self.product.lst_price)],
            uuid="cash-up-cash",
        )
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.card_pm, self.product.lst_price)],
            uuid="cash-up-card",
        )
        eft_amount = self.product.lst_price / 2
        self._sync_order(
            session,
            lines=[(self.product, 0.5)],
            payments=[(self.eft_pm, eft_amount)],
            uuid="cash-up-eft",
        )
        expected = session.get_avea_payment_reconciliation_expected()
        kinds = {line["kind"]: line["expected"] for line in expected["lines"]}
        self.assertEqual(
            expected["total_expected"],
            self.product.lst_price * 2 + eft_amount,
        )
        self.assertEqual(kinds["card"], self.product.lst_price)
        self.assertEqual(kinds["eft"], eft_amount)
        self.assertEqual(kinds["store_credit"], 0.0)
        self.assertEqual(kinds["cash"], self.product.lst_price)
        self.assertEqual(expected["cash_register_expected"], 100.0 + self.product.lst_price)
        self.assertEqual(expected["transaction_count"], 3)

    def test_refund_reduces_payment_expected(self):
        session = self._open_session(0.0)
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.card_pm, 100.0)],
            uuid="cash-up-sale",
        )
        self._sync_order(
            session,
            lines=[(self.product, -1)],
            payments=[(self.card_pm, -100.0)],
            uuid="cash-up-refund",
        )
        expected = session.get_avea_payment_reconciliation_expected()
        card = next(line for line in expected["lines"] if line["kind"] == "card")
        self.assertEqual(card["expected"], 0.0)
        self.assertEqual(expected["total_expected"], 0.0)

    def test_zero_variance_does_not_require_reason(self):
        session = self._open_session(0.0)
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.cash_pm1, 100.0)],
            uuid="cash-up-zero",
        )
        session.invalidate_recordset(["cash_register_balance_end"])
        counted = session.cash_register_balance_end
        reconciliation = self._reconciliation(session, counted)
        self.CashUp._avea_validate_variance_reason(
            reconciliation,
            False,
            session.currency_id,
            cash_difference=0.0,
        )

    def test_non_zero_card_variance_requires_reason(self):
        session = self._open_session(0.0)
        self._sync_order(
            session,
            lines=[(self.product, 2)],
            payments=[(self.card_pm, 200.0)],
            uuid="cash-up-card-variance",
        )
        reconciliation = self._reconciliation(
            session,
            session.cash_register_balance_end,
            {"card": 150.0},
        )
        card = next(line for line in reconciliation["lines"] if line["kind"] == "card")
        self.assertEqual(card["difference"], -50.0)
        with self.assertRaises(UserError):
            self.CashUp._avea_validate_variance_reason(
                reconciliation,
                "",
                session.currency_id,
                cash_difference=0.0,
            )
        self.CashUp._avea_validate_variance_reason(
            reconciliation,
            "Card terminal batch mismatch",
            session.currency_id,
            cash_difference=0.0,
        )

    def test_opposing_cash_and_card_variances(self):
        session = self._open_session(0.0)
        self._sync_order(
            session,
            lines=[(self.product, 15)],
            payments=[(self.cash_pm1, 1500.0)],
            uuid="cash-up-misclass-cash",
        )
        self._sync_order(
            session,
            lines=[(self.product, 15)],
            payments=[(self.card_pm, 1500.0)],
            uuid="cash-up-misclass-card",
        )
        reconciliation = self._reconciliation(
            session,
            counted_cash=1000.0,
            counted_payments={"card": 2000.0},
        )
        cash = next(line for line in reconciliation["lines"] if line["kind"] == "cash")
        card = next(line for line in reconciliation["lines"] if line["kind"] == "card")
        self.assertEqual(cash["expected"], 1500.0)
        self.assertEqual(cash["counted"], 1000.0)
        self.assertEqual(cash["difference"], -500.0)
        self.assertEqual(card["difference"], 500.0)
        self.assertEqual(reconciliation["total_difference"], 500.0)

    def test_total_payments_counted_uses_net_cash(self):
        session = self._open_session(200.0)
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.cash_pm1, 100.0)],
            uuid="cash-up-total",
        )
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.card_pm, 100.0)],
            uuid="cash-up-total-card",
        )
        session.invalidate_recordset(["cash_register_balance_end"])
        counted_cash = session.cash_register_balance_end
        reconciliation = self._reconciliation(
            session,
            counted_cash,
            {"card": 100.0},
        )
        self.assertEqual(reconciliation["total_expected"], 200.0)
        self.assertEqual(reconciliation["total_counted"], 200.0)
        self.assertEqual(reconciliation["total_difference"], 0.0)

    def test_receipt_contains_payment_summary_and_variance_reason(self):
        session = self._open_session(0.0)
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.card_pm, 100.0)],
            uuid="cash-up-receipt",
        )
        amounts = self.CashUp._avea_amounts(session, session.cash_register_balance_end)
        reconciliation = self._reconciliation(
            session,
            session.cash_register_balance_end,
            {"card": 80.0},
        )
        reconciliation["variance_reason"] = "Card batch short"
        receipt = self._receipt(session, amounts, reconciliation)
        kinds = {line["kind"] for line in receipt["payment_lines"]}
        self.assertIn("cash", kinds)
        self.assertIn("card", kinds)
        self.assertIn("total_payments_expected", receipt)
        self.assertIn("total_variance", receipt)
        self.assertIn("payment_summary", receipt)
        self.assertEqual(len(receipt["payment_lines"]), 5)
        self.assertTrue(receipt["has_variance"])
        self.assertEqual(receipt["variance_reason"], "Card batch short")
        card_line = next(
            line for line in receipt["payment_lines"] if line["kind"] == "card"
        )
        self.assertEqual(card_line["difference_amount"], -20.0)

    def test_receipt_slip_print_fields(self):
        product = self.create_product(
            "Receipt Slip Product", self.categ_basic, 926.0, 100.0
        )
        session = self._open_session(1000.0)
        self._sync_order(
            session,
            lines=[(product, 1)],
            payments=[(self.cash_pm1, 926.0)],
            uuid="cash-up-receipt-slip",
        )
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.card_pm, self.product.lst_price)],
            uuid="cash-up-receipt-slip-card",
        )
        amounts = self.CashUp._avea_amounts(session, 1926.0)
        reconciliation = self._reconciliation(session, 1926.0)
        receipt = self._receipt(session, amounts, reconciliation)
        kinds = [line["kind"] for line in receipt["payment_lines"]]
        self.assertEqual(
            kinds,
            ["cash", "card", "eft", "store_credit", "other"],
        )
        cash_line = receipt["payment_lines"][0]
        self.assertEqual(cash_line["expected_amount"], 1926.0)
        self.assertEqual(cash_line["counted_amount"], 1926.0)
        self.assertEqual(
            receipt["total_payments_expected_amount"],
            926.0 + self.product.lst_price,
        )
        self.assertEqual(receipt["opening_cash_amount"], 1000.0)
        self.assertEqual(receipt["cash_to_bag_amount"], 926.0)
        self.assertEqual(receipt["remaining_cash_amount"], 1000.0)
        self.assertEqual(receipt["transaction_count"], 2)
        self.assertFalse(receipt["has_variance"])

    def test_receipt_slip_variance_payload(self):
        session = self._open_session(1000.0)
        product = self.create_product(
            "Variance Slip Product", self.categ_basic, 926.0, 100.0
        )
        self._sync_order(
            session,
            lines=[(product, 1)],
            payments=[(self.cash_pm1, 926.0)],
            uuid="cash-up-receipt-variance",
        )
        amounts = self.CashUp._avea_amounts(session, 1900.0)
        reconciliation = self._reconciliation(session, 1900.0)
        reconciliation["variance_reason"] = "Short cash"
        receipt = self._receipt(session, amounts, reconciliation)
        cash_line = next(
            line for line in receipt["payment_lines"] if line["kind"] == "cash"
        )
        self.assertTrue(receipt["has_variance"])
        self.assertEqual(receipt["variance_reason"], "Short cash")
        self.assertEqual(cash_line["difference_amount"], -26.0)
        self.assertEqual(amounts["cash_to_bag"], 900.0)

    def test_preview_payload_includes_payment_lines(self):
        session = self._open_session(0.0)
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.cash_pm1, 100.0)],
            uuid="cash-up-preview",
        )
        preview = self.CashUp.with_user(self.env.user).pos_get_cash_up_preview(
            session.id
        )
        kinds = {line["kind"] for line in preview["payment_lines"]}
        self.assertIn("cash", kinds)
        self.assertIn("total_payments_expected", preview)
        self.assertEqual(preview["transaction_count"], 1)
        self.assertEqual(preview["difference_amount"], 0.0)

    def test_payment_correction_updates_expected_totals(self):
        session = self._open_session(0.0)
        order = self._sync_order(
            session,
            lines=[(self.product, 5)],
            payments=[(self.cash_pm1, 500.0)],
            uuid="cash-up-correction",
        )
        self.env.user.write(
            {
                "group_ids": [
                    Command.link(
                        self.env.ref("avea_till.group_avea_correct_payment").id
                    )
                ]
            }
        )
        order.avea_correct_payment_method(self.card_pm.id, "Wrong tender selected")
        expected = session.get_avea_payment_reconciliation_expected()
        kinds = {line["kind"]: line["expected"] for line in expected["lines"]}
        self.assertEqual(kinds["cash"], 0.0)
        self.assertEqual(kinds["card"], 500.0)

    def test_preview_transaction_count_matches_paid_orders(self):
        session = self._open_session(1000.0)
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.cash_pm1, self.product.lst_price)],
            uuid="cash-up-tx-count-1",
        )
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.card_pm, self.product.lst_price)],
            uuid="cash-up-tx-count-2",
        )
        preview = self.CashUp.with_user(self.env.user).pos_get_cash_up_preview(
            session.id
        )
        self.assertEqual(session.get_avea_transaction_count(), 2)
        self.assertEqual(preview["transaction_count"], 2)

    def test_payment_line_cash_expected_excludes_opening(self):
        product = self.create_product("Line Cash Product", self.categ_basic, 926.0, 100.0)
        session = self._open_session(1000.0)
        self._sync_order(
            session,
            lines=[(product, 1)],
            payments=[(self.cash_pm1, 926.0)],
            uuid="cash-up-line-cash",
        )
        preview = self.CashUp.with_user(self.env.user).pos_get_cash_up_preview(
            session.id
        )
        cash_line = next(
            line for line in preview["payment_lines"] if line["kind"] == "cash"
        )
        self.assertEqual(cash_line["expected_amount"], 1926.0)
        self.assertEqual(cash_line["counted_amount"], 1926.0)
        self.assertEqual(preview["expected_cash_amount"], 1926.0)
        self.assertEqual(preview["cash_payments_expected_amount"], 926.0)

    def test_cash_to_safe_excludes_opening_float(self):
        product = self.create_product("Safe Cash Product", self.categ_basic, 926.0, 100.0)
        session = self._open_session(1000.0)
        self._sync_order(
            session,
            lines=[(product, 1)],
            payments=[(self.cash_pm1, 926.0)],
            uuid="cash-up-safe",
        )
        amounts = self.CashUp._avea_amounts(session, 1926.0)
        self.assertEqual(amounts["cash_to_bag"], 926.0)
        self.assertEqual(amounts["remaining"], 1000.0)

    def test_payment_summary_cash_excludes_opening(self):
        product = self.create_product("Summary Cash Product", self.categ_basic, 926.0, 100.0)
        session = self._open_session(1000.0)
        self._sync_order(
            session,
            lines=[(product, 1)],
            payments=[(self.cash_pm1, 926.0)],
            uuid="cash-up-summary-cash",
        )
        amounts = self.CashUp._avea_amounts(session, session.cash_register_balance_end)
        reconciliation = self._reconciliation(session, session.cash_register_balance_end)
        receipt = self._receipt(session, amounts, reconciliation)
        cash_summary = next(
            item for item in receipt["payment_summary"] if item["kind"] == "cash"
        )
        self.assertEqual(cash_summary["amount_value"], 926.0)
        self.assertEqual(amounts["expected"], 1926.0)

    def test_opening_cash_excluded_from_payment_cash_expected(self):
        session = self._open_session(1000.0)
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.cash_pm1, self.product.lst_price)],
            uuid="cash-up-opening-split",
        )
        expected = session.get_avea_payment_reconciliation_expected()
        kinds = {line["kind"]: line["expected"] for line in expected["lines"]}
        self.assertEqual(kinds["cash"], self.product.lst_price)
        self.assertEqual(expected["opening_cash"], 1000.0)
        self.assertEqual(
            expected["cash_register_expected"],
            1000.0 + self.product.lst_price,
        )
        self.assertEqual(expected["total_expected"], self.product.lst_price)

    def test_opening_cash_balanced_does_not_require_variance_reason(self):
        product = self.create_product("Opening Cash Product", self.categ_basic, 926.0, 100.0)
        session = self._open_session(1000.0)
        self._sync_order(
            session,
            lines=[(product, 1)],
            payments=[(self.cash_pm1, 926.0)],
            uuid="cash-up-opening-balanced",
        )
        session.invalidate_recordset(["cash_register_balance_end"])
        counted_cash = session.cash_register_balance_end
        amounts = self.CashUp._avea_amounts(session, counted_cash)
        reconciliation = self._reconciliation(session, counted_cash)
        cash = next(line for line in reconciliation["lines"] if line["kind"] == "cash")
        self.assertEqual(cash["expected"], 1926.0)
        self.assertEqual(cash["counted"], 1926.0)
        self.assertEqual(cash["difference"], 0.0)
        self.assertEqual(reconciliation["total_difference"], 0.0)
        self.assertEqual(amounts["difference"], 0.0)
        self.CashUp._avea_validate_variance_reason(
            reconciliation,
            False,
            session.currency_id,
            cash_difference=amounts["difference"],
        )

    def test_payment_reconciliation_cash_row_reconciles_drawer(self):
        product = self.create_product(
            "Payment Cash Product", self.categ_basic, 926.0, 100.0
        )
        session = self._open_session(1000.0)
        self._sync_order(
            session,
            lines=[(product, 1)],
            payments=[(self.cash_pm1, 926.0)],
            uuid="cash-up-payment-cash-counted",
        )
        physical_counted = 1926.0
        amounts = self.CashUp._avea_amounts(session, physical_counted)
        reconciliation = self._reconciliation(session, physical_counted)
        cash = next(line for line in reconciliation["lines"] if line["kind"] == "cash")
        self.assertEqual(amounts["counted"], physical_counted)
        self.assertEqual(amounts["expected"], physical_counted)
        self.assertEqual(amounts["difference"], 0.0)
        self.assertEqual(amounts["cash_to_bag"], 926.0)
        self.assertEqual(cash["expected"], 1926.0)
        self.assertEqual(cash["counted"], 1926.0)
        self.assertEqual(cash["difference"], 0.0)
        self.assertEqual(reconciliation["total_counted"], 926.0)

    def test_receipt_reprint_from_stored_record(self):
        product = self.create_product(
            "Reprint Product", self.categ_basic, 926.0, 100.0
        )
        session = self._open_session(1000.0)
        self._sync_order(
            session,
            lines=[(product, 1)],
            payments=[(self.cash_pm1, 926.0)],
            uuid="cash-up-reprint-stored",
        )
        amounts = self.CashUp._avea_amounts(session, 1926.0)
        reconciliation = self._reconciliation(session, 1926.0)
        cash_up = self._create_stored_cash_up(
            session,
            amounts,
            reconciliation,
            transaction_count=1,
        )
        payload = cash_up.get_receipt_payload()
        self.assertFalse(payload["has_variance"])
        self.assertEqual(payload["cash_to_bag_amount"], 926.0)
        self.assertEqual(payload["transaction_count"], 1)
        self.assertEqual(len(payload["active_payment_lines"]), 1)
        action = cash_up.action_reprint_receipt()
        self.assertEqual(action.get("type"), "ir.actions.act_url")
        self.assertEqual(action.get("target"), "new")
        self.assertIn(str(cash_up.id), action.get("url", ""))
        report = self.env.ref("avea_till.action_report_avea_cash_up_receipt")
        self.assertEqual(report.model, "avea.cash.up")
        html, _report_type = self.env["ir.actions.report"]._render_qweb_html(
            "avea_till.report_avea_cash_up_receipt", cash_up.ids
        )
        self.assertIn(b"CASH UP", html)
        self.assertIn(b"All amounts reconciled", html)

    def test_receipt_reprint_variance_from_stored_record(self):
        product = self.create_product(
            "Reprint Variance Product", self.categ_basic, 926.0, 100.0
        )
        session = self._open_session(1000.0)
        self._sync_order(
            session,
            lines=[(product, 1)],
            payments=[(self.cash_pm1, 926.0)],
            uuid="cash-up-reprint-variance",
        )
        amounts = self.CashUp._avea_amounts(session, 1900.0)
        reconciliation = self._reconciliation(session, 1900.0)
        cash_up = self._create_stored_cash_up(
            session,
            amounts,
            reconciliation,
            variance_reason="Short cash",
            transaction_count=1,
        )
        payload = cash_up.get_receipt_payload()
        self.assertTrue(payload["has_variance"])
        self.assertEqual(payload["variance_reason"], "Short cash")
        self.assertEqual(payload["difference_amount"], -26.0)

    def test_preview_transaction_count_authoritative_not_zero(self):
        session = self._open_session(1000.0)
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.cash_pm1, self.product.lst_price)],
            uuid="cash-up-tx-authoritative-1",
        )
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.card_pm, self.product.lst_price)],
            uuid="cash-up-tx-authoritative-2",
        )
        self._sync_order(
            session,
            lines=[(self.product, 1)],
            payments=[(self.cash_pm1, self.product.lst_price)],
            uuid="cash-up-tx-authoritative-3",
        )
        preview = session.get_avea_cash_up_preview()
        self.assertEqual(session.get_avea_transaction_count(), 3)
        self.assertEqual(preview["transaction_count"], 3)
        self.assertIsInstance(preview["transaction_count"], int)
