# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_stock")
class TestAveaStockReceiveReport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Zzqx Report Supplier",
                "supplier_rank": 1,
                "company_id": cls.company.id,
                "is_company": True,
            }
        )
        cls.purchase_tax = cls.company.account_purchase_tax_id
        cls.sale_tax = cls.company.account_sale_tax_id
        cls.product = cls.env["product.product"].create(
            {
                "name": "Zzqx Report Filter F-800",
                "default_code": "SKU-F800",
                "barcode": "6001234567890",
                "type": "consu",
                "is_storable": True,
                "list_price": 115.0,
                "standard_price": 50.0,
                "avea_cost_ex_tax": 50.0,
                "purchase_ok": True,
                "sale_ok": True,
                "company_id": cls.company.id,
                "supplier_taxes_id": [Command.set(cls.purchase_tax.ids)]
                if cls.purchase_tax
                else False,
                "taxes_id": [Command.set(cls.sale_tax.ids)] if cls.sale_tax else False,
            }
        )
        cls.env["product.supplierinfo"].create(
            {
                "partner_id": cls.partner.id,
                "product_tmpl_id": cls.product.product_tmpl_id.id,
                "product_code": "SUP-F800",
                "price": 50.0,
            }
        )
        warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        if not warehouse:
            raise AssertionError("Warehouse required for Receive Stock report tests")
        cls.company.write(
            {
                "avea_stock_receive_report_email": "owner-report@example.com",
                "avea_receipt_sender_email": "sender@example.com",
            }
        )
        pdf_patcher = patch.object(
            type(cls.env["avea.stock.receive"]),
            "_avea_receive_report_pdf_content",
            lambda self: b"%PDF-1.4 test receive report",
        )
        pdf_patcher.start()
        cls.addClassCleanup(pdf_patcher.stop)

    def _create_receive(self, *, cost=50.0, qty=2.0, choice="keep", extra=None):
        values = {
            "partner_id": self.partner.id,
            "invoice_number": "IO-REPORT-1",
            "invoice_date": fields.Date.today(),
            "received_date": fields.Date.today(),
            "company_id": self.company.id,
            "currency_id": self.currency.id,
            "mark_as_paid": False,
            "line_ids": [
                Command.create(
                    {
                        "product_id": self.product.id,
                        "quantity": qty,
                        "price_unit": cost,
                        "avea_pricing_choice": choice,
                    }
                )
            ],
        }
        if extra:
            values.update(extra)
        return self.env["avea.stock.receive"].create(values)

    def test_dedicated_report_email_overrides_owners(self):
        recipients = self.company._avea_stock_receive_report_recipients()
        self.assertEqual(recipients, ["owner-report@example.com"])

    def test_invalid_report_email_raises(self):
        with self.assertRaises(ValidationError):
            self.company.avea_stock_receive_report_email = "not-an-email"

    def test_blank_report_email_uses_owner_users(self):
        owner = self.env["res.users"].create(
            {
                "name": "Zzqx Receive Owner",
                "login": "zzqx_receive_owner@dev.local",
                "email": "zzqx_receive_owner@dev.local",
                "company_id": self.company.id,
                "company_ids": [Command.set([self.company.id])],
                "group_ids": [
                    Command.set([self.env.ref("avea_till.group_avea_owner").id])
                ],
            }
        )
        self.company.avea_stock_receive_report_email = False
        recipients = self.company._avea_stock_receive_report_recipients()
        self.assertIn(owner.email, recipients)

    def test_report_lists_sku_barcode_supplier_code_markup_and_profit(self):
        receive = self._create_receive(cost=50.0, qty=2.0, choice="keep")
        receive.action_receive_stock()
        self.assertEqual(receive.state, "done")
        values = receive._avea_receive_report_line_values(receive.line_ids)
        self.assertEqual(values["sku"], "SKU-F800")
        self.assertEqual(values["barcode"], "6001234567890")
        self.assertEqual(values["supplier_code"], "SUP-F800")
        self.assertAlmostEqual(values["qty"], 2.0)
        self.assertAlmostEqual(values["cost"], 50.0, places=2)
        self.assertGreater(values["markup"], 0.0)
        self.assertGreater(values["margin"], 0.0)
        self.assertGreater(values["profit_unit"], 0.0)
        self.assertAlmostEqual(values["profit_line"], values["profit_unit"] * 2.0, places=4)
        payload = receive.get_stock_receive_report_payload()
        self.assertEqual(payload["lines"][0]["sku"], "SKU-F800")
        self.assertIn("SKU-F800", payload["lines"][0]["codes"])
        self.assertIn("6001234567890", payload["lines"][0]["codes"])
        self.assertIn("SUP-F800", payload["lines"][0]["codes"])
        html, _report_type = self.env["ir.actions.report"]._render_qweb_html(
            "avea_till.report_avea_stock_receive_document", receive.ids
        )
        self.assertIn(b"SKU-F800", html)
        self.assertIn(b"6001234567890", html)
        self.assertIn(b"SUP-F800", html)
        self.assertIn(b"Markup", html)
        self.assertIn(b"Retail EX (inc)", html)
        self.assertNotIn(b"Retail INC", html)
        self.assertIn(payload["lines"][0]["retail"].encode(), html)
        self.assertIn(payload["lines"][0]["retail_inc"].encode(), html)
        self.assertIn(b"Estimated profit", html)
        mail = self.env["mail.mail"].search(
            [("email_to", "ilike", "owner-report@example.com")],
            order="id desc",
            limit=1,
        )
        self.assertTrue(mail)
        self.assertIn("Stock received", mail.subject)
        self.assertIn("IO-REPORT-1", mail.subject)
        self.assertIn("attached as a PDF", mail.body_html or "")
        self.assertNotIn("SKU-F800", mail.body_html or "")
        self.assertTrue(mail.attachment_ids)
        self.assertTrue(mail.attachment_ids[0].name.lower().endswith(".pdf"))

    def test_report_mentions_price_change_and_kept_cost_difference(self):
        receive = self._create_receive(cost=40.0, qty=1.0, choice="keep")
        receive.action_receive_stock()
        html, _report_type = self.env["ir.actions.report"]._render_qweb_html(
            "avea_till.report_avea_stock_receive_document", receive.ids
        )
        self.assertIn(b"Needs attention", html)
        self.assertIn(b"Current pricing was kept", html)
        self.assertIn("Needs attention", receive._avea_receive_report_body_html())

        line = self._create_receive(
            cost=40.0,
            qty=1.0,
            extra={"invoice_number": "IO-REPORT-2"},
        ).line_ids
        wizard = (
            self.env["avea.stock.receive.pricing.wizard"]
            .with_context(default_line_id=line.id)
            .create({"line_id": line.id})
        )
        wizard.action_update_cost_and_pricing()
        line.receive_id.action_receive_stock()
        changed, _report_type = self.env["ir.actions.report"]._render_qweb_html(
            "avea_till.report_avea_stock_receive_document", line.receive_id.ids
        )
        self.assertIn(b"Price changes", changed)
        self.assertIn(b"Updated cost and retail", changed)
        self.assertIn(b"Markup", changed)

    def test_report_mentions_unmatched_and_total_mismatch(self):
        receive = self._create_receive(
            extra={
                "invoice_number": "IO-REPORT-3",
                "invoice_total": 1.0,
                "unmatched_line_ids": [
                    Command.create(
                        {
                            "description": "Mystery hose",
                            "quantity": 3.0,
                            "price_unit": 12.0,
                            "sku": "HOSE-1",
                            "supplier_code": "SUP-HOSE",
                        }
                    )
                ],
            }
        )
        self.assertTrue(receive.totals_mismatch)
        html, _report_type = self.env["ir.actions.report"]._render_qweb_html(
            "avea_till.report_avea_stock_receive_document", receive.ids
        )
        self.assertIn(b"Needs attention", html)
        self.assertIn(b"Mystery hose", html)
        self.assertIn(b"HOSE-1", html)
        self.assertIn(b"SUP-HOSE", html)
        self.assertIn(b"does not match received total", html)
        self.assertIn("Mystery hose", receive._avea_receive_report_body_html())

    def test_email_failure_does_not_block_receive(self):
        receive = self._create_receive()
        receive.company_id.avea_receipt_sender_email = False
        receive.company_id.email = False
        receive.action_receive_stock()
        self.assertEqual(receive.state, "done")
        self.assertTrue(receive.bill_id)
