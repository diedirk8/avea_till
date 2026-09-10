# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaBusinessOverview(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.config.write({"payment_method_ids": [(6, 0, cls.cash_pm1.ids)]})
        cls.Overview = cls.env["avea.business.overview"]
        cls.product = cls.create_product("Overview Product", cls.categ_basic, 100.0, 40.0)

    def _create_paid_order(self, *, amount, uuid, when, session=None):
        if session is None:
            session = self.open_new_session(0)
        lines = [(self.product, amount / self.product.lst_price)]
        order_data = self.create_ui_order_data(
            pos_order_lines_ui_args=lines,
            payments=[(self.cash_pm1, amount)],
            uuid=uuid,
        )
        sync_result = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(sync_result["pos.order"][0]["id"])
        order.write({"date_order": when})
        self.assertIn(order.state, self.env["pos.session"]._avea_paid_order_states())
        return order

    def test_busiest_time_uses_single_day_hour_slot(self):
        overview = self.Overview.create({"period": "last_30"})
        base_day = fields.Date.context_today(overview) - timedelta(days=3)
        morning = datetime.combine(base_day, datetime.min.time()) + timedelta(hours=10)
        afternoon = datetime.combine(base_day, datetime.min.time()) + timedelta(hours=14)
        other_day = base_day - timedelta(days=1)
        other_morning = datetime.combine(other_day, datetime.min.time()) + timedelta(
            hours=10
        )

        session = self.open_new_session(0)
        orders = self.env["pos.order"].browse(
            [
                self._create_paid_order(
                    amount=100.0, uuid="overview-busy-1", when=morning, session=session
                ).id,
                self._create_paid_order(
                    amount=100.0,
                    uuid="overview-busy-2",
                    when=other_morning,
                    session=session,
                ).id,
                self._create_paid_order(
                    amount=500.0,
                    uuid="overview-busy-3",
                    when=afternoon,
                    session=session,
                ).id,
            ]
        )

        busy = overview._busy_stats_from_orders(orders)
        self.assertEqual(busy["day_sales"], 600.0)
        self.assertEqual(busy["time_sales"], 500.0)
        self.assertEqual(busy["time_count"], 1)
        self.assertIn("14:00", busy["time_display"])
        self.assertLessEqual(busy["time_sales"], busy["day_sales"])

    def test_busiest_time_never_exceeds_busiest_day(self):
        overview = self.Overview.create({"period": "last_30"})
        day_a = fields.Date.context_today(overview) - timedelta(days=2)
        day_b = fields.Date.context_today(overview) - timedelta(days=1)
        session = self.open_new_session(0)
        orders = self.env["pos.order"].browse(
            [
                self._create_paid_order(
                    amount=250.0,
                    uuid="overview-cap-1",
                    when=datetime.combine(day_a, datetime.min.time()) + timedelta(hours=9),
                    session=session,
                ).id,
                self._create_paid_order(
                    amount=250.0,
                    uuid="overview-cap-2",
                    when=datetime.combine(day_a, datetime.min.time()) + timedelta(hours=10),
                    session=session,
                ).id,
                self._create_paid_order(
                    amount=400.0,
                    uuid="overview-cap-3",
                    when=datetime.combine(day_b, datetime.min.time()) + timedelta(hours=11),
                    session=session,
                ).id,
            ]
        )

        busy = overview._busy_stats_from_orders(orders)
        self.assertEqual(busy["day_sales"], 500.0)
        self.assertLessEqual(busy["time_sales"], busy["day_sales"])
