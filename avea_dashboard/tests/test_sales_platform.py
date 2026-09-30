# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools.float_utils import float_compare


@tagged("post_install", "-at_install", "avea_till")
class TestAveaSalesPlatform(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.category = cls.env["product.category"].create({"name": "Platform Test Cat"})
        cls.template = cls.env["product.template"].create(
            {
                "name": "Platform Test Product",
                "list_price": 100.0,
                "categ_id": cls.category.id,
                "sale_ok": True,
                "is_storable": True,
            }
        )

    def _create_platform(self, **kwargs):
        vals = {
            "name": "Test Platform",
            "commission_percent": 10.0,
            "commission_vat": False,
            "price_rounding_rule": "none",
        }
        vals.update(kwargs)
        return self.env["avea.sales.platform"].create(vals)

    def test_create_links_partner_and_pricelist(self):
        platform = self._create_platform(name="Mr D Test")
        self.assertTrue(platform.partner_id)
        self.assertEqual(platform.partner_id.customer_rank, 1)
        self.assertTrue(platform.pricelist_id)
        self.assertEqual(platform.pricelist_id.avea_sales_platform_id, platform)
        self.assertEqual(platform.pricelist_id.company_id, self.company)

    def test_platform_price_gross_up_without_vat(self):
        platform = self._create_platform(commission_percent=10.0, commission_vat=False, price_rounding_rule="none")
        price = platform._avea_platform_price_from_retail(100.0)
        self.assertEqual(float_compare(price, 111.11, precision_digits=2), 0)

    def test_platform_price_rounding_nearest_9(self):
        platform = self._create_platform(commission_percent=10.0, commission_vat=False, price_rounding_rule="nearest_9")
        price = platform._avea_platform_price_from_retail(100.0)
        self.assertEqual(price, 109.0)

    def test_update_platform_prices_does_not_change_retail(self):
        platform = self._create_platform(commission_percent=10.0, commission_vat=False, price_rounding_rule="none")
        retail_before = self.template.list_price
        platform.action_update_platform_prices()
        self.assertEqual(self.template.list_price, retail_before)
        item = self.env["product.pricelist.item"].search(
            [
                ("pricelist_id", "=", platform.pricelist_id.id),
                ("product_tmpl_id", "=", self.template.id),
            ],
            limit=1,
        )
        self.assertTrue(item)
        self.assertEqual(float_compare(item.fixed_price, 111.11, precision_digits=2), 0)

    def test_update_platform_prices_upserts_without_duplicates(self):
        platform = self._create_platform(price_rounding_rule="none")
        platform.action_update_platform_prices()
        platform.action_update_platform_prices()
        items = self.env["product.pricelist.item"].search(
            [
                ("pricelist_id", "=", platform.pricelist_id.id),
                ("product_tmpl_id", "=", self.template.id),
            ]
        )
        self.assertEqual(len(items), 1)

    def test_mr_d_seed_record(self):
        mr_d = self.env.ref("avea_till.sales_platform_mr_d", raise_if_not_found=False)
        if not mr_d:
            self.skipTest("Mr D platform data not installed on this database.")
        self.assertEqual(mr_d.commission_percent, 10.0)
        self.assertTrue(mr_d.commission_vat)
        self.assertTrue(mr_d.partner_id)
        self.assertTrue(mr_d.pricelist_id)
