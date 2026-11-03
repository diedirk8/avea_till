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

    def test_cannot_delete_platform_pricelist(self):
        platform = self.env["avea.sales.platform"].create(
            {
                "name": "Delete Guard Platform",
                "commission_percent": 5.0,
            }
        )
        with self.assertRaises(UserError):
            platform.pricelist_id.unlink()
