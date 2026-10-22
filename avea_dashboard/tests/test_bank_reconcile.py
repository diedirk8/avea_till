# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

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
        wizard = self.env["avea.bank.reconcile.wizard"].create(
            {"journal_id": journal.id, "state": "review"}
        )
        line = self.env["avea.bank.reconcile.line"].create(
            {
                "wizard_id": wizard.id,
                "bank_date": "2026-10-01",
                "description": "FNB TEST PAYMENT",
                "reference": "ABC",
                "amount": -250.0,
            }
        )
        score, hint = line._avea_score_candidate(st_line)
        self.assertGreaterEqual(score, 70.0)
        self.assertIn("amount", hint)
