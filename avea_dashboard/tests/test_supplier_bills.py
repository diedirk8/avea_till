# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import OrderedSet
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaSupplierBills(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Avea Bills Manager",
                "login": "avea_bills_mgr@dev.local",
                "email": "avea_bills_mgr@dev.local",
                "company_id": cls.env.company.id,
                "company_ids": [Command.set([cls.env.company.id])],
                "group_ids": [
                    Command.set([cls.env.ref("avea_till.group_avea_manager").id])
                ],
            }
        )
        cls.partner = cls.env["res.partner"].create(
            {"name": "Bills Centre Supplier", "supplier_rank": 1}
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Bills Centre Product",
                "purchase_ok": True,
                "sale_ok": True,
                "is_storable": True,
                "list_price": 100.0,
                "standard_price": 80.0,
            }
        )

    def _create_vendor_move(self, move_type, amount, ref, invoice_date, due=None):
        move = self.env["account.move"].create(
            {
                "move_type": move_type,
                "partner_id": self.partner.id,
                "invoice_date": invoice_date,
                "invoice_date_due": due or invoice_date,
                "ref": ref,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "name": ref,
                            "quantity": 1,
                            "price_unit": amount,
                        }
                    )
                ],
            }
        )
        move.action_post()
        return move

    def _pay_journal(self):
        journals = self.env.company._avea_expense_journals()
        journal = journals.filtered(lambda rec: rec.type == "cash")[:1] or journals[:1]
        if journal:
            return journal
        journal = self.env["account.journal"].search(
            [
                ("type", "in", ("cash", "bank")),
                ("company_id", "=", self.env.company.id),
            ],
            limit=1,
        )
        if journal and journal not in self.env.company.avea_expense_journal_ids:
            self.env.company.write(
                {"avea_expense_journal_ids": [Command.link(journal.id)]}
            )
        return journal

    def test_bill_status_open_overdue_paid_and_credit(self):
        today = fields.Date.context_today(self.env.user)
        open_bill = self._create_vendor_move(
            "in_invoice",
            400.0,
            "OPEN-1",
            today,
            due=today + timedelta(days=14),
        )
        overdue_bill = self._create_vendor_move(
            "in_invoice",
            250.0,
            "OVER-1",
            today - timedelta(days=40),
            due=today - timedelta(days=10),
        )
        paid_bill = self._create_vendor_move(
            "in_invoice",
            180.0,
            "PAID-1",
            today - timedelta(days=5),
            due=today + timedelta(days=5),
        )
        credit = self._create_vendor_move(
            "in_refund",
            90.0,
            "CRED-1",
            today,
            due=today,
        )
        journal = self._pay_journal()
        if not journal:
            self.skipTest("No Avea cash/bank journal is configured")
        self.env["avea.stock.mixin"]._avea_pay_vendor_bill(
            paid_bill,
            journal,
            self.partner,
            self.env.company,
            today,
            "Pay PAID-1",
        )
        paid_bill.invalidate_recordset()
        self.assertEqual(open_bill.avea_bill_status, "open")
        self.assertEqual(overdue_bill.avea_bill_status, "overdue")
        self.assertEqual(paid_bill.avea_bill_status, "paid")
        self.assertEqual(credit.avea_bill_status, "credit")
        self.assertAlmostEqual(open_bill.avea_amount_paid, 0.0, places=2)
        self.assertAlmostEqual(paid_bill.avea_amount_paid, 180.0, places=2)

        Move = self.env["account.move"]
        self.assertIn(open_bill, Move.search([("avea_bill_status", "=", "open")]))
        self.assertIn(overdue_bill, Move.search([("avea_bill_status", "=", "overdue")]))
        self.assertIn(paid_bill, Move.search([("avea_bill_status", "=", "paid")]))
        self.assertIn(credit, Move.search([("avea_bill_status", "=", "credit")]))
        self.assertNotIn(open_bill, Move.search([("avea_bill_status", "=", "paid")]))
        self.assertIn(
            paid_bill,
            Move.search([("avea_bill_status", "in", OrderedSet(["paid"]))]),
        )
        self.assertIn(
            overdue_bill,
            Move.search([("avea_bill_status", "in", ["overdue"])]),
        )
        action_domain = [
            ("move_type", "in", ("in_invoice", "in_refund")),
            ("state", "=", "posted"),
        ]
        paid = Move.search(action_domain + [("avea_bill_status", "=", "paid")])
        self.assertIn(paid_bill, paid)
        self.assertNotIn(open_bill, paid)
        self.assertNotIn(overdue_bill, paid)
        self.assertNotIn(credit, paid)

    def test_bills_and_payments_actions_are_wired(self):
        bills = self.env.ref("avea_till.action_avea_bills")
        self.assertEqual(bills.res_model, "account.move")
        self.assertIn("in_invoice", bills.domain)
        self.assertIn("in_refund", bills.domain)
        self.assertEqual(
            self.env.ref("avea_till.menu_avea_bills").action, bills
        )

        payments = self.env.ref("avea_till.action_avea_supplier_payments")
        self.assertEqual(payments.res_model, "account.bank.statement.line")
        self.assertIn("avea_is_supplier_payment", payments.domain)
        self.assertEqual(
            self.env.ref("avea_till.menu_avea_supplier_payments").action, payments
        )

        back = self.env["account.move"].action_avea_open_bills()
        self.assertEqual(back["res_model"], "account.move")
        self.assertEqual(back["id"], bills.id)

    def test_paid_bill_appears_in_payments(self):
        today = fields.Date.context_today(self.env.user)
        bill = self._create_vendor_move(
            "in_invoice",
            305.0,
            "PAY-1",
            today,
            due=today + timedelta(days=7),
        )
        journal = self._pay_journal()
        if not journal:
            self.skipTest("No Avea cash/bank journal is configured")
        line = self.env["avea.stock.mixin"]._avea_pay_vendor_bill(
            bill,
            journal,
            self.partner,
            self.env.company,
            today,
            "Pay PAY-1",
        )
        self.assertTrue(line.avea_is_supplier_payment)
        self.assertTrue(line.avea_is_bill_payment)
        self.assertEqual(line.avea_payment_kind, "bill")
        self.assertAlmostEqual(line.avea_paid_amount, 305.0, places=2)
        self.assertEqual(line.avea_bank_match_label, "Not on a statement yet")
        self.assertIn(
            line,
            self.env["account.bank.statement.line"].search(
                [("avea_is_bill_payment", "=", True)]
            ),
        )
        found = self.env["account.bank.statement.line"].search(
            [("avea_is_supplier_payment", "=", True), ("id", "=", line.id)]
        )
        self.assertEqual(found, line)
        manager_found = (
            self.env["account.bank.statement.line"]
            .with_user(self.manager)
            .search([("id", "=", line.id)])
        )
        self.assertEqual(manager_found, line)
        view_id = line.with_context(avea_supplier_workspace=True).get_formview_id()
        self.assertEqual(
            view_id, self.env.ref("avea_till.view_avea_supplier_payment_form").id
        )

        partner_bills = self.partner.action_avea_open_supplier_bills()
        self.assertEqual(partner_bills["res_model"], "account.move")
        self.assertIn(("partner_id", "=", self.partner.id), partner_bills["domain"])
        partner_payments = self.partner.action_avea_open_supplier_payments()
        self.assertEqual(partner_payments["res_model"], "account.bank.statement.line")
        self.assertIn(("partner_id", "=", self.partner.id), partner_payments["domain"])

    def test_pay_bills_wizard_one_payment_covers_two_bills(self):
        today = fields.Date.context_today(self.env.user)
        first = self._create_vendor_move(
            "in_invoice", 400.0, "BIO-1", today, due=today + timedelta(days=7)
        )
        second = self._create_vendor_move(
            "in_invoice", 410.0, "BIO-2", today, due=today + timedelta(days=14)
        )
        journal = self._pay_journal()
        if not journal:
            self.skipTest("No Avea cash/bank journal is configured")
        action = self.partner.action_avea_pay_bills()
        self.assertEqual(action["res_model"], "avea.supplier.pay.bills.wizard")
        wizard = (
            self.env["avea.supplier.pay.bills.wizard"]
            .with_context(**action["context"])
            .create(
                {
                    "partner_id": self.partner.id,
                    "pay_date": today,
                    "journal_id": journal.id,
                    "payment_ref": "Biofarm EFT",
                }
            )
        )
        self.assertGreaterEqual(len(wizard.line_ids), 2)
        for line in wizard.line_ids.filtered(lambda rec: rec.bill_id in (first, second)):
            line.pay = True
            line.amount = line.bill_id.amount_residual
        result = wizard.action_pay()
        first.invalidate_recordset()
        second.invalidate_recordset()
        self.assertTrue(first.currency_id.is_zero(first.amount_residual))
        self.assertTrue(second.currency_id.is_zero(second.amount_residual))
        payment = self.env["account.bank.statement.line"].browse(result["res_id"])
        self.assertAlmostEqual(payment.avea_paid_amount, 810.0, places=2)
        self.assertEqual(payment.partner_id, self.partner)
        self.assertTrue(payment.avea_is_supplier_payment)

    def test_pay_bills_wizard_partial_amount_on_one_bill(self):
        today = fields.Date.context_today(self.env.user)
        full = self._create_vendor_move(
            "in_invoice", 250.0, "PART-FULL", today, due=today + timedelta(days=7)
        )
        partial = self._create_vendor_move(
            "in_invoice", 400.0, "PART-OPEN", today, due=today + timedelta(days=7)
        )
        journal = self._pay_journal()
        if not journal:
            self.skipTest("No Avea cash/bank journal is configured")
        wizard = self.env["avea.supplier.pay.bills.wizard"].create(
            {
                "partner_id": self.partner.id,
                "pay_date": today,
                "journal_id": journal.id,
            }
        )
        for line in wizard.line_ids:
            if line.bill_id == full:
                line.pay = True
                line.amount = 250.0
            elif line.bill_id == partial:
                line.pay = True
                line.amount = 100.0
            else:
                line.pay = False
                line.amount = 0.0
        wizard.action_pay()
        full.invalidate_recordset()
        partial.invalidate_recordset()
        self.assertTrue(full.currency_id.is_zero(full.amount_residual))
        self.assertAlmostEqual(partial.amount_residual, 300.0, places=2)

    def test_open_payments_button_works_on_a_record(self):
        today = fields.Date.context_today(self.env.user)
        bill = self._create_vendor_move(
            "in_invoice", 90.0, "BACK-1", today, due=today + timedelta(days=7)
        )
        journal = self._pay_journal()
        if not journal:
            self.skipTest("No Avea cash/bank journal is configured")
        line = self.env["avea.stock.mixin"]._avea_pay_vendor_bill(
            bill, journal, self.partner, self.env.company, today, "Pay BACK-1"
        )
        action = line.action_avea_open_payments()
        self.assertEqual(action["res_model"], "account.bank.statement.line")

    def test_delete_payment_reopens_bills(self):
        today = fields.Date.context_today(self.env.user)
        bill = self._create_vendor_move(
            "in_invoice", 180.0, "UNDO-1", today, due=today + timedelta(days=7)
        )
        journal = self._pay_journal()
        if not journal:
            self.skipTest("No Avea cash/bank journal is configured")
        line = self.env["avea.stock.mixin"]._avea_pay_vendor_bill(
            bill, journal, self.partner, self.env.company, today, "Pay UNDO-1"
        )
        bill.invalidate_recordset()
        self.assertTrue(bill.currency_id.is_zero(bill.amount_residual))
        self.assertTrue(line.avea_can_delete_payment)
        self.assertTrue(line.avea_is_bill_payment)
        line.with_user(self.manager).action_avea_delete_payment()
        bill.invalidate_recordset()
        self.assertAlmostEqual(bill.amount_residual, 180.0, places=2)
        self.assertFalse(
            self.env["account.bank.statement.line"].search([("id", "=", line.id)])
        )

    def test_cannot_delete_payment_matched_on_statement(self):
        today = fields.Date.context_today(self.env.user)
        bill = self._create_vendor_move(
            "in_invoice", 75.0, "MATCHED-1", today, due=today + timedelta(days=7)
        )
        journal = self._pay_journal()
        if not journal:
            self.skipTest("No Avea cash/bank journal is configured")
        line = self.env["avea.stock.mixin"]._avea_pay_vendor_bill(
            bill, journal, self.partner, self.env.company, today, "Pay MATCHED-1"
        )
        line.avea_cleared = True
        line.invalidate_recordset()
        self.assertFalse(line.avea_can_delete_payment)
        with self.assertRaises(UserError):
            line.action_avea_delete_payment()

    def test_cash_movement_is_not_a_bill_payment(self):
        journal = self._pay_journal()
        if not journal:
            self.skipTest("No Avea cash/bank journal is configured")
        payable = self.env["avea.stock.mixin"]._avea_supplier_payable_account(
            self.partner, self.env.company
        )
        line = (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(
                {
                    "journal_id": journal.id,
                    "amount": -8000.0,
                    "date": fields.Date.context_today(self.env.user),
                    "payment_ref": "BANK - XAL",
                    "partner_id": self.partner.id,
                    "counterpart_account_id": payable.id,
                }
            )
        )
        line.invalidate_recordset()
        self.assertTrue(line.avea_is_supplier_payment)
        self.assertFalse(line.avea_is_bill_payment)
        self.assertEqual(line.avea_payment_kind, "other")
        self.assertNotIn(
            line,
            self.env["account.bank.statement.line"].search(
                [("avea_is_bill_payment", "=", True)]
            ),
        )
