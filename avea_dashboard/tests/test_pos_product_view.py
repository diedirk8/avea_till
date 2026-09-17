# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestPosProductViewSettings(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config

    def test_pos_product_view_defaults(self):
        self.assertEqual(self.config.avea_product_layout, "list")
        self.assertTrue(self.config.avea_show_product_code)
        self.assertTrue(self.config.avea_show_stock_quantity)
        self.assertTrue(self.config.avea_show_stock_status)
        self.assertEqual(self.config.avea_products_per_page, "50")

    def test_product_template_pos_fields_include_stock(self):
        fields_list = self.env["product.template"]._load_pos_data_fields(self.config)
        self.assertIn("avea_stock_qty", fields_list)
        self.assertIn("avea_stock_status", fields_list)

    def test_pos_config_has_nav_category_field(self):
        self.assertIn("avea_nav_category_ids", self.config._fields)
