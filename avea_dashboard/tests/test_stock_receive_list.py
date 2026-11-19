# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_till")
class TestStockReceiveList(TransactionCase):
    def test_receive_stock_opens_a_list_not_a_singleton_draft(self):
        Receive = self.env["avea.stock.receive"]
        before = Receive.search_count([])
        action = Receive.action_open_receive()
        self.assertEqual(action["res_model"], "avea.stock.receive")
        self.assertEqual(action["view_mode"], "list,form")
        self.assertFalse(action.get("res_id"))
        self.assertEqual(Receive.search_count([]), before)

    def test_new_receive_keeps_an_existing_draft(self):
        first = self.env["avea.stock.receive"].create(
            {"invoice_number": "DRAFT-A"}
        )
        action = self.env["avea.stock.receive"].action_new_receive()
        second = self.env["avea.stock.receive"].browse(action["res_id"])
        self.assertTrue(first.exists())
        self.assertEqual(first.state, "draft")
        self.assertEqual(first.invoice_number, "DRAFT-A")
        self.assertTrue(second.exists())
        self.assertNotEqual(first, second)
        self.assertEqual(second.state, "draft")
        self.assertEqual(action["view_mode"], "form")

    def test_back_to_list_keeps_the_draft(self):
        receive = self.env["avea.stock.receive"].create(
            {"invoice_number": "KEEP-ME"}
        )
        action = receive.action_back_to_receive_list()
        self.assertTrue(receive.exists())
        self.assertEqual(receive.invoice_number, "KEEP-ME")
        self.assertEqual(action["view_mode"], "list,form")

    def test_discard_removes_only_that_draft(self):
        keep = self.env["avea.stock.receive"].create({"invoice_number": "KEEP"})
        toss = self.env["avea.stock.receive"].create({"invoice_number": "TOSS"})
        toss.action_cancel_receive()
        self.assertTrue(keep.exists())
        self.assertFalse(toss.exists())

    def test_open_record_uses_receive_form_for_drafts(self):
        receive = self.env["avea.stock.receive"].create({})
        action = receive.action_open_record()
        form_id = self.env.ref("avea_till.view_avea_stock_receive_form").id
        self.assertEqual(action["view_id"], form_id)
        self.assertEqual(action["res_id"], receive.id)

    def test_supplier_receive_still_prefills_and_does_not_steal_other_drafts(self):
        akwa = self.env["res.partner"].create(
            {"name": "Zzqx List Akwa", "supplier_rank": 1}
        )
        other = self.env["res.partner"].create(
            {"name": "Zzqx List Other", "supplier_rank": 1}
        )
        busy = self.env["avea.stock.receive"].create(
            {"partner_id": other.id, "invoice_number": "OTHER-DRAFT"}
        )
        action = akwa.action_avea_receive_stock()
        receive = self.env["avea.stock.receive"].browse(action["res_id"])
        self.assertEqual(receive.partner_id, akwa)
        self.assertNotEqual(receive, busy)
        self.assertEqual(busy.partner_id, other)
        self.assertEqual(busy.invoice_number, "OTHER-DRAFT")
