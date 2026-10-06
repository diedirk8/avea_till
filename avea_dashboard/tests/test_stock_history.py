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

    def test_done_receive_not_deleted_on_archive(self):
        picking = self._create_done_incoming_picking()
        receive = self.env["avea.stock.receive"].create(
            {
                "state": "done",
                "partner_id": self.partner.id,
                "invoice_number": "KEEP-001",
                "invoice_date": "2026-10-05",
                "received_date": "2026-10-05",
                "picking_id": picking.id,
            }
        )
        receive_id = receive.id
        receive._avea_archive_completed()
        self.assertTrue(self.env["avea.stock.receive"].browse(receive_id).exists())

    def test_payment_status_follows_posted_bill_not_only_mark_as_paid(self):
        picking = self._create_done_incoming_picking()
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner.id,
                "invoice_date": "2026-10-05",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "quantity": 1,
                            "price_unit": 100.0,
                        }
                    )
                ],
            }
        )
        bill.action_post()
        journals = self.env.company._avea_expense_journals()
        if journals:
            self.env["avea.stock.mixin"]._avea_pay_vendor_bill(
                bill,
                journals[:1],
                self.partner,
                self.env.company,
                "2026-10-05",
                "PAID-TEST",
            )
        receive = self.env["avea.stock.receive"].create(
            {
                "state": "done",
                "partner_id": self.partner.id,
                "invoice_number": "PAID-TEST",
                "invoice_date": "2026-10-05",
                "received_date": "2026-10-05",
                "bill_id": bill.id,
                "picking_id": picking.id,
                "mark_as_paid": False,
            }
        )
        receive._compute_payment_status()
        self.assertIn("Paid from", receive.payment_status)

    def test_backfill_receive_history_from_avea_po(self):
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner.id,
                "partner_ref": "BACKFILL-INV",
                "origin": "Avea Receive Stock",
                "picking_type_id": warehouse.in_type_id.id,
            }
        )
        self.env["purchase.order.line"].create(
            {
                "order_id": po.id,
                "product_id": self.product.id,
                "product_qty": 5.0,
                "price_unit": 10.0,
            }
        )
        po.button_confirm()
        picking = po.picking_ids[:1]
        picking.move_ids.quantity = 5.0
        picking.button_validate()
        po.action_create_invoice()
        bill = po.invoice_ids[:1]
        bill.invoice_date = "2026-10-05"
        bill.action_post()
        self.assertEqual(self.env["avea.stock.receive"]._avea_backfill_receive_history(), 1)
        history = self.env["avea.stock.receive"].search(
            [("purchase_order_id", "=", po.id), ("state", "=", "done")]
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history.invoice_number, "BACKFILL-INV")
