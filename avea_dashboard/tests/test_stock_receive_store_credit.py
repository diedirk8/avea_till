# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_till")
class TestAveaStockReceiveStoreCredit(TransactionCase):
    """Pay a vendor bill with Pets Empire store credit (animal trade)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company._avea_credit_ensure_accounting_setup()
        cls.currency = cls.company.currency_id
        cls.mixin = cls.env["avea.stock.mixin"]
        cls.Ledger = cls.env["avea.credit.ledger.entry"]
        cls.reason = cls.env.ref(
            "avea_till.credit_reason_animal_trade",
            raise_if_not_found=False,
        ) or cls.env["avea.credit.reason"].search(
            [("manual_issue", "=", True)], limit=1
        )
        if not cls.reason:
            raise AssertionError("Animal Trade store credit reason is required")
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Leada Pretorius",
                "customer_rank": 1,
                "supplier_rank": 1,
                "company_id": cls.company.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Cockatiel",
                "type": "consu",
                "is_storable": True,
                "list_price": 250.0,
                "standard_price": 150.0,
                "avea_cost_ex_tax": 150.0,
                "purchase_ok": True,
                "sale_ok": True,
                "company_id": cls.company.id,
                "supplier_taxes_id": [Command.clear()],
                "taxes_id": [Command.clear()],
            }
        )
        warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        if not warehouse:
            raise AssertionError("Warehouse required for Receive Stock tests")

    def _pay_journal(self):
        journals = self.company._avea_expense_journals()
        journal = journals.filtered(lambda rec: rec.type == "cash")[:1] or journals[:1]
        if journal:
            return journal
        journal = self.env["account.journal"].search(
            [
                ("type", "in", ("cash", "bank")),
                ("company_id", "=", self.company.id),
            ],
            limit=1,
        )
        if journal and journal not in self.company.avea_expense_journal_ids:
            self.company.write(
                {"avea_expense_journal_ids": [Command.link(journal.id)]}
            )
        return journal

    def _issue_credit(self, amount=595.0):
        entry = self.Ledger.create_issued_credit(
            partner=self.partner,
            amount=amount,
            reason=self.reason,
            notes="Invoice 77 store credit",
        )
        self.partner.invalidate_recordset(
            ["avea_credit_balance", "avea_credit_currency_id"]
        )
        return entry

    def _create_bill(self, amount=900.0, ref="77"):
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner.id,
                "invoice_date": "2026-11-12",
                "ref": ref,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "name": "Cockatiel",
                            "quantity": 1,
                            "price_unit": amount,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
            }
        )
        bill.action_post()
        return bill

    def test_already_issued_store_credit_settles_bill_without_granting_more(self):
        self._issue_credit(595.0)
        self.assertAlmostEqual(self.partner.avea_credit_balance, 595.0, places=2)
        bill = self._create_bill(900.0)
        expense = self.company.avea_credit_issuance_expense_account_id

        def _expense_net():
            lines = self.env["account.move.line"].search(
                [
                    ("account_id", "=", expense.id),
                    ("company_id", "=", self.company.id),
                    ("parent_state", "=", "posted"),
                ]
            )
            return sum(lines.mapped("debit")) - sum(lines.mapped("credit"))

        expense_before = _expense_net()

        applied = self.mixin._avea_apply_store_credit_to_vendor_bill(
            bill,
            self.partner,
            self.company,
            595.0,
            already_issued=True,
            pay_date="2026-11-12",
            payment_ref="77",
        )
        bill.invalidate_recordset(["amount_residual"])
        self.partner.invalidate_recordset(["avea_credit_balance"])

        self.assertAlmostEqual(applied, 595.0, places=2)
        self.assertAlmostEqual(bill.amount_residual, 305.0, places=2)
        self.assertAlmostEqual(self.partner.avea_credit_balance, 595.0, places=2)
        self.assertAlmostEqual(_expense_net(), expense_before - 595.0, places=2)

    def test_new_store_credit_as_payment_grants_animal_trade_credit(self):
        self.assertAlmostEqual(self.partner.avea_credit_balance, 0.0, places=2)
        bill = self._create_bill(900.0)
        applied = self.mixin._avea_apply_store_credit_to_vendor_bill(
            bill,
            self.partner,
            self.company,
            595.0,
            already_issued=False,
            pay_date="2026-11-12",
            payment_ref="77",
        )
        bill.invalidate_recordset(["amount_residual"])
        self.partner.invalidate_recordset(["avea_credit_balance"])

        self.assertAlmostEqual(applied, 595.0, places=2)
        self.assertAlmostEqual(bill.amount_residual, 305.0, places=2)
        self.assertAlmostEqual(self.partner.avea_credit_balance, 595.0, places=2)
        entry = self.Ledger.search(
            [("partner_id", "=", self.partner.id), ("state", "=", "posted")],
            limit=1,
        )
        self.assertEqual(entry.reason_id, self.reason)
        self.assertTrue(entry.account_move_id)

    def test_already_issued_can_exceed_remaining_after_sale(self):
        """Wallet can be lower if they spent some credit; still settle the bill."""
        self._issue_credit(595.0)
        self.Ledger.create_pos_redemption(self.partner, 290.0)
        self.partner.invalidate_recordset(["avea_credit_balance"])
        self.assertAlmostEqual(self.partner.avea_credit_balance, 305.0, places=2)
        bill = self._create_bill(900.0)
        applied = self.mixin._avea_apply_store_credit_to_vendor_bill(
            bill,
            self.partner,
            self.company,
            595.0,
            already_issued=True,
            pay_date="2026-11-12",
            payment_ref="77",
        )
        bill.invalidate_recordset(["amount_residual"])
        self.partner.invalidate_recordset(["avea_credit_balance"])
        self.assertAlmostEqual(applied, 595.0, places=2)
        self.assertAlmostEqual(bill.amount_residual, 305.0, places=2)
        self.assertAlmostEqual(self.partner.avea_credit_balance, 305.0, places=2)

    def test_supplier_bill_pay_wizard_splits_store_credit_and_eft(self):
        journal = self._pay_journal()
        if not journal:
            self.skipTest("No Avea cash/bank journal is configured")
        self._issue_credit(595.0)
        bill = self._create_bill(900.0)
        wizard = self.env["avea.supplier.bill.pay.wizard"].create(
            {
                "bill_id": bill.id,
                "amount": 305.0,
                "pay_date": "2026-11-12",
                "journal_id": journal.id,
                "use_store_credit": True,
                "store_credit_already_issued": True,
                "store_credit_amount": 595.0,
            }
        )
        wizard.action_pay()
        bill.invalidate_recordset(["amount_residual", "payment_state"])
        self.partner.invalidate_recordset(["avea_credit_balance"])
        self.assertTrue(bill.currency_id.is_zero(bill.amount_residual))
        self.assertAlmostEqual(self.partner.avea_credit_balance, 595.0, places=2)

    def test_receive_stock_pays_issued_store_credit_and_eft(self):
        journal = self._pay_journal()
        if not journal:
            self.skipTest("No Avea cash/bank journal is configured")
        self._issue_credit(595.0)
        receive = self.env["avea.stock.receive"].create(
            {
                "partner_id": self.partner.id,
                "invoice_number": "77",
                "invoice_date": "2026-11-12",
                "received_date": "2026-11-12",
                "company_id": self.company.id,
                "currency_id": self.currency.id,
                "invoice_total": 900.0,
                "use_store_credit": True,
                "store_credit_already_issued": True,
                "store_credit_amount": 595.0,
                "mark_as_paid": True,
                "paid_from_journal_id": journal.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "quantity": 6.0,
                            "price_unit": 150.0,
                            "avea_pricing_choice": "keep",
                        }
                    )
                ],
            }
        )
        receive.action_receive_stock()
        receive.invalidate_recordset()
        bill = receive.bill_id
        self.assertTrue(bill)
        self.assertTrue(bill.currency_id.is_zero(bill.amount_residual))
        self.assertAlmostEqual(receive.store_credit_applied, 595.0, places=2)
        cash_paid = bill.currency_id.round(bill.amount_total - 595.0)
        self.assertAlmostEqual(receive.payment_journal_amount, cash_paid, places=2)
        self.partner.invalidate_recordset(["avea_credit_balance"])
        self.assertAlmostEqual(self.partner.avea_credit_balance, 595.0, places=2)
        self.assertIn("Store credit", receive.payment_status)
        self.assertIn("595", receive.payment_status)
        self.assertIn(journal.display_name, receive.payment_status)

    def test_customer_with_store_credit_is_selectable_as_supplier(self):
        customer = self.env["res.partner"].create(
            {
                "name": "Credit Only Customer",
                "customer_rank": 1,
                "company_id": self.company.id,
            }
        )
        self.Ledger.create_issued_credit(
            partner=customer,
            amount=50.0,
            reason=self.reason,
        )
        customer.invalidate_recordset(["avea_credit_balance", "supplier_rank"])
        self.assertGreater(customer.avea_credit_balance, 0.0)
        self.assertEqual(customer.supplier_rank, 0)
        found = self.env["res.partner"].search(
            [
                "|",
                ("supplier_rank", ">", 0),
                ("avea_credit_balance", ">", 0),
                ("id", "=", customer.id),
            ]
        )
        self.assertEqual(found, customer)
