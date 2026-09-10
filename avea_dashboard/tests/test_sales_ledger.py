# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install", "avea_till")
class TestAveaSalesLedger(TestPoSCommon):
    """Sales Ledger reads native pos.order.line rows across all sessions."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.product_a = cls.create_product("Sales Ledger Product A", cls.categ_basic, 100, 50)
        cls.product_b = cls.create_product("Sales Ledger Product B", cls.categ_basic, 50, 25)
        cls.Line = cls.env["pos.order.line"]

    def _create_paid_order(self, *, lines, customer=False, uuid="sales-ledger-test", session=None):
        if session is None:
            self.config.write({"payment_method_ids": [(6, 0, self.cash_pm1.ids)]})
            session = self.open_new_session(0)
        total = sum(qty * product.lst_price for product, qty in lines)
        order_data = self.create_ui_order_data(
            pos_order_lines_ui_args=lines,
            customer=customer,
            payments=[(self.cash_pm1, total)],
            uuid=uuid,
        )
        sync_result = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(sync_result["pos.order"][0]["id"])
        self.assertIn(order.state, self.env["pos.session"]._avea_paid_order_states())
        return order, session

    def _ledger_lines(self, domain=None):
        base = self.Line._avea_sales_ledger_domain()
        if domain:
            base = base + domain
        return self.Line.search(base, order="avea_order_date desc, id desc")

    def test_multiple_products_one_order_create_separate_rows(self):
        order, _session = self._create_paid_order(
            lines=[(self.product_a, 2), (self.product_b, 1)],
            uuid="sales-ledger-multi",
        )
        lines = self._ledger_lines([("order_id", "=", order.id)])
        self.assertEqual(len(lines), 2)
        self.assertEqual(set(lines.mapped("product_id")), {self.product_a, self.product_b})
        self.assertEqual(set(lines.mapped("avea_order_reference")), {order._avea_till_display_reference()})

    def test_customer_and_walk_in_sales(self):
        self.config.write({"payment_method_ids": [(6, 0, self.cash_pm1.ids)]})
        session = self.open_new_session(0)

        def _order(lines, customer, uuid):
            total = sum(qty * product.lst_price for product, qty in lines)
            data = self.create_ui_order_data(
                pos_order_lines_ui_args=lines,
                customer=customer,
                payments=[(self.cash_pm1, total)],
                uuid=uuid,
            )
            sync_result = self.env["pos.order"].sync_from_ui([data])
            return self.env["pos.order"].browse(sync_result["pos.order"][0]["id"])

        order_with_customer = _order(
            [(self.product_a, 1)], self.customer, "sales-ledger-customer"
        )
        order_walk_in = _order([(self.product_b, 1)], False, "sales-ledger-walkin")
        customer_line = self._ledger_lines([("order_id", "=", order_with_customer.id)])
        walk_in_line = self._ledger_lines([("order_id", "=", order_walk_in.id)])
        self.assertEqual(customer_line.avea_order_partner_id, self.customer)
        self.assertFalse(walk_in_line.avea_order_partner_id)

    def test_refund_line_keeps_negative_quantity(self):
        order, _session = self._create_paid_order(
            lines=[(self.product_a, -1)],
            uuid="sales-ledger-refund",
        )
        line = self._ledger_lines([("order_id", "=", order.id)])
        self.assertEqual(len(line), 1)
        self.assertLess(line.qty, 0)

    def test_domain_excludes_draft_orders(self):
        draft_order = self.env["pos.order"].search([("state", "=", "draft")], limit=1)
        if not draft_order:
            session = self.open_new_session(0)
            draft_order = self.env["pos.order"].create(
                {
                    "session_id": session.id,
                    "partner_id": self.customer.id,
                    "amount_tax": 0.0,
                    "amount_total": 0.0,
                    "amount_paid": 0.0,
                    "amount_return": 0.0,
                    "lines": [
                        (
                            0,
                            0,
                            {
                                "product_id": self.product_a.id,
                                "qty": 1,
                                "price_unit": 100,
                                "price_subtotal": 100,
                                "price_subtotal_incl": 100,
                                "name": "Line 1",
                            },
                        )
                    ],
                }
            )
        self.assertNotIn(draft_order.state, self.env["pos.session"]._avea_paid_order_states())
        lines = self._ledger_lines([("order_id", "=", draft_order.id)])
        self.assertFalse(lines)

    def test_search_filters_product_customer_and_order_reference(self):
        order, _session = self._create_paid_order(
            lines=[(self.product_a, 1), (self.product_b, 2)],
            customer=self.customer,
            uuid="sales-ledger-filter",
        )
        reference = order._avea_till_display_reference()
        product_domain = self.Line._avea_sales_ledger_search_domain(product="Product A")
        self.assertTrue(
            self.Line.search(product_domain + [("order_id", "=", order.id)])
        )
        customer_domain = self.Line._avea_sales_ledger_search_domain(
            customer=self.customer.name
        )
        self.assertTrue(self.Line.search(customer_domain + [("order_id", "=", order.id)]))
        order_domain = self.Line._avea_sales_ledger_search_domain(order_ref=reference)
        self.assertEqual(
            self.Line.search(order_domain + [("order_id", "=", order.id)]).order_id,
            order,
        )

    def test_default_ordering_newest_first(self):
        self.config.write({"payment_method_ids": [(6, 0, self.cash_pm1.ids)]})
        session = self.open_new_session(0)
        older, session = self._create_paid_order(
            lines=[(self.product_a, 1)],
            uuid="sales-ledger-older",
            session=session,
        )
        newer, _session = self._create_paid_order(
            lines=[(self.product_b, 1)],
            uuid="sales-ledger-newer",
            session=session,
        )
        lines = self._ledger_lines(
            [("order_id", "in", [older.id, newer.id])]
        )
        self.assertGreaterEqual(lines[0].avea_order_date, lines[-1].avea_order_date)

    def test_search_date_range(self):
        order, _session = self._create_paid_order(
            lines=[(self.product_a, 1)],
            uuid="sales-ledger-date",
        )
        line = self._ledger_lines([("order_id", "=", order.id)])
        sale_date = fields.Datetime.to_datetime(line.avea_order_date)
        domain = self.Line._avea_sales_ledger_search_domain(
            date_from=sale_date.replace(hour=0, minute=0, second=0),
            date_to=sale_date.replace(hour=23, minute=59, second=59),
        )
        self.assertIn(line, self.Line.search(domain))

    def test_pagination_respects_limit(self):
        action = self.Line.action_avea_open_sales_ledger()
        context = action.get("context") or {}
        if isinstance(context, str):
            context = safe_eval(context)
        self.assertEqual(context.get("limit"), 100)
        limited = self.Line.search(
            self.Line._avea_sales_ledger_domain(),
            order="avea_order_date desc, id desc",
            limit=100,
        )
        self.assertLessEqual(len(limited), 100)

    def test_open_order_action_targets_parent_order(self):
        order, _session = self._create_paid_order(
            lines=[(self.product_a, 1)],
            uuid="sales-ledger-open-order",
        )
        line = self._ledger_lines([("order_id", "=", order.id)])
        action = line.action_avea_open_pos_order()
        self.assertEqual(action["res_model"], "pos.order")
        self.assertEqual(action["res_id"], order.id)

    def test_product_reference_split_from_pos_name(self):
        self.product_a.default_code = "00180"
        order, _session = self._create_paid_order(
            lines=[(self.product_a, 1)],
            uuid="sales-ledger-ref-split",
        )
        line = self._ledger_lines([("order_id", "=", order.id)])
        line.write({"full_product_name": "[00180] RC Mini Puppy 4kg"})
        line._compute_avea_product_display()
        self.assertEqual(line.avea_product_reference, "00180")
        self.assertEqual(line.avea_product_display, "RC Mini Puppy 4kg")
        self.assertEqual(line.avea_product_line_label, "00180 · RC Mini Puppy 4kg")

    def test_banner_info_reports_count_and_range(self):
        order, _session = self._create_paid_order(
            lines=[(self.product_a, 1), (self.product_b, 1)],
            uuid="sales-ledger-banner",
        )
        domain = self.Line._avea_sales_ledger_domain() + [("order_id", "=", order.id)]
        info = self.Line.avea_sales_ledger_banner_info(domain)
        self.assertEqual(info["total"], 2)
        self.assertIn("sale lines", info["summary_display"])
        self.assertTrue(info["range_display"])
