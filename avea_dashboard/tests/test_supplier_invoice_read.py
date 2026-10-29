# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.avea_till.models.stock.supplier_invoice_reader import (
    AveaSupplierInvoiceReader,
)


INCLUSIVE = """
Tax Invoice INV100
Invoice date: 28/10/2026
Prices include VAT
2 Zzqx Phantom Pellet 9kg 115.00 230.00
"""

EXCLUSIVE = """
Supplier Invoice INV200
Date: 2026-10-28
Prices exclude VAT
PE-ABC123 Avea Invoice Match Kibble 2 50.00 100.00
Unknown Grooming Brush 1 30.00 30.00
VAT 15% 19.50
Total 149.50
"""


@tagged("post_install", "-at_install", "avea_invoice_read")
class TestSupplierInvoiceRead(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {
                "name": "Avea Invoice Match Kibble",
                "default_code": "PE-ABC123",
                "type": "consu",
                "is_storable": True,
                "purchase_ok": True,
                "sale_ok": True,
                "list_price": 80.0,
                "standard_price": 40.0,
            }
        )

    def test_parse_vat_and_skip_totals(self):
        parsed = AveaSupplierInvoiceReader.parse_text(EXCLUSIVE)
        self.assertEqual(parsed["vat_mode"], "exclusive")
        self.assertEqual(parsed["invoice_number"], "INV200")
        self.assertEqual(len(parsed["lines"]), 2)
        self.assertEqual(parsed["lines"][0]["codes"], ["PE-ABC123"])
        self.assertEqual(parsed["lines"][0]["quantity"], 2.0)
        self.assertEqual(parsed["lines"][0]["unit_price"], 50.0)
        self.assertNotIn("vat", parsed["lines"][1]["description"].lower())

    def test_inclusive_prices_become_ex_tax(self):
        parsed = AveaSupplierInvoiceReader.parse_text(INCLUSIVE)
        self.assertEqual(parsed["vat_mode"], "inclusive")
        receive = self.env["avea.stock.receive"].create({})
        receive._avea_apply_invoice_reading(parsed)
        self.assertFalse(receive.line_ids)
        self.assertEqual(len(receive.unmatched_line_ids), 1)
        self.assertAlmostEqual(receive.unmatched_line_ids.price_unit, 100.0, places=2)

    def test_sku_match_and_unknown_line(self):
        parsed = AveaSupplierInvoiceReader.parse_text(EXCLUSIVE)
        receive = self.env["avea.stock.receive"].create({})
        receive._avea_apply_invoice_reading(parsed)
        self.assertEqual(receive.line_ids.product_id, self.product)
        self.assertEqual(receive.line_ids.quantity, 2.0)
        self.assertEqual(receive.line_ids.price_unit, 50.0)
        self.assertEqual(len(receive.unmatched_line_ids), 1)
        self.assertIn("Brush", receive.unmatched_line_ids.description)
        self.assertIn("Matched 1.", receive.invoice_read_summary)
        self.assertIn("Not found 1.", receive.invoice_read_summary)

    def test_read_uploaded_text_invoice(self):
        receive = self.env["avea.stock.receive"].create({})
        receive.write(
            {
                "invoice_document_filename": "invoice.txt",
                "invoice_document": __import__("base64")
                .b64encode(EXCLUSIVE.encode())
                .decode(),
            }
        )
        receive.action_read_supplier_invoice()
        self.assertEqual(receive.invoice_number, "INV200")
        self.assertEqual(receive.line_ids.product_id, self.product)
        self.assertTrue(receive.unmatched_line_ids)

    def test_refuses_to_replace_existing_lines(self):
        receive = self.env["avea.stock.receive"].create(
            {
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "quantity": 1,
                            "price_unit": 10,
                        },
                    )
                ]
            }
        )
        with self.assertRaises(Exception):
            receive.action_read_supplier_invoice()
