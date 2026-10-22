# -*- coding: utf-8 -*-
import base64

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.avea_till.models.operations.bank_reconcile_booking_rules import (
    AveaBankReconcileBookingRules,
)
from odoo.addons.avea_till.models.operations.bank_statement_parser import (
    AveaBankStatementParser,
)


@tagged("post_install", "-at_install", "avea_till")
class TestAveaBankReconcile(TransactionCase):
    def test_parse_fnb_style_csv(self):
        content = """Recreated Statement
Date,20241001
Account Number,62812345678
Opening Balance,1000.00
Closing Balance,850.00
Effective Date,Description,Reference,Amount,Balance
20241002,Supplier payment,INV001,-150.00,850.00
"""
        parsed = AveaBankStatementParser.parse("fnb_statement.csv", content.encode())
        self.assertEqual(parsed["source"], "fnb_csv")
        self.assertEqual(parsed["account_number"], "62812345678")
        self.assertEqual(len(parsed["transactions"]), 1)
        tx = parsed["transactions"][0]
        self.assertEqual(str(tx["date"]), "2024-10-02")
        self.assertEqual(tx["amount"], -150.0)
        self.assertEqual(tx["reference"], "INV001")

    def test_parse_fnb_gold_business_columnar_pdf(self):
        content = """
Gold Business Account : 62920038462
Statement Period : 30 June 2026 to 31 July 2026
Transactions in RAND (ZAR)

Date
Description
Amount
Balance

01 Jul Payshap Account Off-Us N Mokoena Salary
01 Jul
FNB App Payment From Cash
5,599.41
1,000.00Cr
2,307.97Cr
3,307.97Cr
"""
        parsed = AveaBankStatementParser._parse_fnb_pdf_text(content)
        self.assertGreaterEqual(len(parsed["transactions"]), 2)
        self.assertEqual(parsed["transactions"][0]["amount"], -5599.41)
        self.assertEqual(parsed["transactions"][1]["amount"], 1000.0)

    def test_parse_fnb_pdf_text(self):
        content = """
FIRST NATIONAL BANK
Statement period: 01 March 2024 to 31 March 2024
Account Number: 62812345678
Opening Balance 10 000.00
Closing Balance 9 850.00

Date Description Amount Balance Accrued Bank Charges
01 Mar Supplier payment -150.00 9 850.00 0.00
15 Mar Customer deposit 500.00 10 350.00 0.00
"""
        parsed = AveaBankStatementParser._parse_fnb_pdf_text(content)
        self.assertEqual(parsed["source"], "fnb_pdf")
        self.assertEqual(len(parsed["transactions"]), 2)
        self.assertEqual(parsed["transactions"][0]["amount"], -150.0)
        self.assertEqual(str(parsed["transactions"][0]["date"]), "2024-03-01")

    def test_parse_generic_header_csv(self):
        content = """Date,Description,Amount
2024-10-05,Card purchase,-45.50
2024-10-06,Deposit,200.00
"""
        parsed = AveaBankStatementParser.parse("statement.csv", content.encode())
        self.assertEqual(len(parsed["transactions"]), 2)
        self.assertEqual(parsed["transactions"][0]["amount"], -45.5)

    def test_match_scores_existing_statement_line(self):
        journal = self.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", self.env.company.id)],
            limit=1,
        )
        if not journal or not journal.suspense_account_id:
            return
        st_line = (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(
                {
                    "journal_id": journal.id,
                    "amount": -250.0,
                    "date": "2026-10-01",
                    "payment_ref": "FNB TEST PAYMENT",
                    "counterpart_account_id": journal.suspense_account_id.id,
                }
            )
        )
        reconciliation = self.env["avea.bank.reconciliation"].create(
            {"journal_id": journal.id, "state": "in_progress"}
        )
        line = self.env["avea.bank.reconcile.line"].create(
            {
                "reconciliation_id": reconciliation.id,
                "bank_date": "2026-10-01",
                "description": "FNB TEST PAYMENT",
                "reference": "ABC",
                "amount": -250.0,
            }
        )
        score, hint = line._avea_score_candidate(st_line)
        self.assertGreaterEqual(score, 70.0)
        self.assertIn("amount", hint)

    def test_possible_match_near_date(self):
        journal = self.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", self.env.company.id)],
            limit=1,
        )
        if not journal or not journal.suspense_account_id:
            return
        st_line = (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(
                {
                    "journal_id": journal.id,
                    "amount": -5599.41,
                    "date": "2026-07-02",
                    "payment_ref": "N Mokoena Salary",
                    "counterpart_account_id": journal.suspense_account_id.id,
                }
            )
        )
        reconciliation = self.env["avea.bank.reconciliation"].create(
            {"journal_id": journal.id, "state": "in_progress"}
        )
        line = self.env["avea.bank.reconcile.line"].create(
            {
                "reconciliation_id": reconciliation.id,
                "bank_date": "2026-07-01",
                "description": "Payshap N Mokoena Salary",
                "amount": -5599.41,
            }
        )
        score, _hint = line._avea_score_candidate(st_line)
        self.assertGreaterEqual(score, 50.0)
        reconciliation._avea_match_lines()
        line.invalidate_recordset()
        self.assertIn(line.match_state, ("matched", "possible"))
        self.assertTrue(line.book_match_summary)

    def test_booking_suggestion_bank_fee_date_only(self):
        journal = self.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", self.env.company.id)],
            limit=1,
        )
        if not journal:
            return
        reconciliation = self.env["avea.bank.reconciliation"].create(
            {"journal_id": journal.id, "state": "in_progress"}
        )
        line = self.env["avea.bank.reconcile.line"].create(
            {
                "reconciliation_id": reconciliation.id,
                "bank_date": "2026-07-09",
                "description": "09 Jul",
                "amount": -1.07,
            }
        )
        self.assertIn("bank charge", (line.booking_suggestion or "").lower())
        line._avea_apply_booking_suggestion()
        self.assertEqual(line.import_action, "expense")

    def test_booking_suggestion_fuel_and_salary(self):
        company = self.env.company
        currency = company.currency_id
        fuel = AveaBankReconcileBookingRules.infer(
            self.env,
            company=company,
            description="POS Purchase Engen Garage",
            reference="",
            amount=-450.0,
            bank_date="2026-07-10",
            currency=currency,
        )
        self.assertIn("fuel", fuel["booking_suggestion"].lower())
        salary = AveaBankReconcileBookingRules.infer(
            self.env,
            company=company,
            description="Payshap N Mokoena Salary",
            reference="",
            amount=-5599.41,
            bank_date="2026-07-01",
            currency=currency,
        )
        self.assertIn("salary", salary["booking_suggestion"].lower())

    def test_parse_statement_csv_and_read_lines(self):
        journal = self.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", self.env.company.id)],
            limit=1,
        )
        if not journal:
            return
        csv_body = """Date,Description,Amount
2024-10-05,Card purchase,-45.50
"""
        reconciliation = self.env["avea.bank.reconciliation"].create(
            {
                "journal_id": journal.id,
                "state": "draft",
                "statement_file": base64.b64encode(csv_body.encode()),
                "statement_filename": "statement.csv",
            }
        )
        reconciliation.action_parse_statement()
        self.assertEqual(reconciliation.state, "in_progress")
        self.assertEqual(len(reconciliation.line_ids), 1)
        data = reconciliation.with_context(
            avea_bank_reconcile_labels=True
        ).line_ids.read(["statement_line_id", "book_match_summary"])
        self.assertEqual(len(data), 1)
