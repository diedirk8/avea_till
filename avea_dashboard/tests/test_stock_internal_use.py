# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_till")
class TestAveaStockInternalUse(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {
                "name": "Internal Use Seeds",
                "is_storable": True,
                "purchase_ok": True,
            }
        )
        cls.location = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        ).lot_stock_id
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.location, 20.0
        )

    def test_internal_use_reduces_stock_and_creates_history(self):
        wizard = self.env["avea.stock.internal_use"].create(
            {
                "location_id": self.location.id,
                "use_date": "2026-10-26",
                "notes": "Demo cage",
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "quantity": 3.0,
                        }
                    )
                ],
            }
        )
        qty_before = self.product.with_context(location=self.location.id).qty_available
        wizard.action_use_stock()
        qty_after = self.product.with_context(location=self.location.id).qty_available
        self.assertAlmostEqual(qty_after, qty_before - 3.0)

        history = self.env["avea.stock.internal_use.history"].search(
            [("notes", "=", "Demo cage")], limit=1
        )
        self.assertTrue(history)
        self.assertEqual(len(history.scrap_ids), 1)
        self.assertEqual(history.scrap_ids.state, "done")
        self.assertEqual(history.line_ids.quantity, 3.0)

    def test_internal_use_rejects_insufficient_stock(self):
        wizard = self.env["avea.stock.internal_use"].create(
            {
                "location_id": self.location.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "quantity": 9999.0,
                        }
                    )
                ],
            }
        )
        with self.assertRaises(ValidationError):
            wizard.action_use_stock()

    def test_action_open_internal_use(self):
        action = self.env["avea.stock.internal_use"].action_open_internal_use()
        self.assertEqual(action["res_model"], "avea.stock.internal_use")
        self.assertEqual(action["target"], "main")
