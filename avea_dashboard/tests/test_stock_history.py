# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_till")
class TestAveaStockHistory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {
                "name": "History Test Product",
                "is_storable": True,
                "purchase_ok": True,
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "History Test Supplier"})
        cls.picking_type = cls.env["stock.picking.type"].search(
            [("code", "=", "incoming"), ("company_id", "=", cls.env.company.id)],
            limit=1,
        )

    def _create_done_incoming_picking(self, qty=10.0):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type.id,
                "location_id": self.picking_type.default_location_src_id.id,
                "location_dest_id": self.picking_type.default_location_dest_id.id,
                "partner_id": self.partner.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": qty,
                            "product_uom": self.product.uom_id.id,
                            "location_id": self.picking_type.default_location_src_id.id,
                            "location_dest_id": self.picking_type.default_location_dest_id.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.move_ids.quantity = qty
        picking.button_validate()
        return picking

    def test_return_creates_history_and_receive_can_open_return(self):
        picking = self._create_done_incoming_picking()
        receive = self.env["avea.stock.receive"].create(
            {
                "state": "done",
                "partner_id": self.partner.id,
                "invoice_number": "HIST-001",
                "invoice_date": "2026-10-05",
                "received_date": "2026-10-05",
                "picking_id": picking.id,
            }
        )
        self.assertTrue(receive.can_return_stock)
        action = receive.action_return_this_stock()
        self.assertEqual(action["res_model"], "avea.stock.return")
        wizard = self.env["avea.stock.return"].browse(action["res_id"])
        self.assertEqual(wizard.picking_id, picking)

        return_wizard = self.env["avea.stock.return"].create(
            {"picking_id": picking.id, "return_date": "2026-10-05"}
        )
        return_wizard._onchange_picking_id()
        line = return_wizard.line_ids[:1]
        line.quantity = 2.0
        return_wizard._avea_create_return_history(
            return_wizard._avea_return_lines(),
            self.env["stock.picking"],
            self.env["account.move"],
        )
        history = self.env["avea.stock.return.history"].search(
            [("receipt_picking_id", "=", picking.id)]
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history.line_ids.quantity, 2.0)
