# -*- coding: utf-8 -*-
import ast

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_pricelist_manager")
class TestAveaPricelistManager(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.product = cls.env["product.template"].create(
            {
                "name": "Avea Pricelist Test Kibble",
                "list_price": 120.0,
                "type": "consu",
                "sale_ok": True,
                "available_in_pos": True,
            }
        )
        cls.pos_config = cls.env["pos.config"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        if not cls.pos_config:
            cls.pos_config = cls.env["pos.config"].create(
                {
                    "name": "Test Till",
                    "company_id": cls.company.id,
                }
            )

    def test_manager_excludes_platform_pricelists(self):
        platform = self.env["avea.sales.platform"].create(
            {
                "name": "Test Platform",
                "commission_percent": 10.0,
            }
        )
        action = self.env.ref("avea_till.action_avea_pricelist_manager")
        raw_domain = action.domain or "[]"
        domain = raw_domain if isinstance(raw_domain, list) else ast.literal_eval(raw_domain)
        lists = self.env["product.pricelist"].search(domain)
        self.assertNotIn(platform.pricelist_id, lists)

    def test_fill_from_shelf_and_pos_register(self):
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Staff pricing",
                "company_id": self.company.id,
                "avea_pos_available": True,
            }
        )
        pricelist.action_avea_fill_from_shelf()
        line = pricelist.item_ids.filtered(lambda row: row.product_tmpl_id == self.product)
        self.assertEqual(len(line), 1)
        self.assertEqual(line.fixed_price, 120.0)
        self.assertTrue(self.pos_config.use_pricelist)
        self.assertIn(pricelist, self.pos_config.available_pricelist_ids)

    def test_list_read_includes_customer_count(self):
        partner = self.env["res.partner"].create(
            {
                "name": "Pricelist Customer",
                "property_product_pricelist": self.env["product.pricelist"].create(
                    {"name": "Trade list", "company_id": self.company.id}
                ).id,
            }
        )
        pricelist = partner.property_product_pricelist
        data = self.env["product.pricelist"].web_search_read(
            domain=[("id", "=", pricelist.id)],
            specification={
                "name": {},
                "avea_item_count": {},
                "avea_customer_count": {},
            },
            offset=0,
            limit=1,
            order="",
        )
        row = data["records"][0]
        self.assertGreaterEqual(row["avea_customer_count"], 1)

    def test_formula_rule_counts_and_summarises(self):
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Staff cost plus",
                "company_id": self.company.id,
            }
        )
        self.env["product.pricelist.item"].create(
            {
                "pricelist_id": pricelist.id,
                "applied_on": "3_global",
                "compute_price": "formula",
                "base": "standard_price",
                "price_markup": 24.2,
                "price_round": 1.0,
            }
        )
        pricelist.invalidate_recordset(["avea_item_count", "avea_rule_summary"])
        self.assertEqual(pricelist.avea_item_count, 1)
        self.assertTrue(pricelist.avea_rule_summary)
        self.assertRegex(pricelist.avea_rule_summary, r"24")

    def test_assign_customers_without_leaving_form(self):
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Staff assign",
                "company_id": self.company.id,
            }
        )
        other = self.env["product.pricelist"].create(
            {
                "name": "Other list",
                "company_id": self.company.id,
            }
        )
        keep = self.env["res.partner"].create(
            {
                "name": "Keep on staff",
                "customer_rank": 1,
                "specific_property_product_pricelist": pricelist.id,
            }
        )
        extra = self.env["res.partner"].create(
            {
                "name": "Move onto staff",
                "customer_rank": 1,
                "specific_property_product_pricelist": other.id,
            }
        )
        drop = self.env["res.partner"].create(
            {
                "name": "Remove from staff",
                "customer_rank": 1,
                "specific_property_product_pricelist": pricelist.id,
            }
        )
        pricelist.invalidate_recordset(["avea_customer_ids"])
        pricelist.avea_customer_ids = keep | extra
        self.assertEqual(keep.specific_property_product_pricelist, pricelist)
        self.assertEqual(extra.specific_property_product_pricelist, pricelist)
        self.assertFalse(drop.specific_property_product_pricelist)

    def test_category_exception_overrides_all_products(self):
        category = self.env["product.category"].create({"name": "Bird food"})
        bird = self.env["product.template"].create(
            {
                "name": "Seed mix",
                "list_price": 200.0,
                "standard_price": 100.0,
                "categ_id": category.id,
                "type": "consu",
                "sale_ok": True,
            }
        )
        other = self.product
        other.standard_price = 50.0
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Staff with exception",
                "company_id": self.company.id,
            }
        )
        self.env["product.pricelist.item"].create(
            [
                {
                    "pricelist_id": pricelist.id,
                    "applied_on": "3_global",
                    "compute_price": "formula",
                    "base": "standard_price",
                    "price_markup": 24.2,
                    "price_round": 1.0,
                },
                {
                    "pricelist_id": pricelist.id,
                    "applied_on": "2_product_category",
                    "categ_id": category.id,
                    "compute_price": "formula",
                    "base": "standard_price",
                    "price_markup": 10.0,
                    "price_round": 1.0,
                },
            ]
        )
        bird_price = pricelist._get_product_price(bird.product_variant_id, 1)
        other_price = pricelist._get_product_price(other.product_variant_id, 1)
        self.assertAlmostEqual(bird_price, 110.0, places=1)
        self.assertAlmostEqual(other_price, 62.0, places=1)

    def test_priority_controls_which_rule_applies_first(self):
        category = self.env["product.category"].create({"name": "Toys"})
        toy = self.env["product.template"].create(
            {
                "name": "Chew toy",
                "list_price": 80.0,
                "standard_price": 40.0,
                "categ_id": category.id,
                "type": "consu",
                "sale_ok": True,
            }
        )
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Priority test",
                "company_id": self.company.id,
            }
        )
        self.env["product.pricelist.item"].create(
            [
                {
                    "pricelist_id": pricelist.id,
                    "applied_on": "3_global",
                    "compute_price": "formula",
                    "base": "standard_price",
                    "price_markup": 50.0,
                    "avea_priority": 1,
                },
                {
                    "pricelist_id": pricelist.id,
                    "applied_on": "2_product_category",
                    "categ_id": category.id,
                    "compute_price": "formula",
                    "base": "standard_price",
                    "price_markup": 10.0,
                    "avea_priority": 9,
                },
            ]
        )
        price = pricelist._get_product_price(toy.product_variant_id, 1)
        self.assertAlmostEqual(price, 60.0, places=1)

    def test_how_and_amount_map_to_odoo_fields(self):
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "How amount map",
                "company_id": self.company.id,
            }
        )
        item = self.env["product.pricelist.item"].create(
            {
                "pricelist_id": pricelist.id,
                "applied_on": "3_global",
                "compute_price": "formula",
                "base": "standard_price",
                "price_markup": 24.2,
            }
        )
        self.assertEqual(item.avea_method, "cost_plus")
        self.assertAlmostEqual(item.avea_amount, 24.2, places=2)
        self.assertIn("24.2", item.avea_result)
        self.assertIn("cost", item.avea_result.lower())

        item.write({"avea_method": "off_sales", "avea_amount": 20.0})
        item.invalidate_recordset()
        self.assertEqual(item.compute_price, "percentage")
        self.assertAlmostEqual(item.percent_price, 20.0, places=2)
        self.assertEqual(item.avea_method, "off_sales")
        self.assertRegex(item.avea_result, r"20(\.0+)?%\s+off")
        self.assertIn("shelf", item.avea_result.lower())

    def test_create_sets_default_level_from_applies_to(self):
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Default levels",
                "company_id": self.company.id,
            }
        )
        global_item, category_item = self.env["product.pricelist.item"].create(
            [
                {
                    "pricelist_id": pricelist.id,
                    "applied_on": "3_global",
                    "compute_price": "formula",
                    "base": "standard_price",
                    "price_markup": 24.2,
                },
                {
                    "pricelist_id": pricelist.id,
                    "applied_on": "2_product_category",
                    "categ_id": self.env["product.category"].create({"name": "Default cat"}).id,
                    "compute_price": "percentage",
                    "percent_price": 20.0,
                },
            ]
        )
        self.assertEqual(global_item.avea_priority, 10)
        self.assertEqual(category_item.avea_priority, 3)

    def test_view_prices_shows_computed_list_and_rule(self):
        category = self.env["product.category"].create({"name": "Bird food"})
        bird = self.env["product.template"].create(
            {
                "name": "Seed mix",
                "list_price": 200.0,
                "standard_price": 100.0,
                "categ_id": category.id,
                "type": "consu",
                "sale_ok": True,
            }
        )
        other = self.product
        other.standard_price = 50.0
        other.list_price = 120.0
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Staff preview",
                "company_id": self.company.id,
            }
        )
        self.env["product.pricelist.item"].create(
            [
                {
                    "pricelist_id": pricelist.id,
                    "applied_on": "3_global",
                    "compute_price": "formula",
                    "base": "standard_price",
                    "price_markup": 24.2,
                    "avea_priority": 10,
                },
                {
                    "pricelist_id": pricelist.id,
                    "applied_on": "2_product_category",
                    "categ_id": category.id,
                    "compute_price": "percentage",
                    "percent_price": 20.0,
                    "avea_priority": 3,
                },
            ]
        )
        bird_row = bird.with_context(avea_pricelist_id=pricelist.id)
        other_row = other.with_context(avea_pricelist_id=pricelist.id)
        self.assertAlmostEqual(
            bird_row.avea_pricelist_preview_price,
            pricelist._get_product_price(bird.product_variant_id, 1),
            places=2,
        )
        self.assertAlmostEqual(
            other_row.avea_pricelist_preview_price,
            pricelist._get_product_price(other.product_variant_id, 1),
            places=2,
        )
        self.assertAlmostEqual(other_row.avea_pricelist_preview_shelf, 120.0, places=1)
        self.assertAlmostEqual(other_row.avea_pricelist_preview_cost, 50.0, places=1)
        self.assertIn("Bird food", bird_row.avea_pricelist_preview_rule)
        self.assertRegex(bird_row.avea_pricelist_preview_rule, r"20(\.0+)?%")
        self.assertIn("All products", other_row.avea_pricelist_preview_rule)
        self.assertIn("cost", other_row.avea_pricelist_preview_rule.lower())

        action = pricelist.action_avea_view_prices()
        self.assertEqual(action["res_model"], "product.template")
        self.assertEqual(action["context"]["avea_pricelist_id"], pricelist.id)
        self.assertIn(("sale_ok", "=", True), action["domain"])
        self.assertIn(bird, self.env["product.template"].search(action["domain"]))

    def test_cannot_delete_platform_pricelist(self):
        platform = self.env["avea.sales.platform"].create(
            {
                "name": "Delete Guard Platform",
                "commission_percent": 5.0,
            }
        )
        with self.assertRaises(UserError):
            platform.pricelist_id.unlink()
