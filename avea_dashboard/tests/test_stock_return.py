# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_till")
class TestAveaStockReturn(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {
                "name": "Return Test Product",
                "is_storable": True,
                "purchase_ok": True,
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Return Test Supplier"})
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

    def test_return_line_product_from_move(self):
        picking = self._create_done_incoming_picking()
        wizard = self.env["avea.stock.return"].create(
            {"picking_id": picking.id, "return_date": "2026-10-05"}
        )
        wizard._onchange_picking_id()
        line = wizard.line_ids[:1]
        self.assertTrue(line.move_id)
        self.assertEqual(line.product_id, self.product)

    def test_find_receipt_by_supplier_invoice_number(self):
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_ref": "INV-TEST-123",
                "picking_type_id": warehouse.in_type_id.id,
            }
        )
        self.env["purchase.order.line"].create(
            {
                "order_id": po.id,
                "product_id": self.product.id,
                "product_qty": 10.0,
                "price_unit": 5.0,
            }
        )
        po.button_confirm()
        picking = po.picking_ids[:1]
        picking.move_ids.quantity = 10.0
        picking.button_validate()
        self.assertEqual(picking.avea_supplier_invoice_ref, "INV-TEST-123")
        found = self.env["stock.picking"]._avea_find_receipt_for_return(
            "INV-TEST-123",
            company=self.env.company,
        )
        self.assertEqual(found, picking)
        wizard = self.env["avea.stock.return"].create(
            {"lookup_invoice_number": "INV-TEST-123", "return_date": "2026-10-05"}
        )
        wizard.action_find_receipt_by_invoice()
        self.assertEqual(wizard.picking_id, picking)

    def test_return_line_write_quantity_keeps_product(self):
        picking = self._create_done_incoming_picking()
        wizard = self.env["avea.stock.return"].create(
            {"picking_id": picking.id, "return_date": "2026-10-05"}
        )
        wizard._onchange_picking_id()
        line = wizard.line_ids[:1]
        line.write({"quantity": 3.0})
        self.assertEqual(line.product_id, self.product)
