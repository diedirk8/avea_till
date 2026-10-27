# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_till")
class TestAveaStockCatalogueBulk(TransactionCase):
    def test_bulk_archive_and_restore(self):
        templates = self.env["product.template"].create(
            [
                {"name": "Bulk A", "sale_ok": True, "is_storable": True},
                {"name": "Bulk B", "sale_ok": True, "is_storable": True},
            ]
        )
        templates.action_avea_bulk_archive()
        self.assertFalse(any(templates.mapped("active")))
        templates.action_avea_bulk_unarchive()
        self.assertTrue(all(templates.mapped("active")))

    def test_merge_wizard_requires_two_products(self):
        one = self.env["product.template"].create(
            {"name": "Only One", "sale_ok": True, "is_storable": True}
        )
        with self.assertRaises(Exception):
            one.action_avea_open_merge_wizard()
