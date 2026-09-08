# -*- coding: utf-8 -*-
from odoo import Command, fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from unittest import SkipTest


@tagged("post_install", "-at_install", "avea_stock")
class TestAveaStockReceivePricing(TransactionCase):
    """Receive Stock pricing must stay predictable under average costing."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Avea Pricing Test Supplier",
                "supplier_rank": 1,
                "company_id": cls.company.id,
                "is_company": True,
            }
        )
        cls.purchase_tax = cls.company.account_purchase_tax_id
        cls.sale_tax = cls.company.account_sale_tax_id
        cls.average_category = cls.env["product.category"].search(
            [("property_cost_method", "=", "average")], limit=1
        )
        if not cls.average_category:
            cls.average_category = cls.env["product.category"].create(
                {
                    "name": "Avea Average Test Category",
                    "property_cost_method": "average",
                }
            )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Avea Pricing Test Product",
                "type": "consu",
                "is_storable": True,
                "list_price": 115.0,
                "standard_price": 100.0,
                "avea_cost_ex_tax": 100.0,
                "purchase_ok": True,
                "sale_ok": True,
                "company_id": cls.company.id,
                "categ_id": cls.average_category.id,
                "supplier_taxes_id": [Command.set(cls.purchase_tax.ids)]
                if cls.purchase_tax
                else False,
                "taxes_id": [Command.set(cls.sale_tax.ids)] if cls.sale_tax else False,
            }
        )
        cls.template = cls.product.product_tmpl_id
        if cls.product.cost_method != "average":
            raise SkipTest("Average costing category required for pricing tests.")

    def _create_receive(self, *, qty=1.0, cost=100.0, choice="keep"):
        return self.env["avea.stock.receive"].create(
            {
                "partner_id": self.partner.id,
                "invoice_number": "PRICE-TEST-001",
                "invoice_date": fields.Date.today(),
                "received_date": fields.Date.today(),
                "company_id": self.company.id,
                "currency_id": self.currency.id,
                "mark_as_paid": False,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "quantity": qty,
                            "price_unit": cost,
                            "avea_pricing_choice": choice,
                        }
                    )
                ],
            }
        )

    def test_avco_changes_standard_price_but_not_avea_cost_on_keep(self):
        receive = self._create_receive(qty=10.0, cost=55.5555, choice="keep")
        avea_before = self.template.avea_cost_ex_tax
        standard_before = self.product.standard_price

        receive.action_receive_stock()

        self.product.invalidate_recordset()
        self.template.invalidate_recordset()
        self.assertNotAlmostEqual(
            self.product.standard_price,
            standard_before,
            places=2,
            msg="Average costing should still update Odoo standard_price.",
        )
        self.assertAlmostEqual(
            self.template.avea_cost_ex_tax,
            avea_before,
            places=4,
            msg="Avea purchasing cost must not move when pricing is kept.",
        )

    def test_wizard_update_cost_only_sets_avea_cost_without_avco_drift(self):
        line = self._create_receive(qty=5.0, cost=55.5555).line_ids
        wizard = (
            self.env["avea.stock.receive.pricing.wizard"]
            .with_context(default_line_id=line.id)
            .create({"line_id": line.id})
        )
        self.assertAlmostEqual(wizard.new_cost, 55.56, places=2)
        wizard.action_update_cost_only()

        self.template.invalidate_recordset()
        self.product.invalidate_recordset()
        self.assertAlmostEqual(self.template.avea_cost_ex_tax, 55.5555, places=4)
        self.assertAlmostEqual(line.price_unit, 55.5555, places=4)

        receive = line.receive_id
        receive.action_receive_stock()

        self.template.invalidate_recordset()
        self.product.invalidate_recordset()
        self.assertAlmostEqual(self.template.avea_cost_ex_tax, 55.5555, places=4)

    def test_pricing_round_trip_keeps_resolved_cost(self):
        line = self._create_receive(qty=1.0, cost=50.1234).line_ids
        wizard = (
            self.env["avea.stock.receive.pricing.wizard"]
            .with_context(default_line_id=line.id)
            .create({"line_id": line.id})
        )
        resolved = wizard._avea_resolve_new_cost()
        self.assertAlmostEqual(resolved, 50.1234, places=4)

        template = wizard.product_tmpl_id
        template._avea_pricing_from_cost_retail(wizard.new_cost, wizard.new_retail)
        wizard._avea_recompute_from_cost_retail()
        self.assertAlmostEqual(wizard._avea_resolve_new_cost(), 50.1234, places=4)

    def test_receive_multiple_units_at_different_supplier_cost(self):
        """Existing stock + new receipt must not rewrite Avea cost when kept."""
        self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "product_id": self.product.id,
                "inventory_quantity": 4.0,
                "location_id": self.env.ref("stock.stock_location_stock").id,
            }
        ).action_apply_inventory()
        self.template.avea_cost_ex_tax = 100.0
        self.product.standard_price = 100.0

        receive = self._create_receive(qty=6.0, cost=80.3333, choice="keep")
        receive.action_receive_stock()

        self.template.invalidate_recordset()
        self.product.invalidate_recordset()
        self.assertAlmostEqual(self.template.avea_cost_ex_tax, 100.0, places=4)
        self.assertNotAlmostEqual(self.product.standard_price, 100.0, places=2)
