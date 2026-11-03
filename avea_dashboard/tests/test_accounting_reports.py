# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_accounting_reports")
class TestAveaAccountingReports(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Avea Accounting Reports",
                "login": "avea_acct_reports@dev.local",
                "email": "avea_acct_reports@dev.local",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [
                    Command.set([cls.env.ref("avea_till.group_avea_manager").id])
                ],
            }
        )

    def _env(self):
        return self.env(user=self.manager)

    def test_reports_home_action(self):
        action = self._env()["avea.accounting.reports.home"].action_open_home()
        self.assertEqual(action["res_model"], "avea.accounting.reports.home")
        self.assertEqual(action["view_mode"], "form")
        wizard = self._env()["avea.accounting.reports.home"].browse(action["res_id"])
        self.assertTrue(wizard.exists())
        self.assertEqual(wizard.period, "ytd")

    def test_profit_loss_report_builds(self):
        action = self._env()["avea.accounting.profit.loss"].action_open_report(
            period="ytd"
        )
        self.assertEqual(action["res_model"], "avea.accounting.profit.loss")
        report = self._env()["avea.accounting.profit.loss"].browse(action["res_id"])
        self.assertTrue(report.exists())
        self.assertEqual(report.net_profit, report.total_income - report.total_expense)
        headers = report.line_ids.filtered("is_section_header")
        if report.line_ids.filtered(lambda line: line.section == "income" and not line.is_section_header and not line.is_total):
            self.assertTrue(headers.filtered(lambda line: line.section == "income"))
            self.assertEqual(headers.filtered(lambda line: line.section == "income")[:1].account_name, "INCOME")

    def test_balance_sheet_report_builds(self):
        action = self._env()["avea.accounting.balance.sheet"].action_open_report(
            period="ytd"
        )
        report = self._env()["avea.accounting.balance.sheet"].browse(action["res_id"])
        self.assertTrue(report.exists())
        self.assertTrue(report.as_at_display)

    def test_trial_balance_debits_match_credits(self):
        action = self._env()["avea.accounting.trial.balance"].action_open_report(
            period="ytd"
        )
        report = self._env()["avea.accounting.trial.balance"].browse(action["res_id"])
        self.assertAlmostEqual(report.total_debit, report.total_credit, places=2)

    def test_general_ledger_report_builds(self):
        action = self._env()["avea.accounting.general.ledger"].action_open_report(
            period="ytd"
        )
        report = self._env()["avea.accounting.general.ledger"].browse(action["res_id"])
        self.assertTrue(report.exists())
