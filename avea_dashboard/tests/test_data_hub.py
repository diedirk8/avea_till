# -*- coding: utf-8 -*-
import base64
import io
from datetime import timedelta

import xlsxwriter
from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from unittest import SkipTest


def _xlsx_bytes(headers, rows):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    sheet = workbook.add_worksheet("Data")
    for col, header in enumerate(headers):
        sheet.write(0, col, header)
    for row_index, row in enumerate(rows, start=1):
        for col, value in enumerate(row):
            sheet.write(row_index, col, value)
    workbook.close()
    return output.getvalue()


@tagged("post_install", "-at_install", "avea_till")
class TestAveaDataHub(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.product = cls.env["product.template"].create(
            {
                "name": "Data Hub Kibble",
                "default_code": "DH-KIBBLE",
                "barcode": "6009709471111",
                "type": "consu",
                "is_storable": True,
                "sale_ok": True,
                "purchase_ok": True,
                "available_in_pos": True,
                "list_price": 120.0,
                "standard_price": 70.0,
                "avea_cost_ex_tax": 70.0,
                "company_id": cls.company.id,
            }
        )
        cls.customer = cls.env["res.partner"].create(
            {
                "name": "Data Hub Customer",
                "email": "datahub.customer@example.com",
                "phone": "0115550100",
                "customer_rank": 1,
                "company_id": cls.company.id,
            }
        )
        cls.supplier = cls.env["res.partner"].create(
            {
                "name": "Data Hub Supplier",
                "email": "datahub.supplier@example.com",
                "supplier_rank": 1,
                "company_id": cls.company.id,
            }
        )

    def _hub(self):
        return self.env["avea.data.hub"].create({"company_id": self.company.id})

    def _import(self, data_type, raw, filename="data.xlsx"):
        wizard = self.env["avea.data.import"].create(
            {
                "data_type": data_type,
                "spreadsheet": base64.b64encode(raw).decode(),
                "spreadsheet_filename": filename,
            }
        )
        wizard.action_preview()
        return wizard

    def test_lists_expose_avea_import_export(self):
        products = self.env.ref("avea_till.view_avea_stock_product_list").arch_db or ""
        self.assertIn('name="action_avea_import_products"', products)
        self.assertIn('name="action_avea_export_products"', products)
        customers = self.env.ref("avea_till.view_avea_customer_list").arch_db or ""
        self.assertIn('name="action_avea_import_customers"', customers)
        suppliers = self.env.ref("avea_till.view_avea_supplier_list").arch_db or ""
        self.assertIn('name="action_avea_import_suppliers"', suppliers)
        hub = self.env.ref("avea_till.view_avea_data_hub_form").arch_db or ""
        self.assertIn('name="action_import_opening_stock"', hub)
        self.assertIn('name="action_export_sales"', hub)

    def test_settings_data_is_in_manager_nav(self):
        manager = self.env["res.users"].create(
            {
                "name": "Data Hub Manager",
                "login": "avea_data_hub_mgr@dev.local",
                "company_id": self.company.id,
                "company_ids": [Command.set([self.company.id])],
                "group_ids": [Command.set([self.env.ref("avea_till.group_avea_manager").id])],
            }
        )
        nav = manager._avea_nav_structure()
        labels = [item["label"] for item in nav["settings"]["items"]]
        self.assertIn("Data", labels)

    def test_export_products_includes_sku(self):
        headers, rows, slug, sheet = self._hub()._export_products()
        self.assertEqual(sheet, "Products")
        self.assertIn("SKU", headers)
        skus = [row[0] for row in rows]
        self.assertIn("DH-KIBBLE", skus)

    def test_export_selected_products_only(self):
        self.env["product.template"].create(
            {
                "name": "Data Hub Other",
                "default_code": "DH-OTHER",
                "type": "consu",
                "sale_ok": True,
                "list_price": 10.0,
                "company_id": self.company.id,
            }
        )
        _headers, rows, _slug, _sheet = self._hub()._export_products(templates=self.product)
        skus = [row[0] for row in rows]
        self.assertEqual(skus, ["DH-KIBBLE"])
        action = self.env["product.template"].action_avea_export_products(
            product_ids=self.product.ids
        )
        self.assertEqual(action["type"], "ir.actions.act_url")
        with self.assertRaises(UserError):
            self._hub()._download_product_records(self.env["product.template"])

    def test_export_customers_and_suppliers_are_separate(self):
        _headers, customer_rows, _, _ = self._hub()._export_customers()
        names = [row[0] for row in customer_rows]
        self.assertIn("Data Hub Customer", names)
        self.assertNotIn("Data Hub Supplier", names)
        _headers, supplier_rows, _, _ = self._hub()._export_suppliers()
        supplier_names = [row[0] for row in supplier_rows]
        self.assertIn("Data Hub Supplier", supplier_names)
        self.assertNotIn("Data Hub Customer", supplier_names)

    def test_import_products_creates_and_updates(self):
        raw = _xlsx_bytes(
            ["SKU", "Name", "Cost EX VAT", "Retail INC VAT", "Sell on POS", "Track stock"],
            [
                ["DH-KIBBLE", "Data Hub Kibble Updated", 75.5, 129.0, "yes", "yes"],
                ["DH-NEW", "Data Hub New Treats", 20.0, 45.0, "yes", "yes"],
            ],
        )
        wizard = self._import("products", raw)
        self.assertEqual(wizard.update_count, 1)
        self.assertEqual(wizard.create_count, 1)
        wizard.action_apply()
        self.product.invalidate_recordset()
        self.assertEqual(self.product.name, "Data Hub Kibble Updated")
        self.assertAlmostEqual(self.product.avea_cost_ex_tax, 75.5, places=3)
        created = self.env["product.template"].search([("default_code", "=", "DH-NEW")], limit=1)
        self.assertTrue(created)
        self.assertEqual(created.name, "Data Hub New Treats")
        self.assertTrue(created.available_in_pos)

    def test_duplicate_sku_in_file_is_an_error(self):
        raw = _xlsx_bytes(
            ["SKU", "Name"],
            [["DH-DUP", "First"], ["DH-DUP", "Second"]],
        )
        wizard = self._import("products", raw)
        self.assertEqual(wizard.error_count, 1)
        self.assertEqual(wizard.create_count, 1)

    def test_import_customers_matches_email(self):
        raw = _xlsx_bytes(
            ["Name", "Email", "Phone", "City"],
            [
                ["Data Hub Customer", "datahub.customer@example.com", "0115550199", "Pretoria"],
                ["Brand New Walker", "walker@example.com", "0820001111", "Durban"],
            ],
        )
        wizard = self._import("customers", raw)
        wizard.action_apply()
        self.customer.invalidate_recordset()
        self.assertEqual(self.customer.city, "Pretoria")
        self.assertEqual(self.customer.phone, "0115550199")
        created = self.env["res.partner"].search([("email", "=", "walker@example.com")], limit=1)
        self.assertTrue(created)
        self.assertGreaterEqual(created.customer_rank, 1)

    def test_import_suppliers_matches_name(self):
        raw = _xlsx_bytes(
            ["Name", "VAT"],
            [["Data Hub Supplier", "4123456789"]],
        )
        wizard = self._import("suppliers", raw)
        wizard.action_apply()
        self.supplier.invalidate_recordset()
        self.assertEqual(self.supplier.vat, "4123456789")

    def test_opening_stock_creates_review_stock_take(self):
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.company.id)], limit=1
        )
        if not warehouse:
            raise SkipTest("Warehouse required for opening stock import.")
        raw = _xlsx_bytes(
            ["SKU", "Qty"],
            [["DH-KIBBLE", 17]],
        )
        wizard = self._import("opening_stock", raw)
        self.assertEqual(wizard.update_count, 1)
        action = wizard.action_apply()
        self.assertEqual(action["tag"], "avea_stock_take")
        take = self.env["avea.stock.take"].browse(action["params"]["stock_take_id"])
        self.assertEqual(take.state, "review")
        line = take.line_ids.filtered(lambda row: row.product_id.default_code == "DH-KIBBLE")
        self.assertEqual(len(line), 1)
        self.assertAlmostEqual(line.counted_qty, 17.0, places=2)
        self.assertTrue(line.is_counted)

    def test_sales_export_rejects_inverted_dates(self):
        hub = self._hub()
        hub.date_from = fields.Date.today()
        hub.date_to = fields.Date.today() - timedelta(days=3)
        with self.assertRaises(UserError):
            hub._export_sales()

    def test_sales_and_transaction_export_have_headers(self):
        headers, rows, _slug, sheet = self._hub()._export_sales()
        self.assertEqual(sheet, "Sales")
        self.assertIn("Order", headers)
        self.assertIsInstance(rows, list)
        txn_headers, _rows, _slug, txn_sheet = self._hub()._export_transactions()
        self.assertEqual(txn_sheet, "Transactions")
        self.assertIn("Reference", txn_headers)

    def test_download_template_and_export_return_files(self):
        action = self._hub().action_export_products()
        self.assertEqual(action["type"], "ir.actions.act_url")
        wizard = self.env["avea.data.import"].create({"data_type": "products"})
        template = wizard.action_download_template()
        self.assertEqual(template["type"], "ir.actions.act_url")
