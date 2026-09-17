# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_stock")
class TestAveaProductPricingTax(TransactionCase):
    """Tax-aware cost and profit fields used by promotions and stock."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.tax_15 = cls.env["account.tax"].create(
            {
                "name": "Avea Test VAT 15%",
                "amount": 15.0,
                "type_tax_use": "sale",
                "amount_type": "percent",
                "company_id": cls.company.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Avea Tax Pricing Product",
                "type": "consu",
                "sale_ok": True,
                "list_price": 365.0,
                "avea_cost_ex_tax": 242.96,
                "standard_price": 242.96,
                "taxes_id": [Command.set(cls.tax_15.ids)],
            }
        )
        cls.template = cls.product.product_tmpl_id

    def test_cost_incl_tax_uses_product_sales_tax(self):
        self.assertAlmostEqual(self.template.avea_cost_incl_tax, 279.40, places=2)

    def test_profit_incl_tax_is_retail_minus_cost_incl_tax(self):
        self.assertAlmostEqual(self.template.avea_profit_incl_tax, 85.60, places=2)

    def test_markup_uses_ex_tax_retail_and_cost(self):
        self.assertAlmostEqual(self.template.avea_markup_percent, 30.6, places=1)

    def test_product_variant_exposes_related_tax_fields(self):
        self.assertAlmostEqual(self.product.avea_cost_incl_tax, 279.40, places=2)
        self.assertAlmostEqual(self.product.avea_profit_incl_tax, 85.60, places=2)

    def test_zero_tax_product_leaves_cost_incl_equal_to_cost_ex(self):
        product = self.env["product.product"].create(
            {
                "name": "Avea Zero Tax Product",
                "type": "consu",
                "sale_ok": True,
                "list_price": 100.0,
                "avea_cost_ex_tax": 60.0,
                "taxes_id": [Command.clear()],
            }
        )
        template = product.product_tmpl_id
        self.assertAlmostEqual(template.avea_cost_incl_tax, 60.0, places=2)
        self.assertAlmostEqual(template.avea_profit_incl_tax, 40.0, places=2)
