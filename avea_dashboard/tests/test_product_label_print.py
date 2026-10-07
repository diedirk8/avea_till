# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_stock")
class TestAveaProductLabelPrint(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env["product.template"].create(
            {
                "name": "Shelf Label Product",
                "type": "consu",
                "sale_ok": True,
                "list_price": 99.0,
            }
        )
        cls.param = cls.env["ir.config_parameter"].sudo()

    def test_dymo_process_flags_direct_print_when_enabled(self):
        self.param.set_param("avea_till.direct_product_label_print", "1")
        wizard = self.env["product.label.layout"].create(
            {
                "print_format": "dymo",
                "product_tmpl_ids": [Command.set(self.template.ids)],
            }
        )
        action = wizard.process()
        self.assertTrue(action["context"].get("avea_direct_label_print"))
        self.assertEqual(
            action["report_name"], "product.report_producttemplatelabel_dymo"
        )

    def test_dymo_process_unchanged_when_disabled(self):
        self.param.set_param("avea_till.direct_product_label_print", "0")
        wizard = self.env["product.label.layout"].create(
            {
                "print_format": "dymo",
                "product_tmpl_ids": [Command.set(self.template.ids)],
            }
        )
        action = wizard.process()
        self.assertFalse(action["context"].get("avea_direct_label_print"))
