# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaPerformanceProfitCogs(TestPoSCommon):
    """Gross profit uses historical POS line cost (total_cost), not avea_cost_ex_tax."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.config.write({"payment_method_ids": [(6, 0, cls.cash_pm1.ids)]})
        cls.Line = cls.env["pos.order.line"]

    def _create_paid_order(self, *, lines, uuid="profit-cogs", session=None, payments=None):
        if session is None:
            session = self.open_new_session(0)
        if payments is None:
            total = sum(
                param[2]["price_subtotal_incl"]
                if isinstance(param, dict)
                else param[0].lst_price * param[1]
                for param in lines
            )
            payments = [(self.cash_pm1, total)]
        order_data = self.create_ui_order_data(
            pos_order_lines_ui_args=lines,
            payments=payments,
            uuid=uuid,
        )
        sync_result = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(sync_result["pos.order"][0]["id"])
        self.assertIn(order.state, self.env["pos.session"]._avea_paid_order_states())
        return order, session

    def _line_metrics(self, line):
        return self.Line._avea_performance_line_metrics(line)

    def test_basic_profit_uses_historical_pos_cost(self):
        """A) Buy R100, sell R140 → gross profit R40."""
        product = self.create_product("GP Basic", self.categ_basic, 140.0, 100.0)
        product.product_tmpl_id.avea_cost_ex_tax = 100.0
        order, _session = self._create_paid_order(
            lines=[(product, 1)],
            uuid="gp-basic",
        )
        metrics = self._line_metrics(order.lines[0])
        self.assertAlmostEqual(metrics["revenue_ex_tax"], 140.0, places=2)
        self.assertAlmostEqual(metrics["cost_total"], 100.0, places=2)
        self.assertAlmostEqual(metrics["gross_profit"], 40.0, places=2)
        self.assertAlmostEqual(order.lines[0].margin, 40.0, places=2)

    def test_later_cost_change_does_not_rewrite_first_sale(self):
        """B) First sale GP R40 stays R40 after product cost rises to R120; second sale GP R30."""
        product = self.create_product("GP History", self.categ_basic, 140.0, 100.0)
        template = product.product_tmpl_id
        template.avea_cost_ex_tax = 100.0

        order1, session = self._create_paid_order(
            lines=[(product, 1)],
            uuid="gp-history-1",
        )
        line1 = order1.lines[0]
        self.assertAlmostEqual(self._line_metrics(line1)["gross_profit"], 40.0, places=2)

        template.write({"standard_price": 120.0, "avea_cost_ex_tax": 999.0, "list_price": 150.0})
        product.invalidate_recordset()
        template.invalidate_recordset()
        line1.invalidate_recordset()

        self.assertAlmostEqual(self._line_metrics(line1)["gross_profit"], 40.0, places=2)

        order2, _session = self._create_paid_order(
            lines=[(product, 1)],
            uuid="gp-history-2",
            session=session,
        )
        line2 = order2.lines[0]
        self.assertAlmostEqual(self._line_metrics(line2)["revenue_ex_tax"], 150.0, places=2)
        self.assertAlmostEqual(self._line_metrics(line2)["cost_total"], 120.0, places=2)
        self.assertAlmostEqual(self._line_metrics(line2)["gross_profit"], 30.0, places=2)

    def test_zero_price_sale_negative_gross_profit(self):
        """C) Cost R100, sell R0 → gross profit -R100."""
        product = self.create_product("GP Zero", self.categ_basic, 100.0, 100.0)
        product.product_tmpl_id.avea_cost_ex_tax = 100.0
        order, _session = self._create_paid_order(
            lines=[
                {
                    "product": product,
                    "quantity": 1,
                    "price_unit": 0.0,
                    "price_subtotal": 0.0,
                    "price_subtotal_incl": 0.0,
                }
            ],
            uuid="gp-zero",
            payments=[(self.cash_pm1, 0.0)],
        )
        metrics = self._line_metrics(order.lines[0])
        self.assertAlmostEqual(metrics["revenue_ex_tax"], 0.0, places=2)
        self.assertAlmostEqual(metrics["cost_total"], 100.0, places=2)
        self.assertAlmostEqual(metrics["gross_profit"], -100.0, places=2)

    def test_refund_reduces_revenue_and_cogs(self):
        """D) Refunds reduce net gross profit."""
        product = self.create_product("GP Refund", self.categ_basic, 80.0, 30.0)
        product.product_tmpl_id.avea_cost_ex_tax = 30.0
        order_sale, session = self._create_paid_order(
            lines=[(product, 5)],
            uuid="gp-refund-sale",
        )
        sale_metrics = self._line_metrics(order_sale.lines[0])
        self.assertAlmostEqual(sale_metrics["gross_profit"], 5 * (80.0 - 30.0), places=2)

        order_refund, _session = self._create_paid_order(
            lines=[(product, -2)],
            uuid="gp-refund-return",
            session=session,
        )
        rankings = self.Line._avea_performance_rankings(order_sale | order_refund)
        product_row = next(
            row for row in rankings["profit_products"] if row["record_id"] == product.id
        )
        self.assertEqual(product_row["units_positive"], 5.0)
        self.assertAlmostEqual(product_row["gross_profit"], 3 * (80.0 - 30.0), places=2)

    def test_discount_reduces_revenue_not_historical_cost(self):
        """E) Discount lowers revenue; COGS unchanged on the line."""
        product = self.create_product("GP Discount", self.categ_basic, 100.0, 40.0)
        product.product_tmpl_id.avea_cost_ex_tax = 40.0
        order, _session = self._create_paid_order(
            lines=[(product, 1)],
            uuid="gp-discount-base",
        )
        line = order.lines[0]
        baseline = self._line_metrics(line)
        line.write({"discount": 20.0, "price_subtotal": baseline["revenue_ex_tax"] * 0.8})
        discounted = self._line_metrics(line)
        self.assertLess(discounted["revenue_ex_tax"], baseline["revenue_ex_tax"])
        self.assertAlmostEqual(discounted["cost_total"], baseline["cost_total"], places=2)
        self.assertLess(discounted["gross_profit"], baseline["gross_profit"])

    def test_aggregate_matches_sum_of_pos_line_margins(self):
        """F) Period totals align with native Odoo POS margin on the same orders."""
        products = [
            self.create_product(f"GP Hist {idx}", self.categ_basic, 50.0 + idx, 20.0 + idx)
            for idx in range(3)
        ]
        order, _session = self._create_paid_order(
            lines=[(products[0], 2), (products[1], 1), (products[2], 3)],
            uuid="gp-aggregate",
        )
        lines = self.Line._avea_performance_lines_for_orders(order)
        expected_gp = sum(lines.mapped("margin"))
        expected_rev = sum(lines.mapped("price_subtotal"))
        rankings = self.Line._avea_performance_rankings(order)
        actual_gp = sum(row["gross_profit"] for row in rankings["profit_products"])
        actual_rev = sum(row["revenue_ex_tax"] for row in rankings["top_products"])
        self.assertAlmostEqual(actual_gp, expected_gp, places=2)
        self.assertAlmostEqual(actual_rev, expected_rev, places=2)

    def test_avea_cost_change_does_not_affect_reported_cogs(self):
        """G) avea_cost_ex_tax remains for Stock; profit reporting ignores later edits."""
        product = self.create_product("GP Avea Cost", self.categ_basic, 200.0, 50.0)
        template = product.product_tmpl_id
        template.avea_cost_ex_tax = 50.0
        order, _session = self._create_paid_order(
            lines=[(product, 1)],
            uuid="gp-avea-cost",
        )
        line = order.lines[0]
        before = self._line_metrics(line)
        template.avea_cost_ex_tax = 500.0
        template.invalidate_recordset()
        line.invalidate_recordset()
        after = self._line_metrics(line)
        self.assertAlmostEqual(after["cost_total"], before["cost_total"], places=2)
        self.assertAlmostEqual(after["gross_profit"], before["gross_profit"], places=2)
        self.assertAlmostEqual(template._avea_get_cost_ex_tax(), 500.0, places=2)
