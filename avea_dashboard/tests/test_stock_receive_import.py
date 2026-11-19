# -*- coding: utf-8 -*-
import base64
import io

import xlsxwriter
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


def _xlsx_bytes(headers, rows):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    sheet = workbook.add_worksheet("Products")
    for col, header in enumerate(headers):
        sheet.write(0, col, header)
    for row_index, row in enumerate(rows, start=1):
        for col, value in enumerate(row):
            sheet.write(row_index, col, value)
    workbook.close()
    return output.getvalue()


@tagged("post_install", "-at_install", "avea_till")
class TestStockReceiveImport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {
                "name": "Zzqx Import Kibble 2kg",
                "default_code": "ZZQX-IMP-2KG",
                "type": "consu",
                "is_storable": True,
                "purchase_ok": True,
                "sale_ok": True,
                "list_price": 250.0,
                "standard_price": 180.0,
            }
        )
        cls.receive = cls.env["avea.stock.receive"].create({})

    def _wizard(self, raw, filename="products.xlsx"):
        return self.env["avea.stock.receive.import"].create(
            {
                "receive_id": self.receive.id,
                "spreadsheet": base64.b64encode(raw).decode(),
                "spreadsheet_filename": filename,
            }
        )

    def test_upload_invoice_does_not_fill_lines(self):
        self.receive.write(
            {
                "invoice_document_filename": "invoice.txt",
                "invoice_document": base64.b64encode(b"Tax Invoice INV9").decode(),
            }
        )
        self.assertFalse(self.receive.line_ids)
        self.assertFalse(self.receive.unmatched_line_ids)
        self.assertFalse(
            hasattr(type(self.receive), "_onchange_invoice_document")
        )

    def test_import_matches_sku_and_discount(self):
        raw = _xlsx_bytes(
            ["Product", "SKU", "Qty", "Excl Tax Cost", "Discount %"],
            [["Zzqx Import Kibble 2kg", "ZZQX-IMP-2KG", 6, 185.0, 5]],
        )
        self._wizard(raw).action_import()
        line = self.receive.line_ids
        self.assertEqual(line.product_id, self.product)
        self.assertEqual(line.quantity, 6.0)
        self.assertAlmostEqual(line.price_unit, 185.0, places=2)
        self.assertAlmostEqual(line.discount, 5.0, places=2)
        self.assertFalse(self.receive.unmatched_line_ids)

    def test_import_unknown_row_gets_closest_match(self):
        raw = _xlsx_bytes(
            ["Product", "SKU", "Qty", "Excl Tax Cost", "Discount %"],
            [["Zzqx Import Kibble 8kg extra", "", 2, 40.0, 0]],
        )
        self._wizard(raw).action_import()
        self.assertFalse(self.receive.line_ids)
        unmatched = self.receive.unmatched_line_ids
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(unmatched.product_id, self.product)
        unmatched.action_add_to_receive()
        self.assertEqual(self.receive.line_ids.product_id, self.product)
        self.assertEqual(self.receive.line_ids.quantity, 2.0)
        self.assertFalse(self.receive.unmatched_line_ids)

    def test_create_product_from_unmatched(self):
        unmatched = self.env["avea.stock.receive.unmatched"].create(
            {
                "receive_id": self.receive.id,
                "description": "Zzqx Brand New Treat 200g",
                "quantity": 4,
                "price_unit": 22.5,
                "discount": 10,
                "supplier_code": "ABT-200",
            }
        )
        action = unmatched.action_create_product()
        self.assertEqual(action["res_model"], "product.template")
        self.assertEqual(action["target"], "new")
        context = action["context"]
        self.assertEqual(context["avea_return_unmatched_id"], unmatched.id)
        self.assertEqual(context["default_name"], "Zzqx Brand New Treat 200g")
        self.assertEqual(context["default_default_code"], "ABT-200")
        product = (
            self.env["product.template"]
            .with_context(**context)
            .create(
                {
                    "name": context["default_name"],
                    "default_code": context["default_default_code"],
                    "avea_cost_ex_tax": 22.5,
                    "type": "consu",
                    "is_storable": True,
                    "purchase_ok": True,
                    "sale_ok": True,
                }
            )
        )
        product.with_context(**context).action_avea_save_and_return_receive()
        line = self.receive.line_ids
        self.assertEqual(line.product_id, product.product_variant_id)
        self.assertEqual(line.quantity, 4.0)
        self.assertAlmostEqual(line.price_unit, 22.5, places=2)
        self.assertAlmostEqual(line.discount, 10.0, places=2)
        self.assertFalse(unmatched.exists())

    def test_csv_import_uses_template_headers(self):
        csv_text = (
            "Product,SKU,Qty,Excl Tax Cost,Discount %\n"
            "Something else,ZZQX-IMP-2KG,1,99.5,0\n"
        )
        self._wizard(csv_text.encode(), filename="products.csv").action_import()
        self.assertEqual(self.receive.line_ids.product_id, self.product)
        self.assertAlmostEqual(self.receive.line_ids.price_unit, 99.5, places=2)

    def test_download_template_is_excel(self):
        wizard = self.env["avea.stock.receive.import"].create(
            {"receive_id": self.receive.id}
        )
        action = wizard.action_download_template()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertIn("download=true", action["url"])
