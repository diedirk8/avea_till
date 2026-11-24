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

    def _create_receive(
        self, *, qty=1.0, cost=100.0, choice="keep", discount=0.0, invoice="PRICE-TEST-001"
    ):
        return self.env["avea.stock.receive"].create(
            {
                "partner_id": self.partner.id,
                "invoice_number": invoice,
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
                            "discount": discount,
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
        self.assertAlmostEqual(wizard.new_cost, 55.556, places=3)
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

    def test_pricing_wizard_shows_cost_to_three_decimals(self):
        self.template.avea_cost_ex_tax = 7.27
        line = self._create_receive(qty=1.0, cost=7.265).line_ids
        wizard = (
            self.env["avea.stock.receive.pricing.wizard"]
            .with_context(default_line_id=line.id)
            .create({"line_id": line.id})
        )
        self.assertAlmostEqual(wizard.current_cost, 7.270, places=3)
        self.assertAlmostEqual(wizard.new_cost, 7.265, places=3)
        self.assertAlmostEqual(wizard._avea_resolve_new_cost(), 7.265, places=4)
        self.assertEqual(wizard._fields["new_cost"]._digits[1], 3)

    def test_pricing_wizard_view_shows_cost_as_float_not_monetary(self):
        arch = self.env.ref("avea_till.view_avea_stock_receive_pricing_wizard_form").arch_db or ""
        self.assertIn("o_avea_stock_pricing_cost", arch)
        self.assertNotRegex(arch, r'name="new_cost"[^>]*widget="monetary"')
        self.assertNotRegex(arch, r'name="current_cost"[^>]*widget="monetary"')
        self.assertRegex(arch, r'name="new_retail"[^>]*widget="monetary"')

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

    def test_pricing_wizard_keeps_edited_retail_after_stale_markup_onchange(self):
        line = self._create_receive(qty=1.0, cost=126.25).line_ids
        wizard = (
            self.env["avea.stock.receive.pricing.wizard"]
            .with_context(default_line_id=line.id)
            .create({"line_id": line.id})
        )
        stale_markup = wizard.new_markup
        target_retail = (wizard.new_retail or 0.0) + 1.0
        wizard.new_retail = target_retail
        wizard._onchange_new_retail()
        wizard.new_markup = stale_markup
        wizard._onchange_new_markup()
        self.assertAlmostEqual(wizard.new_retail, target_retail, places=2)

        wizard.action_update_cost_and_pricing()
        self.template.invalidate_recordset()
        self.assertAlmostEqual(self.template.list_price, target_retail, places=2)

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

    def test_free_product_receive_keeps_catalog_cost(self):
        location = self.env.ref("stock.stock_location_stock")
        qty_before = self.product.with_context(location=location.id).qty_available
        receive = self.env["avea.stock.receive"].create(
            {
                "partner_id": self.partner.id,
                "invoice_number": "FREE-TEST-001",
                "invoice_date": fields.Date.today(),
                "received_date": fields.Date.today(),
                "company_id": self.company.id,
                "currency_id": self.currency.id,
                "mark_as_paid": False,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "quantity": 3.0,
                            "price_unit": 0.0,
                        }
                    )
                ],
            }
        )
        receive.action_receive_stock()

        self.product.invalidate_recordset()
        self.template.invalidate_recordset()
        self.assertEqual(receive.state, "done")
        self.assertEqual(receive.line_ids.avea_pricing_choice, "keep")
        self.assertAlmostEqual(self.template.avea_cost_ex_tax, 100.0, places=4)
        self.assertAlmostEqual(
            self.product.with_context(location=location.id).qty_available,
            qty_before + 3.0,
            places=2,
        )

    def test_line_discount_does_not_change_catalogue_cost(self):
        self.template.avea_cost_ex_tax = 247.39
        receive = self._create_receive(
            qty=4.0,
            cost=247.39,
            discount=5.0,
            choice="keep",
            invoice="PRICE-DISC-KEEP",
        )
        receive.action_receive_stock()
        self.template.invalidate_recordset()
        self.assertAlmostEqual(self.template.avea_cost_ex_tax, 247.39, places=4)
        line = receive.line_ids
        self.assertAlmostEqual(line.price_unit, 247.39, places=4)
        self.assertAlmostEqual(line.price_unit_discounted, 235.0205, places=4)

    def test_update_cost_only_uses_typed_unit_cost_not_discount(self):
        self.template.avea_cost_ex_tax = 86.12
        line = self._create_receive(
            qty=2.0,
            cost=87.20,
            discount=5.0,
            invoice="PRICE-DISC-TYPED",
        ).line_ids
        wizard = (
            self.env["avea.stock.receive.pricing.wizard"]
            .with_context(default_line_id=line.id)
            .create({"line_id": line.id})
        )
        wizard.action_update_cost_only()
        self.template.invalidate_recordset()
        self.assertAlmostEqual(self.template.avea_cost_ex_tax, 87.20, places=4)
        self.assertAlmostEqual(line.price_unit, 87.20, places=4)
        self.assertAlmostEqual(line.price_unit_discounted, 82.84, places=2)
        line.receive_id.action_receive_stock()
        payload = line.receive_id.get_stock_receive_report_payload()
        self.assertEqual(len(payload["price_changes"]), 1)
        detail = payload["price_changes"][0]["detail"]
        self.assertIn("Buying cost", detail)
        self.assertNotIn("82.84", detail)
        self.assertNotIn("82,84", detail)
        self.assertAlmostEqual(line.avea_previous_cost, 86.12, places=2)
        self.assertAlmostEqual(line.price_unit, 87.20, places=2)

    def test_update_cost_only_matching_typed_cost_keeps_catalogue(self):
        self.template.avea_cost_ex_tax = 247.39
        line = self._create_receive(
            qty=4.0,
            cost=247.39,
            discount=5.0,
            invoice="PRICE-DISC-SAME",
        ).line_ids
        wizard = (
            self.env["avea.stock.receive.pricing.wizard"]
            .with_context(default_line_id=line.id)
            .create({"line_id": line.id})
        )
        wizard.action_update_cost_only()
        self.assertEqual(line.avea_pricing_choice, "keep")
        self.template.invalidate_recordset()
        self.assertAlmostEqual(self.template.avea_cost_ex_tax, 247.39, places=4)

    def test_discount_onchange_does_not_open_pricing_wizard(self):
        self.template.avea_cost_ex_tax = 247.39
        line = self._create_receive(
            qty=1.0,
            cost=247.39,
            invoice="PRICE-DISC-ONCHANGE",
        ).line_ids
        line.discount = 5.0
        line._onchange_price_unit_cost_update()
        self.assertFalse(line.avea_open_pricing_wizard)
        self.assertNotEqual(line.avea_pricing_choice, "cost_only")

    def test_one_cent_cost_difference_does_not_open_pricing_wizard(self):
        self.template.avea_cost_ex_tax = 125.51
        line = self._create_receive(
            qty=2.0,
            cost=125.514,
            invoice="PRICE-1C-POPUP",
        ).line_ids
        self.assertFalse(line.avea_cost_differs)
        line.price_unit = 125.52
        line._onchange_price_unit_cost_update()
        self.assertFalse(line.avea_open_pricing_wizard)
        line.price_unit = 125.514
        line._onchange_price_unit_cost_update()
        self.assertFalse(line.avea_open_pricing_wizard)
        wizard = (
            self.env["avea.stock.receive.pricing.wizard"]
            .with_context(default_line_id=line.id)
            .create({"line_id": line.id})
        )
        wizard.action_update_cost_only()
        self.assertEqual(line.avea_pricing_choice, "keep")
        self.template.invalidate_recordset()
        self.assertAlmostEqual(self.template.avea_cost_ex_tax, 125.51, places=4)
        line.receive_id.action_receive_stock()
        self.assertEqual(line.receive_id.state, "done")
        payload = line.receive_id.get_stock_receive_report_payload()
        self.assertFalse(payload["price_changes"])

    def test_two_cent_cost_difference_still_opens_pricing_wizard(self):
        self.template.avea_cost_ex_tax = 125.51
        line = self._create_receive(
            qty=1.0,
            cost=125.51,
            invoice="PRICE-2C-POPUP",
        ).line_ids
        line.price_unit = 125.53
        self.assertTrue(line.avea_cost_differs)
        line._onchange_price_unit_cost_update()
        self.assertTrue(line.avea_open_pricing_wizard)
