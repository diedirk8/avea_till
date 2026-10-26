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
        cls.reason = cls.env["stock.scrap.reason.tag"].create(
            {"name": "Broken bag"}
        )

    def _wizard_vals(self, **overrides):
        vals = {
            "location_id": self.location.id,
            "use_date": "2026-10-26",
            "reason_tag_id": self.reason.id,
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
        vals.update(overrides)
        return vals

    def test_internal_use_reduces_stock_and_creates_history(self):
        wizard = self.env["avea.stock.internal_use"].create(self._wizard_vals())
        self.assertEqual(wizard.user_id, self.env.user)
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
        self.assertEqual(history.reason_tag_id, self.reason)
        self.assertEqual(history.user_id, self.env.user)
        self.assertEqual(history.scrap_ids.scrap_reason_tag_ids, self.reason)

    def test_scrap_records_selected_user(self):
        other_user = self.env["res.users"].create(
            {
                "name": "Scrap Staff",
                "login": "scrap_staff@dev.local",
                "email": "scrap_staff@dev.local",
            }
        )
        wizard = self.env["avea.stock.internal_use"].create(
            self._wizard_vals(user_id=other_user.id)
        )
        wizard.action_use_stock()
        history = self.env["avea.stock.internal_use.history"].search(
            [("notes", "=", "Demo cage")], limit=1
        )
        self.assertEqual(history.user_id, other_user)

    def test_internal_use_rejects_insufficient_stock(self):
        wizard = self.env["avea.stock.internal_use"].create(
            self._wizard_vals(
                line_ids=[
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "quantity": 9999.0,
                        }
                    )
                ]
            )
        )
        with self.assertRaises(ValidationError):
            wizard.action_use_stock()

    def test_scrap_requires_reason(self):
        wizard = self.env["avea.stock.internal_use"].create(
            self._wizard_vals(reason_tag_id=False)
        )
        with self.assertRaises(ValidationError):
            wizard.action_use_stock()

    def test_quick_add_reason_reuses_existing(self):
        reason_id, display_name = self.env["stock.scrap.reason.tag"].name_create(
            "Broken bag"
        )
        self.assertEqual(reason_id, self.reason.id)
        self.assertIn("Broken bag", display_name)

    def test_action_open_internal_use(self):
        action = self.env["avea.stock.internal_use"].action_open_internal_use()
        self.assertEqual(action["res_model"], "avea.stock.internal_use")
        self.assertEqual(action["name"], "Scrap Stock")
        self.assertEqual(action["target"], "main")
        wizard = self.env["avea.stock.internal_use"].browse(action["res_id"])
        self.assertEqual(wizard.user_id, self.env.user)

    def test_action_cancel_scrap_returns_to_products(self):
        wizard = self.env["avea.stock.internal_use"].create(self._wizard_vals())
        action = wizard.action_cancel_scrap()
        self.assertEqual(action["res_model"], "product.template")
        self.assertEqual(action["target"], "main")
