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

    def test_cannot_delete_platform_pricelist(self):
        platform = self.env["avea.sales.platform"].create(
            {
                "name": "Delete Guard Platform",
                "commission_percent": 5.0,
            }
        )
        with self.assertRaises(UserError):
            platform.pricelist_id.unlink()
