# -*- coding: utf-8 -*-
import base64

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.avea_till.models.operations.bank_reconcile_booking_rules import (
    AveaBankReconcileBookingRules,
)
from odoo.addons.avea_till.models.operations.bank_statement_parser import (
    AveaBankStatementParser,
)
from odoo.addons.avea_till.models.operations.merchant_payout_parser import (
    AveaMerchantPayoutParser,
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

    def test_fnb_service_fee_and_card_settlement_names(self):
        from odoo.addons.avea_till.models.operations.bank_statement_parser import (
            _clean_fnb_description,
        )

        fee, original = _clean_fnb_description("09 Jul", -1.07)
        self.assertEqual(fee, "FNB service fee")
        self.assertEqual(original, "09 Jul")
        blank_fee, _blank_ref = _clean_fnb_description("", -349.0, "")
        self.assertEqual(blank_fee, "FNB service fee")
        card, _card_ref = _clean_fnb_description("", -94.09, "400568*2514 18 Jul")
        self.assertEqual(card, "POS purchase")
        named, _named_ref = _clean_fnb_description("POS Purchase Checkers Sixty60", -1535.22)
        self.assertEqual(named, "POS Purchase Checkers Sixty60")
        name, raw = _clean_fnb_description(
            "Magtape Credit Capitec 0107Possettle 260630",
            651.57,
        )
        self.assertEqual(name, "Capitec card settlement (sales 30 Jun 2026)")
        self.assertIn("Possettle", raw)
        yoco, _raw = _clean_fnb_description("Magtape Credit Yoco 9Chxd 010726", 2869.47)
        self.assertEqual(yoco, "Yoco card settlement (sales 1 Jul 2026)")

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
        self.assertTrue(line.amount_spent_display)
        self.assertFalse(line.amount_received_display)
        self.assertFalse(line.is_card_settlement)
        received = self.env["avea.bank.reconcile.line"].create(
            {
                "reconciliation_id": reconciliation.id,
                "bank_date": "2026-07-01",
                "description": "Capitec card settlement (sales 30 Jun 2026)",
                "amount": 651.57,
            }
        )
        self.assertFalse(received.amount_spent_display)
        self.assertTrue(received.amount_received_display)
        self.assertTrue(received.is_card_settlement)
        self.assertIn("Settle", received.booking_suggestion or "")
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

    def test_extract_salary_payee_name(self):
        name = AveaBankReconcileBookingRules._avea_extract_employee_name(
            "Payshap Account Off-Us N Mokoena Salary"
        )
        self.assertEqual(name, "N Mokoena")

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

    def _bank_journal(self):
        journal = self.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", self.env.company.id)],
            limit=1,
        )
        if not journal or not journal.suspense_account_id:
            return self.env["account.journal"]
        return journal

    def _statement_line(self, journal, **vals):
        values = {
            "journal_id": journal.id,
            "amount": -80.0,
            "date": "2026-07-15",
            "payment_ref": "AVEA RECON TEST",
            "counterpart_account_id": journal.suspense_account_id.id,
        }
        values.update(vals)
        return (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(values)
        )

    def test_reversed_or_near_amount_does_not_score(self):
        journal = self._bank_journal()
        if not journal:
            return
        st_line = self._statement_line(journal, amount=-250.0, payment_ref="RENT")
        reconciliation = self.env["avea.bank.reconciliation"].create(
            {"journal_id": journal.id, "state": "in_progress", "date_to": "2026-07-31"}
        )
        line = self.env["avea.bank.reconcile.line"].create(
            {
                "reconciliation_id": reconciliation.id,
                "bank_date": "2026-07-15",
                "description": "RENT",
                "amount": 250.0,
            }
        )
        score, _hint = line._avea_score_candidate(st_line)
        self.assertEqual(score, 0.0)
        near = self._statement_line(journal, amount=-249.0, payment_ref="RENT")
        score, _hint = line._avea_score_candidate(near)
        self.assertEqual(score, 0.0)

    def test_one_book_entry_matches_only_one_statement_line(self):
        journal = self._bank_journal()
        if not journal:
            return
        st_line = self._statement_line(
            journal, amount=-42.42, date="2026-07-10", payment_ref="ONCE"
        )
        reconciliation = self.env["avea.bank.reconciliation"].create(
            {
                "journal_id": journal.id,
                "state": "in_progress",
                "date_from": "2026-07-01",
                "date_to": "2026-07-31",
            }
        )
        for _index in range(2):
            self.env["avea.bank.reconcile.line"].create(
                {
                    "reconciliation_id": reconciliation.id,
                    "bank_date": "2026-07-10",
                    "description": "ONCE",
                    "amount": -42.42,
                }
            )
        reconciliation._avea_match_lines()
        linked = reconciliation.line_ids.filtered(
            lambda line: line.statement_line_id == st_line
        )
        self.assertEqual(len(linked), 1)

    def test_older_book_entry_is_outstanding_only_when_asked(self):
        journal = self._bank_journal()
        if not journal:
            return
        old = self._statement_line(
            journal, amount=-15.0, date="2098-05-01", payment_ref="OLD CHEQUE"
        )
        reconciliation = self.env["avea.bank.reconciliation"].create(
            {
                "journal_id": journal.id,
                "state": "in_progress",
                "date_from": "2099-07-01",
                "date_to": "2099-07-31",
            }
        )
        outstanding = reconciliation._avea_outstanding_statement_lines()
        if reconciliation._avea_has_prior_reconciliation():
            self.assertIn(old, outstanding)
        else:
            self.assertNotIn(old, outstanding)
            reconciliation.prior_items_outstanding = True
            self.assertIn(old, reconciliation._avea_outstanding_statement_lines())

    def test_complete_requires_a_zero_difference_and_clears_the_line(self):
        journal = self._bank_journal()
        if not journal:
            return
        st_line = self._statement_line(
            journal,
            amount=-321.55,
            date="2099-07-20",
            payment_ref="CLEAR ME",
        )
        reconciliation = self.env["avea.bank.reconciliation"].create(
            {
                "journal_id": journal.id,
                "state": "in_progress",
                "date_from": "2099-07-01",
                "date_to": "2099-07-31",
                "balances_from_file": True,
                "prior_items_outstanding": True,
            }
        )
        self.env["avea.bank.reconcile.line"].create(
            {
                "reconciliation_id": reconciliation.id,
                "bank_date": "2099-07-20",
                "description": "CLEAR ME",
                "amount": -321.55,
            }
        )
        reconciliation._avea_match_lines()
        self.assertEqual(reconciliation.line_ids.match_state, "matched")
        with self.assertRaises(UserError):
            reconciliation.action_apply_reconciliation()
        currency = reconciliation.currency_id
        reconciliation.closing_balance = reconciliation.adjusted_book_balance
        reconciliation.opening_balance = currency.round(
            reconciliation.closing_balance - sum(reconciliation.line_ids.mapped("amount"))
        )
        self.assertTrue(currency.is_zero(reconciliation.statement_difference))
        reconciliation.action_apply_reconciliation()
        self.assertEqual(reconciliation.state, "done")
        self.assertTrue(st_line.avea_cleared)
        self.assertEqual(st_line.avea_cleared_reconciliation_id, reconciliation)
        again = self.env["avea.bank.reconciliation"].create(
            {
                "journal_id": journal.id,
                "state": "in_progress",
                "date_from": "2099-08-01",
                "date_to": "2099-08-31",
            }
        )
        self.env["avea.bank.reconcile.line"].create(
            {
                "reconciliation_id": again.id,
                "bank_date": "2099-07-20",
                "description": "CLEAR ME",
                "amount": -321.55,
            }
        )
        again._avea_match_lines()
        self.assertFalse(again.line_ids.statement_line_id)

    def _reconcile_line(self, journal, amount, description="Allocate test"):
        reconciliation = self.env["avea.bank.reconciliation"].create(
            {
                "journal_id": journal.id,
                "state": "in_progress",
                "date_from": "2099-07-01",
                "date_to": "2099-07-31",
            }
        )
        line = self.env["avea.bank.reconcile.line"].create(
            {
                "reconciliation_id": reconciliation.id,
                "bank_date": "2099-07-18",
                "description": description,
                "amount": amount,
            }
        )
        return line

    def test_match_open_vendor_bill(self):
        journal = self._bank_journal()
        if not journal:
            return
        partner = self.env["res.partner"].create({"name": "Avea Recon Supplier"})
        expense = self.env["account.account"].search(
            [
                ("account_type", "=", "expense"),
                ("company_ids", "in", self.env.company.id),
            ],
            limit=1,
        )
        if not expense:
            return
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": partner.id,
                "invoice_date": "2099-07-18",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Shop supplies",
                            "account_id": expense.id,
                            "quantity": 1,
                            "price_unit": 88.0,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
            }
        )
        bill.action_post()
        line = self._reconcile_line(journal, -bill.amount_residual, partner.name)
        wizard = self.env["avea.bank.reconcile.apply"].create(
            {
                "reconcile_line_id": line.id,
                "mode": "match",
                "move_ids": [Command.set(bill.ids)],
            }
        )
        wizard.action_apply()
        self.assertEqual(line.match_state, "matched")
        self.assertTrue(line.statement_line_id)
        self.assertEqual(bill.payment_state, "paid")

    def test_split_bank_line_across_two_accounts(self):
        journal = self._bank_journal()
        if not journal or not journal.suspense_account_id:
            return
        accounts = self.env["account.account"].search(
            [
                ("account_type", "=", "expense"),
                ("company_ids", "in", self.env.company.id),
            ],
            limit=2,
        )
        if len(accounts) < 2:
            return
        line = self._reconcile_line(journal, -100.0, "Split payment")
        wizard = self.env["avea.bank.reconcile.apply"].create(
            {
                "reconcile_line_id": line.id,
                "mode": "split",
                "split_line_ids": [
                    Command.create(
                        {"account_id": accounts[0].id, "name": "Fuel", "amount": 40.0}
                    ),
                    Command.create(
                        {"account_id": accounts[1].id, "name": "Repairs", "amount": 60.0}
                    ),
                ],
            }
        )
        wizard.action_apply()
        self.assertEqual(line.match_state, "matched")
        move_lines = line.statement_line_id.move_id.line_ids
        fuel = move_lines.filtered(lambda item: item.account_id == accounts[0])
        repairs = move_lines.filtered(lambda item: item.account_id == accounts[1])
        self.assertAlmostEqual(fuel.debit, 40.0, places=2)
        self.assertAlmostEqual(repairs.debit, 60.0, places=2)

    def test_transfer_between_money_accounts(self):
        journal = self._bank_journal()
        if not journal:
            return
        others = self.env.company._avea_transfer_journals() - journal
        other = others[:1]
        if not other:
            return
        line = self._reconcile_line(journal, -55.0, "Move to cash")
        wizard = self.env["avea.bank.reconcile.apply"].create(
            {
                "reconcile_line_id": line.id,
                "mode": "transfer",
                "transfer_journal_id": other.id,
            }
        )
        wizard.action_apply()
        self.assertEqual(line.match_state, "matched")
        self.assertEqual(line.statement_line_id.journal_id, journal)
        self.assertAlmostEqual(line.statement_line_id.amount, -55.0, places=2)

    def test_parse_yoco_csv_skips_sep_and_includes_capital(self):
        content = """sep=,
Date,Amount,Fee amount,Fee VAT amount,Capital Repayment,Pocket Savings,State
2026/08/01 00:01:04,3062.51,99.50,13.00,602.29,0,paid
2026/09/01 00:01:02,3965.99,81.97,10.70,771.04,0,paid
"""
        raw = content.encode()
        self.assertEqual(AveaMerchantPayoutParser.detect("Yoco-payouts.csv", raw), "yoco")
        parsed = AveaMerchantPayoutParser.parse("Yoco-payouts.csv", raw)
        self.assertEqual(parsed["provider"], "yoco")
        self.assertEqual(len(parsed["payouts"]), 2)
        first = next(row for row in parsed["payouts"] if str(row["payout_date"]) == "2026-08-01")
        self.assertEqual(str(first["payout_date"]), "2026-08-01")
        self.assertAlmostEqual(first["net_amount"], 3062.51)
        self.assertAlmostEqual(first["fee_amount"], 112.50)
        self.assertAlmostEqual(first["capital_amount"], 602.29)
        self.assertAlmostEqual(first["gross_amount"], 3777.30)

    def test_parse_capitec_merchant_statement_text(self):
        content = """
Capitec Bank Limited
Merchant Statement
PETS EMPIRE
Statement period 2 Jul 2026 - 1 Aug 2026
All settlements
Payout Date Reference Total
02/07/2026 CAPITEC 0207PosSettle 260701 R2 375.55
03/07/2026 CAPITEC 0307PosSettle 260702 R2 165.23
Settlements for card machine transactions: NP531080 Total: R4 598.00
02/07/2026 CAPITEC 0207PosSettle 260701 R2 399.00
03/07/2026 CAPITEC 0307PosSettle 260702 R2 199.00
"""
        parsed = AveaMerchantPayoutParser._parse_capitec_text(content)
        self.assertEqual(parsed["provider"], "capitec")
        self.assertEqual(len(parsed["payouts"]), 2)
        first = parsed["payouts"][0]
        self.assertEqual(str(first["payout_date"]), "2026-07-02")
        self.assertEqual(str(first["trading_date"]), "2026-07-01")
        self.assertAlmostEqual(first["net_amount"], 2375.55)
        self.assertAlmostEqual(first["gross_amount"], 2399.00)
        self.assertAlmostEqual(first["fee_amount"], 23.45)
        self.assertAlmostEqual(first["capital_amount"], 0.0)

    def test_parse_capitec_columnar_merchant_pdf_text(self):
        content = """
Merchant Statement
Capitec Bank Limited
All settlements
Payout Date
Reference
02/07/2026
CAPITEC 0207PosSettle 260701
03/07/2026
CAPITEC 0307PosSettle 260702
Total
R2 375.55
R2 165.23
Settlements for card machine transactions: NP531080 Total: R4 598.00
02/07/2026
CAPITEC 0207PosSettle 260701
03/07/2026
CAPITEC 0307PosSettle 260702
R2 399.00
R2 199.00
"""
        parsed = AveaMerchantPayoutParser._parse_capitec_text(content)
        self.assertEqual(len(parsed["payouts"]), 2)
        self.assertAlmostEqual(parsed["payouts"][0]["net_amount"], 2375.55)
        self.assertAlmostEqual(parsed["payouts"][0]["gross_amount"], 2399.00)
        self.assertAlmostEqual(parsed["payouts"][1]["gross_amount"], 2199.00)
        self.assertAlmostEqual(sum(row["gross_amount"] for row in parsed["payouts"]), 4598.00)

    def test_parse_capitec_legacy_detail_of_deposits(self):
        content = """
Capitec Bank Limited
Merchant Statement
PETS EMPIRE
Statement Period
02 Sep - 01 Oct 2024
DETAIL OF DEPOSITS
Batch Transmission Date
2024-09-02
2024-09-03
Reference Number
CAPITEC 0209PosSettle 240902
CAPITEC 0309PosSettle 240903
Total Deposit Amount
355.49
5 584.27
5 939.76
A registered credit provider. NCR Reg. No.: NCRCP13
Batch Total
359.00
5 673.00
"""
        parsed = AveaMerchantPayoutParser._parse_capitec_text(content)
        self.assertEqual(len(parsed["payouts"]), 2)
        first = parsed["payouts"][0]
        self.assertEqual(str(first["payout_date"]), "2024-09-02")
        self.assertEqual(str(first["trading_date"]), "2024-09-02")
        self.assertAlmostEqual(first["net_amount"], 355.49)
        self.assertAlmostEqual(first["gross_amount"], 359.00)
        self.assertAlmostEqual(first["fee_amount"], 3.51)
        self.assertAlmostEqual(parsed["payouts"][1]["net_amount"], 5584.27)
        self.assertAlmostEqual(parsed["payouts"][1]["gross_amount"], 5673.00)

    def test_parse_capitec_drops_scrambled_gross_column(self):
        content = """
Merchant Statement
Capitec Bank Limited
All settlements
02/07/2026 CAPITEC 0207PosSettle 260701 R100.00
03/07/2026 CAPITEC 0307PosSettle 260702 R200.00
Settlements for card machine
02/07/2026 CAPITEC 0207PosSettle 260701 R250.00
03/07/2026 CAPITEC 0307PosSettle 260702 R50.00
"""
        parsed = AveaMerchantPayoutParser._parse_capitec_text(content)
        self.assertEqual(len(parsed["payouts"]), 2)
        self.assertAlmostEqual(parsed["payouts"][0]["net_amount"], 100.0)
        self.assertAlmostEqual(parsed["payouts"][0]["gross_amount"], 100.0)
        self.assertAlmostEqual(parsed["payouts"][0]["fee_amount"], 0.0)
        self.assertAlmostEqual(parsed["payouts"][1]["net_amount"], 200.0)

    def test_yoco_file_rejected_as_bank_statement(self):
        journal = self._bank_journal()
        if not journal:
            return
        content = """sep=,
Date,Amount,Fee amount,Fee VAT amount,Capital Repayment,State
2026/08/01 00:01:04,3062.51,99.50,13.00,602.29,paid
"""
        reconciliation = self.env["avea.bank.reconciliation"].create(
            {
                "journal_id": journal.id,
                "state": "draft",
                "statement_file": base64.b64encode(content.encode()),
                "statement_filename": "Yoco-payouts.csv",
            }
        )
        with self.assertRaises(UserError):
            reconciliation.action_parse_statement()

    def test_yoco_payout_matches_fnb_line_and_splits_capital(self):
        journal = self._bank_journal()
        if not journal:
            return
        card = self.env["pos.payment.method"].search([("name", "ilike", "card")], limit=1)
        if not card or not card.outstanding_account_id:
            return
        fee_account = self.env["account.account"].search(
            [
                ("company_ids", "in", self.env.company.id),
                ("account_type", "=", "expense"),
            ],
            limit=1,
        )
        loan_account = self.env["account.account"].search(
            [
                ("company_ids", "in", self.env.company.id),
                ("account_type", "=", "liability_current"),
            ],
            limit=1,
        )
        if not fee_account or not loan_account:
            return
        yoco = """sep=,
Date,Amount,Fee amount,Fee VAT amount,Capital Repayment,State
2026/08/01 00:01:04,3062.51,99.50,13.00,602.29,paid
"""
        fnb = """Date,Description,Amount
2026-08-01,Yoco card settlement (sales 1 Aug 2026),3062.51
"""
        reconciliation = self.env["avea.bank.reconciliation"].create(
            {
                "journal_id": journal.id,
                "state": "draft",
                "date_from": "2026-08-01",
                "date_to": "2026-08-31",
                "statement_file": base64.b64encode(fnb.encode()),
                "statement_filename": "statement.csv",
                "merchant_file_ids": [
                    Command.create(
                        {
                            "datas": base64.b64encode(yoco.encode()),
                            "filename": "Yoco-payouts.csv",
                        }
                    )
                ],
            }
        )
        reconciliation.action_parse_statement()
        line = reconciliation.line_ids[:1]
        self.assertTrue(line.is_card_settlement)
        self.assertTrue(line.merchant_payout_id)
        self.assertAlmostEqual(line.merchant_payout_id.gross_amount, 3777.30)
        self.assertEqual(reconciliation.ready_card_batch_count, 1)
        wizard = self.env["avea.bank.reconcile.apply"].create(
            {
                "reconcile_line_id": line.id,
                "mode": "settlement",
                "settlement_gross": line.merchant_payout_id.gross_amount,
                "settlement_capital": line.merchant_payout_id.capital_amount,
                "fee_account_id": fee_account.id,
                "capital_account_id": loan_account.id,
            }
        )
        self.assertAlmostEqual(wizard.settlement_fee, 112.50)
        wizard.action_apply()
        move_lines = line.statement_line_id.move_id.line_ids
        self.assertAlmostEqual(
            sum(move_lines.filtered(lambda aml: aml.account_id == fee_account).mapped("debit")),
            112.50,
            places=2,
        )
        self.assertAlmostEqual(
            sum(move_lines.filtered(lambda aml: aml.account_id == loan_account).mapped("debit")),
            602.29,
            places=2,
        )
        outstanding = card.outstanding_account_id
        self.assertAlmostEqual(
            sum(move_lines.filtered(lambda aml: aml.account_id == outstanding).mapped("credit")),
            3777.30,
            places=2,
        )

    def test_statement_dates_are_editable_and_refresh_card_period(self):
        journal = self._bank_journal()
        if not journal:
            return
        reconciliation = self.env["avea.bank.reconciliation"].create(
            {
                "journal_id": journal.id,
                "state": "in_progress",
                "date_from": "2026-08-01",
                "date_to": "2026-08-31",
                "line_filter": "needs_work",
            }
        )
        payout = self.env["avea.bank.reconcile.merchant.payout"].create(
            {
                "reconciliation_id": reconciliation.id,
                "provider": "yoco",
                "payout_date": "2026-08-15",
                "net_amount": 100.0,
                "gross_amount": 110.0,
                "fee_amount": 10.0,
                "capital_amount": 0.0,
                "on_this_statement": True,
            }
        )
        reconciliation.write({"date_from": "2026-09-01", "date_to": "2026-09-30"})
        self.assertFalse(payout.on_this_statement)
        reconciliation.write({"date_from": "2026-08-01", "date_to": "2026-08-31"})
        self.assertTrue(payout.on_this_statement)

    def test_work_filter_hides_matched_lines_and_ranks_unmatched_first(self):
        journal = self._bank_journal()
        if not journal:
            return
        reconciliation = self.env["avea.bank.reconciliation"].create(
            {
                "journal_id": journal.id,
                "state": "in_progress",
                "date_from": "2026-08-01",
                "date_to": "2026-08-31",
            }
        )
        unmatched = self.env["avea.bank.reconcile.line"].create(
            {
                "reconciliation_id": reconciliation.id,
                "bank_date": "2026-08-10",
                "description": "Unmatched rent",
                "amount": -50.0,
                "match_state": "unmatched",
                "sequence": 20,
            }
        )
        matched = self.env["avea.bank.reconcile.line"].create(
            {
                "reconciliation_id": reconciliation.id,
                "bank_date": "2026-08-01",
                "description": "Already done",
                "amount": -10.0,
                "match_state": "matched",
                "sequence": 10,
            }
        )
        self.assertEqual(reconciliation.work_remaining_count, 1)
        self.assertEqual(reconciliation.line_filter, "needs_work")
        self.assertEqual(reconciliation.display_line_ids, unmatched)
        self.assertIn("Record", unmatched.work_hint)
        reconciliation.line_filter = "all"
        self.assertEqual(reconciliation.display_line_ids, unmatched | matched)
        self.assertLess(unmatched.match_work_rank, matched.match_work_rank)
        self.assertEqual(reconciliation.next_step_kind, "work_lines")

    def test_draft_guidance_asks_for_the_statement_file(self):
        journal = self._bank_journal()
        if not journal:
            return
        reconciliation = self.env["avea.bank.reconciliation"].create(
            {"journal_id": journal.id, "state": "draft"}
        )
        self.assertEqual(reconciliation.next_step_kind, "upload")
        self.assertFalse(reconciliation.can_complete)
        reconciliation.statement_filename = "fnb.pdf"
        reconciliation.statement_file = base64.b64encode(b"placeholder")
        self.assertEqual(reconciliation.next_step_kind, "load")
