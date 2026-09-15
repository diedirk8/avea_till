# -*- coding: utf-8 -*-
from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from unittest import SkipTest


@tagged("post_install", "-at_install", "avea_stock")
class TestAveaStockTake(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        if not cls.warehouse:
            raise SkipTest("Warehouse required for stock take tests.")
        cls.location = cls.warehouse.lot_stock_id
        cls.supplier = cls.env["res.partner"].create(
            {
                "name": "Stock Take Supplier",
                "supplier_rank": 1,
                "company_id": cls.company.id,
            }
        )
        cls.category_a = cls.env["product.category"].create({"name": "Stock Take Birds"})
        cls.category_b = cls.env["product.category"].create({"name": "Stock Take Cats"})
        cls.product_a = cls._create_product("Stock Take Product A", cls.category_a, supplier=cls.supplier)
        cls.product_b = cls._create_product("Stock Take Product B", cls.category_a, supplier=cls.supplier)
        cls.product_c = cls._create_product("Stock Take Product C", cls.category_b)
        cls.outside_product = cls._create_product("Stock Take Outside Product", cls.category_b)

    @classmethod
    def _create_product(cls, name, category, supplier=None):
        template_vals = {
            "name": name,
            "type": "consu",
            "is_storable": True,
            "sale_ok": True,
            "purchase_ok": True,
            "categ_id": category.id,
            "company_id": cls.company.id,
        }
        if supplier:
            template_vals["avea_supplier_id"] = supplier.id
        product = cls.env["product.product"].create(
            {
                "name": name,
                "type": "consu",
                "is_storable": True,
                "sale_ok": True,
                "purchase_ok": True,
                "categ_id": category.id,
                "company_id": cls.company.id,
            }
        )
        if supplier:
            product.product_tmpl_id.avea_supplier_id = supplier
        return product

    def _set_qty(self, product, qty):
        self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "product_id": product.id,
                "location_id": self.location.id,
                "inventory_quantity": qty,
            }
        ).action_apply_inventory()
        product.invalidate_recordset()

    def _create_take(self, **values):
        defaults = {
            "company_id": self.company.id,
            "location_id": self.location.id,
            "scope_mode": "partial",
            "counting_mode": "review",
        }
        defaults.update(values)
        stock_take = self.env["avea.stock.take"].create(defaults)
        stock_take._avea_populate_lines()
        stock_take.state = "counting"
        return stock_take

    def _qty(self, product):
        return product.with_context(location=self.location.id).qty_available

    def test_full_stock_take_counts_and_applies(self):
        self._set_qty(self.product_a, 10.0)
        self._set_qty(self.product_b, 6.0)
        stock_take = self._create_take(
            manual_product_ids=[Command.set([self.product_a.id, self.product_b.id])],
            counting_mode="review",
        )
        line_a = stock_take.line_ids.filtered(lambda line: line.product_id == self.product_a)
        line_b = stock_take.line_ids.filtered(lambda line: line.product_id == self.product_b)
        self.assertTrue(line_a and line_b)
        line_a._avea_set_counted_qty(8.0)
        line_b._avea_set_counted_qty(6.0)
        stock_take.action_prepare_review()
        stock_take.action_apply_stock_take()
        self.assertEqual(stock_take.state, "applied")
        self.assertAlmostEqual(self._qty(self.product_a), 8.0, places=2)
        self.assertAlmostEqual(self._qty(self.product_b), 6.0, places=2)

    def test_partial_supplier_filter_only_adjusts_included_products(self):
        self._set_qty(self.product_a, 5.0)
        self._set_qty(self.product_b, 7.0)
        self._set_qty(self.outside_product, 4.0)
        stock_take = self._create_take(
            filter_supplier_id=self.supplier.id,
            counting_mode="review",
        )
        lines = stock_take.line_ids
        self.assertEqual(set(lines.mapped("product_id").ids), {self.product_a.id, self.product_b.id})
        for line in lines:
            line._avea_set_counted_qty(line.expected_qty - 1.0)
        stock_take.action_prepare_review()
        stock_take.action_apply_stock_take()
        self.assertAlmostEqual(self._qty(self.outside_product), 4.0, places=2)

    def test_category_filtered_stock_take(self):
        self._set_qty(self.product_c, 3.0)
        stock_take = self._create_take(filter_category_id=self.category_b.id)
        self.assertIn(self.product_c, stock_take.line_ids.mapped("product_id"))
        self.assertNotIn(self.product_a, stock_take.line_ids.mapped("product_id"))
        line = stock_take.line_ids.filtered(lambda item: item.product_id == self.product_c)
        self.assertEqual(len(line), 1)
        for item in stock_take.line_ids:
            item._avea_set_counted_qty(5.0 if item.product_id == self.product_c else item.expected_qty)
        stock_take.action_prepare_review()
        stock_take.action_apply_stock_take()
        self.assertAlmostEqual(self._qty(self.product_c), 5.0, places=2)

    def test_manual_selection_stock_take(self):
        self._set_qty(self.product_a, 2.0)
        stock_take = self._create_take(
            manual_product_ids=[Command.set([self.product_a.id])],
        )
        self.assertEqual(len(stock_take.line_ids), 1)
        stock_take.line_ids._avea_set_counted_qty(9.0)
        stock_take.action_prepare_review()
        stock_take.action_apply_stock_take()
        self.assertAlmostEqual(self._qty(self.product_a), 9.0, places=2)

    def test_incomplete_stock_take_cannot_be_applied(self):
        stock_take = self._create_take(manual_product_ids=[Command.set([self.product_a.id, self.product_b.id])])
        stock_take.line_ids[0]._avea_set_counted_qty(1.0)
        with self.assertRaises(UserError):
            stock_take.action_prepare_review()
        with self.assertRaises(UserError):
            stock_take.action_apply_stock_take()

    def test_immediate_mode_updates_one_product_at_a_time(self):
        self._set_qty(self.product_a, 12.0)
        self._set_qty(self.product_b, 4.0)
        stock_take = self._create_take(
            manual_product_ids=[Command.set([self.product_a.id, self.product_b.id])],
            counting_mode="immediate",
        )
        line_a = stock_take.line_ids.filtered(lambda line: line.product_id == self.product_a)
        stock_take.action_record_count(line_a.id, 10.0)
        self.assertAlmostEqual(self._qty(self.product_a), 10.0, places=2)
        self.assertAlmostEqual(self._qty(self.product_b), 4.0, places=2)
        self.assertTrue(line_a.is_applied)
        self.assertEqual(stock_take.state, "counting")

    def test_cannot_apply_twice(self):
        stock_take = self._create_take(manual_product_ids=[Command.set([self.product_a.id])])
        stock_take.line_ids._avea_set_counted_qty(1.0)
        stock_take.action_prepare_review()
        stock_take.action_apply_stock_take()
        with self.assertRaises(UserError):
            stock_take.action_apply_stock_take()

    def test_cancel_stock_take(self):
        stock_take = self._create_take(manual_product_ids=[Command.set([self.product_a.id])])
        stock_take.line_ids._avea_set_counted_qty(3.0)
        action = stock_take.action_cancel_stock_take()
        self.assertEqual(stock_take.state, "cancelled")
        self.assertEqual(action["tag"], "avea_stock_take")
        self.assertFalse(action["params"]["stock_take_id"])

    def test_resume_draft_for_user(self):
        stock_take = self.env["avea.stock.take"].create(
            {
                "scope_mode": "everything",
                "counting_mode": "review",
                "company_id": self.company.id,
                "location_id": self.location.id,
                "user_id": self.env.user.id,
                "state": "counting",
            }
        )
        action = self.env["avea.stock.take"].action_open_stock_take()
        self.assertEqual(action["tag"], "avea_stock_take")
        self.assertEqual(action["params"]["stock_take_id"], stock_take.id)

    def test_search_products_for_selection_filters(self):
        result = self.env["avea.stock.take"].search_products_for_selection(
            {
                "scope_mode": "partial",
                "filter_category_id": self.category_a.id,
            }
        )
        product_ids = {row["id"] for row in result["products"]}
        self.assertEqual(result["count"], 2)
        self.assertEqual(product_ids, {self.product_a.id, self.product_b.id})
        self.assertIn("category_name", result["products"][0])
        self.assertIn("qty_available", result["products"][0])

    def test_partial_without_products_cannot_start(self):
        stock_take = self.env["avea.stock.take"].create(
            {
                "scope_mode": "partial",
                "counting_mode": "review",
                "company_id": self.company.id,
                "location_id": self.location.id,
            }
        )
        with self.assertRaises(UserError):
            stock_take.action_start_counting()

    def test_partial_manual_selection_without_filters_can_start(self):
        stock_take = self.env["avea.stock.take"].create(
            {
                "scope_mode": "partial",
                "counting_mode": "review",
                "company_id": self.company.id,
                "location_id": self.location.id,
                "manual_product_ids": [Command.set([self.product_a.id, self.product_b.id])],
            }
        )
        stock_take.action_start_counting()
        self.assertEqual(len(stock_take.line_ids), 2)

    def test_preview_count_uses_manual_selection(self):
        result = self.env["avea.stock.take"].preview_product_count(
            {
                "scope_mode": "partial",
                "manual_product_ids": [Command.set([self.product_a.id, self.product_b.id])],
            }
        )
        self.assertEqual(result["count"], 2)

    def test_positive_negative_and_zero_variance(self):
        self._set_qty(self.product_a, 10.0)
        self._set_qty(self.product_b, 0.0)
        stock_take = self._create_take(
            manual_product_ids=[Command.set([self.product_a.id, self.product_b.id])],
        )
        line_a = stock_take.line_ids.filtered(lambda line: line.product_id == self.product_a)
        line_b = stock_take.line_ids.filtered(lambda line: line.product_id == self.product_b)
        line_a._avea_set_counted_qty(12.0)
        line_b._avea_set_counted_qty(0.0)
        stock_take.action_prepare_review()
        self.assertAlmostEqual(line_a.difference_qty, 2.0, places=2)
        self.assertAlmostEqual(line_b.difference_qty, 0.0, places=2)
        stock_take.action_apply_stock_take()
        self.assertAlmostEqual(self._qty(self.product_a), 12.0, places=2)
        self.assertAlmostEqual(self._qty(self.product_b), 0.0, places=2)
