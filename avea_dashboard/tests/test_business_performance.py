# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaBusinessPerformance(TestPoSCommon):
    """Business Performance rankings from native POS sale lines."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.config.write({"payment_method_ids": [(6, 0, cls.cash_pm1.ids)]})
        cls.Line = cls.env["pos.order.line"]
        cls.Performance = cls.env["avea.business.performance"]
        cls.categ_alt = cls.env["product.category"].create({"name": "Performance Alt"})
        cls.product_high_vol = cls.create_product(
            "Perf High Volume", cls.categ_basic, 20.0, 5.0
        )
        cls.product_high_val = cls.create_product(
            "Perf High Value", cls.categ_alt, 500.0, 200.0
        )
        cls.product_discounted = cls.create_product(
            "Perf Discounted", cls.categ_basic, 100.0, 40.0
        )
        cls.product_refund = cls.create_product(
            "Perf Refund", cls.categ_alt, 80.0, 30.0
        )
        for product, cost in (
            (cls.product_high_vol, 5.0),
            (cls.product_high_val, 200.0),
            (cls.product_discounted, 40.0),
            (cls.product_refund, 30.0),
        ):
            product.product_tmpl_id.avea_cost_ex_tax = cost

    def _create_paid_order(self, *, lines, uuid="perf-test", session=None):
        if session is None:
            session = self.open_new_session(0)
        total = sum(qty * product.lst_price for product, qty in lines)
        order_data = self.create_ui_order_data(
            pos_order_lines_ui_args=lines,
            payments=[(self.cash_pm1, total)],
            uuid=uuid,
        )
        sync_result = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(sync_result["pos.order"][0]["id"])
        self.assertIn(order.state, self.env["pos.session"]._avea_paid_order_states())
        return order, session

    def _rankings_for_orders(self, orders):
        return self.Line._avea_performance_rankings(orders)

    def test_performance_product_label_uses_clean_name(self):
        product = self.product_high_vol
        product.default_code = "00180"
        label = self.Line._avea_performance_product_label(product)
        self.assertEqual(label, "00180 · Perf High Volume")
        self.assertNotIn("[", label)

    def test_balanced_performer_outranks_one_off_high_value(self):
        aggregates = [
            {
                "record_id": 1,
                "label": "Steady Seller",
                "units_positive": 50.0,
                "revenue_ex_tax": 1000.0,
                "gross_profit": 750.0,
            },
            {
                "record_id": 2,
                "label": "One Off Premium",
                "units_positive": 1.0,
                "revenue_ex_tax": 1000.0,
                "gross_profit": 800.0,
            },
        ]
        ranked = self.Line._avea_performance_score_rows(aggregates)
        self.assertEqual(ranked[0]["label"], "Steady Seller")

    def test_profit_ranking_uses_gross_profit_not_margin_percent(self):
        aggregates = [
            {
                "record_id": 1,
                "label": "High Margin Small",
                "units_positive": 2.0,
                "revenue_ex_tax": 100.0,
                "gross_profit": 80.0,
            },
            {
                "record_id": 2,
                "label": "Lower Margin Big",
                "units_positive": 20.0,
                "revenue_ex_tax": 1000.0,
                "gross_profit": 300.0,
            },
        ]
        ranked = self.Line._avea_performance_profit_rows(aggregates)
        self.assertEqual(ranked[0]["label"], "Lower Margin Big")

    def test_integration_profit_and_performance_from_pos_orders(self):
        order, _session = self._create_paid_order(
            lines=[(self.product_high_vol, 20), (self.product_high_val, 2)],
            uuid="perf-integration-main",
        )
        rankings = self._rankings_for_orders(order)
        self.assertTrue(rankings["top_products"])
        self.assertTrue(rankings["profit_products"])
        top_names = [row["label"] for row in rankings["top_products"]]
        self.assertIn(self.product_high_vol.display_name, top_names)
        profit_leader = rankings["profit_products"][0]
        self.assertGreater(profit_leader["gross_profit"], 0.0)
        self.assertGreater(profit_leader["revenue_ex_tax"], 0.0)

    def test_discount_reduces_revenue_and_profit(self):
        order, _session = self._create_paid_order(
            lines=[(self.product_discounted, 1)],
            uuid="perf-discount-base",
        )
        line = order.lines.filtered(lambda l: l.product_id == self.product_discounted)
        baseline = self.Line._avea_performance_line_metrics(line)
        line.write({"discount": 20.0, "price_subtotal": baseline["revenue_ex_tax"] * 0.8})
        discounted = self.Line._avea_performance_line_metrics(line)
        self.assertLess(discounted["revenue_ex_tax"], baseline["revenue_ex_tax"])
        self.assertLess(discounted["gross_profit"], baseline["gross_profit"])

    def test_refund_reduces_category_totals(self):
        _order_sale, session = self._create_paid_order(
            lines=[(self.product_refund, 5)],
            uuid="perf-refund-sale",
        )
        order_refund, _session = self._create_paid_order(
            lines=[(self.product_refund, -2)],
            uuid="perf-refund-return",
            session=session,
        )
        orders = _order_sale | order_refund
        rankings = self._rankings_for_orders(orders)
        product_row = next(
            row
            for row in rankings["profit_products"]
            if row["record_id"] == self.product_refund.id
        )
        self.assertEqual(product_row["units_positive"], 5.0)
        self.assertLess(product_row["gross_profit"], 5 * (80.0 - 30.0))

    def test_category_aggregation_combines_products(self):
        order, _session = self._create_paid_order(
            lines=[
                (self.product_high_vol, 3),
                (self.product_discounted, 2),
            ],
            uuid="perf-category-basic",
        )
        rankings = self._rankings_for_orders(order)
        basic_id = self.product_high_vol.categ_id.id
        basic_rows = [
            row for row in rankings["top_categories"] if row["record_id"] == basic_id
        ]
        self.assertEqual(len(basic_rows), 1)
        self.assertEqual(basic_rows[0]["units_positive"], 5.0)

    def test_period_filter_limits_orders(self):
        order, _session = self._create_paid_order(
            lines=[(self.product_high_vol, 1)],
            uuid="perf-period-old",
        )
        old_date = fields.Datetime.now() - timedelta(days=40)
        order.write({"date_order": old_date})
        dashboard = self.Performance.create({"period": "last_7"})
        windows = dashboard._period_windows("last_7")
        recent_orders = dashboard._paid_orders_between(*windows["data_current"])
        self.assertNotIn(order.id, recent_orders.ids)

    def test_performance_dashboard_populates_four_sections(self):
        self._create_paid_order(
            lines=[
                (self.product_high_vol, 4),
                (self.product_high_val, 1),
            ],
            uuid="perf-dashboard",
        )
        action = self.Performance.action_open_business_performance(period="today")
        dashboard = self.Performance.browse(action["res_id"])
        self.assertTrue(dashboard.top_product_line_ids)
        self.assertTrue(dashboard.profit_product_line_ids)
        self.assertEqual(
            dashboard.top_product_line_ids[0].section,
            "top_product",
        )
