# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaSupplierCentre(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Avea Supplier Manager",
                "login": "avea_supplier_mgr@dev.local",
                "email": "avea_supplier_mgr@dev.local",
                "company_id": cls.env.company.id,
                "company_ids": [Command.set([cls.env.company.id])],
                "group_ids": [
                    Command.set([cls.env.ref("avea_till.group_avea_manager").id])
                ],
            }
        )

    def test_create_from_workspace_sets_supplier_rank(self):
        partner = (
            self.env["res.partner"]
            .with_context(avea_supplier_workspace=True)
            .create({"name": "Avea Centre Supplier"})
        )
        self.assertGreater(partner.supplier_rank, 0)
        self.assertTrue(partner.is_company)

    def test_product_shell_uses_avea_supplier_form(self):
        partner = self.env["res.partner"].create(
            {"name": "Shell Supplier", "supplier_rank": 1}
        )
        view_id = partner.with_user(self.manager).get_formview_id()
        expected = self.env.ref("avea_till.view_avea_supplier_form").id
        self.assertEqual(view_id, expected)

    def test_customer_form_still_wins_for_shoppers(self):
        partner = self.env["res.partner"].create(
            {"name": "Shopper Not Supplier", "customer_rank": 1}
        )
        view_id = partner.with_user(self.manager).get_formview_id()
        expected = self.env.ref("avea_till.view_avea_customer_form").id
        self.assertEqual(view_id, expected)

    def test_supplier_workspace_opens_supplier_form_even_if_also_customer(self):
        partner = self.env["res.partner"].create(
            {
                "name": "Both Roles",
                "customer_rank": 1,
                "supplier_rank": 1,
            }
        )
        view_id = partner.with_user(self.manager).with_context(
            avea_supplier_workspace=True
        ).get_formview_id()
        expected = self.env.ref("avea_till.view_avea_supplier_form").id
        self.assertEqual(view_id, expected)

    def test_receive_stock_action_sets_partner(self):
        partner = self.env["res.partner"].create(
            {"name": "Receive From Supplier", "supplier_rank": 1}
        )
        action = partner.action_avea_receive_stock()
        self.assertEqual(action["res_model"], "avea.stock.receive")
        receive = self.env["avea.stock.receive"].browse(action["res_id"])
        self.assertEqual(receive.partner_id, partner)
        self.assertEqual(receive.state, "draft")

    def test_expense_action_prefills_supplier(self):
        partner = self.env["res.partner"].create(
            {"name": "Expense Supplier", "supplier_rank": 1}
        )
        action = partner.action_avea_add_supplier_expense()
        self.assertEqual(action["res_model"], "avea.operational.expense.wizard")
        self.assertEqual(action["context"]["default_partner_id"], partner.id)

    def test_products_action_filters_supplier(self):
        partner = self.env["res.partner"].create(
            {"name": "Catalogue Supplier", "supplier_rank": 1}
        )
        action = partner.action_avea_open_supplier_products()
        self.assertEqual(action["res_model"], "product.template")
        self.assertIn(("avea_supplier_id", "=", partner.id), action["domain"])

    def test_receipts_action_filters_supplier(self):
        partner = self.env["res.partner"].create(
            {"name": "History Supplier", "supplier_rank": 1}
        )
        action = partner.action_avea_open_supplier_receipts()
        self.assertEqual(action["res_model"], "avea.stock.receive")
        self.assertIn(("partner_id", "=", partner.id), action["domain"])

    def test_owing_and_credit_domains(self):
        Partner = self.env["res.partner"]
        self.assertEqual(
            Partner.avea_supplier_owing_domain(),
            [("avea_supplier_payable", ">", 0)],
        )
        self.assertEqual(
            Partner.avea_supplier_credit_domain(),
            [("avea_supplier_credit_available", ">", 0)],
        )

    def test_product_count_follows_supplier_link(self):
        partner = self.env["res.partner"].create(
            {"name": "Linked Supplier", "supplier_rank": 1}
        )
        self.env["product.template"].create(
            {
                "name": "Supplier Centre Product",
                "sale_ok": True,
                "purchase_ok": True,
                "is_storable": True,
                "avea_supplier_id": partner.id,
            }
        )
        partner.invalidate_recordset()
        self.assertEqual(partner.avea_supplier_product_count, 1)

    def _create_unpaid_bill(self, partner, amount, ref="AKWA-1"):
        product = self.env["product.product"].search(
            [("purchase_ok", "=", True)], limit=1
        )
        if not product:
            product = self.env["product.product"].create(
                {
                    "name": "Supplier Bill Product",
                    "purchase_ok": True,
                    "sale_ok": True,
                    "is_storable": True,
                    "list_price": amount,
                    "standard_price": amount,
                }
            )
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": partner.id,
                "invoice_date": "2026-10-01",
                "ref": ref,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "name": "Akwa feed",
                            "quantity": 1,
                            "price_unit": amount,
                        }
                    )
                ],
            }
        )
        bill.action_post()
        return bill

    def test_unpaid_bill_shows_in_what_we_owe(self):
        partner = self.env["res.partner"].create(
            {"name": "Akwa", "supplier_rank": 1}
        )
        bill = self._create_unpaid_bill(partner, 81000.0)
        partner.invalidate_recordset()
        self.assertIn(bill, partner.avea_open_vendor_move_ids)
        self.assertGreater(partner.avea_supplier_payable, 0)
        action = partner.action_avea_open_what_we_owe()
        self.assertEqual(action["res_model"], "account.move")
        self.assertIn(("partner_id", "=", partner.id), action["domain"])
        self.assertIn(("amount_residual", "!=", 0), action["domain"])
        self.assertEqual(bill.avea_supplier_bill_source, "bill")
        self.assertTrue(bill.avea_supplier_bill_label)
        self.assertTrue(bill.avea_can_pay_bill)

    def _pay_journal(self):
        journals = self.env.company._avea_expense_journals()
        journal = journals.filtered(
            lambda rec: rec.type == "cash"
        )[:1] or journals[:1]
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

    def test_pay_unpaid_bill_clears_what_we_owe(self):
        partner = self.env["res.partner"].create(
            {"name": "Akwa Pay", "supplier_rank": 1}
        )
        bill = self._create_unpaid_bill(partner, 810.0, ref="AKWA-PAY")
        self.assertTrue(bill.avea_can_pay_bill)
        action = bill.action_avea_pay_supplier_bill()
        self.assertEqual(action["res_model"], "avea.supplier.bill.pay.wizard")
        wizard = self.env["avea.supplier.bill.pay.wizard"].browse(action["res_id"])
        self.assertEqual(wizard.bill_id, bill)
        self.assertAlmostEqual(wizard.amount, bill.amount_residual, places=2)
        journal = self._pay_journal()
        if not journal:
            self.skipTest("No Avea cash/bank journal is configured")
        wizard.journal_id = journal
        result = wizard.action_pay()
        self.assertEqual(result["res_model"], "res.partner")
        self.assertEqual(result["res_id"], partner.id)
        bill.invalidate_recordset()
        partner.invalidate_recordset()
        self.assertTrue(bill.currency_id.is_zero(bill.amount_residual))
        self.assertFalse(bill.avea_can_pay_bill)
        self.assertNotIn(bill, partner.avea_open_vendor_move_ids)

    def test_manager_can_pay_open_supplier_bill(self):
        partner = self.env["res.partner"].create(
            {"name": "Manager Pay Supplier", "supplier_rank": 1}
        )
        bill = self._create_unpaid_bill(partner, 125.0, ref="MGR-PAY")
        action = bill.with_user(self.manager).action_avea_pay_supplier_bill()
        wizard = (
            self.env["avea.supplier.bill.pay.wizard"]
            .with_user(self.manager)
            .browse(action["res_id"])
        )
        journal = self._pay_journal()
        if not journal:
            self.skipTest("No Avea cash/bank journal is configured")
        wizard.journal_id = journal
        wizard.action_pay()
        bill.invalidate_recordset()
        self.assertTrue(bill.currency_id.is_zero(bill.amount_residual))

    def test_manager_can_read_open_supplier_bill(self):
        partner = self.env["res.partner"].create(
            {"name": "Readable Bill Supplier", "supplier_rank": 1}
        )
        bill = self._create_unpaid_bill(partner, 250.0, ref="READ-1")
        found = (
            self.env["account.move"]
            .with_user(self.manager)
            .search([("id", "=", bill.id)])
        )
        self.assertEqual(found, bill)
        view_id = bill.with_user(self.manager).get_formview_id()
        self.assertEqual(
            view_id, self.env.ref("avea_till.view_avea_supplier_bill_form").id
        )

    def test_supplier_centre_action_is_wired(self):
        action = self.env.ref("avea_till.action_avea_supplier_centre")
        self.assertEqual(action.res_model, "res.partner")
        self.assertIn("supplier_rank", action.domain)
        menu = self.env.ref("avea_till.menu_avea_supplier_centre")
        self.assertEqual(menu.action, action)
