# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaBusinessReportingFinancials(TestPoSCommon):
    """Unified profit and discount reporting for Overview and Performance."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.config.write({"payment_method_ids": [(6, 0, cls.cash_pm1.ids)]})
        cls.Line = cls.env["pos.order.line"]

    def _create_paid_order(self, *, lines, uuid="reporting", session=None, payments=None):
        if session is None:
            session = self.open_new_session(0)
        if payments is None:
            total = 0.0
            for param in lines:
                if isinstance(param, dict):
                    total += param.get("price_subtotal_incl", 0.0)
                else:
                    total += param[0].lst_price * param[1]
            payments = [(self.cash_pm1, total)]
        order_data = self.create_ui_order_data(
            pos_order_lines_ui_args=lines,
            payments=payments,
            uuid=uuid,
        )
        sync_result = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(sync_result["pos.order"][0]["id"])
        return order, session

    def _financial(self, orders):
        return self.Line._avea_performance_financial_summary(orders)

    def test_basic_profit_no_discount(self):
        """A) Cost R100, retail R150, sold R150 → GP R50, discount R0."""
        product = self.create_product("Report Basic", self.categ_basic, 150.0, 100.0)
        product.product_tmpl_id.avea_cost_ex_tax = 100.0
        order, _session = self._create_paid_order(lines=[(product, 1)], uuid="report-basic")
        line = order.lines[0]
        self.assertAlmostEqual(line.avea_retail_unit_ex_tax, 150.0, places=2)
        financial = self._financial(order)
        self.assertAlmostEqual(financial["revenue_ex_tax"], 150.0, places=2)
        self.assertAlmostEqual(financial["cost_total"], 100.0, places=2)
        self.assertAlmostEqual(financial["gross_profit"], 50.0, places=2)
        self.assertAlmostEqual(financial["discounts_given"], 0.0, places=2)

    def test_discounted_sale(self):
        """B) Cost R100, retail R150, sold R130 → GP R30, discount R20."""
        product = self.create_product("Report Discount", self.categ_basic, 150.0, 100.0)
        order, _session = self._create_paid_order(
            lines=[
                {
                    "product": product,
                    "quantity": 1,
                    "price_unit": 130.0,
                    "price_subtotal": 130.0,
                    "price_subtotal_incl": 130.0,
                }
            ],
            uuid="report-discount",
        )
        line = order.lines[0]
        self.assertAlmostEqual(line.avea_retail_unit_ex_tax, 150.0, places=2)
        financial = self._financial(order)
        self.assertAlmostEqual(financial["revenue_ex_tax"], 130.0, places=2)
        self.assertAlmostEqual(financial["gross_profit"], 30.0, places=2)
        self.assertAlmostEqual(financial["discounts_given"], 20.0, places=2)

    def test_historical_cost_change(self):
        """C) First sale GP R50 stays after product cost rises."""
        product = self.create_product("Report Cost", self.categ_basic, 150.0, 100.0)
        template = product.product_tmpl_id
        order1, session = self._create_paid_order(lines=[(product, 1)], uuid="report-cost-1")
        self.assertAlmostEqual(self._financial(order1)["gross_profit"], 50.0, places=2)

        template.write({"standard_price": 120.0, "avea_cost_ex_tax": 120.0})
        order2, _session = self._create_paid_order(
            lines=[(product, 1)],
            uuid="report-cost-2",
            session=session,
        )
        self.assertAlmostEqual(self._financial(order1)["gross_profit"], 50.0, places=2)
        self.assertAlmostEqual(self._financial(order2)["gross_profit"], 30.0, places=2)

    def test_historical_retail_change(self):
        """D) Discount R20 stays after retail price rises."""
        product = self.create_product("Report Retail", self.categ_basic, 150.0, 100.0)
        order, _session = self._create_paid_order(
            lines=[
                {
                    "product": product,
                    "quantity": 1,
                    "price_unit": 130.0,
                    "price_subtotal": 130.0,
                    "price_subtotal_incl": 130.0,
                }
            ],
            uuid="report-retail",
        )
        before = self._financial(order)["discounts_given"]
        product.product_tmpl_id.list_price = 170.0
        order.lines.invalidate_recordset()
        after = self._financial(order)["discounts_given"]
        self.assertAlmostEqual(before, 20.0, places=2)
        self.assertAlmostEqual(after, 20.0, places=2)

    def test_zero_price_sale(self):
        """E) Cost R100, sold R0 → GP -R100."""
        product = self.create_product("Report Zero", self.categ_basic, 100.0, 100.0)
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
            uuid="report-zero",
            payments=[(self.cash_pm1, 0.0)],
        )
        financial = self._financial(order)
        self.assertAlmostEqual(financial["gross_profit"], -100.0, places=2)
        self.assertAlmostEqual(financial["discounts_given"], 100.0, places=2)

    def test_refund_reverses_financials(self):
        """F) Refunds reverse revenue, COGS, GP and discounts."""
        product = self.create_product("Report Refund", self.categ_basic, 150.0, 100.0)
        order_sale, session = self._create_paid_order(
            lines=[(product, 2)],
            uuid="report-refund-sale",
        )
        sale = self._financial(order_sale)
        order_refund, _session = self._create_paid_order(
            lines=[(product, -1)],
            uuid="report-refund-return",
            session=session,
        )
        combined = self._financial(order_sale | order_refund)
        self.assertAlmostEqual(combined["revenue_ex_tax"], 150.0, places=2)
        self.assertAlmostEqual(combined["cost_total"], 100.0, places=2)
        self.assertAlmostEqual(combined["gross_profit"], 50.0, places=2)
        self.assertAlmostEqual(combined["discounts_given"], 0.0, places=2)
        self.assertGreater(sale["revenue_ex_tax"], combined["revenue_ex_tax"])

    def test_manual_percent_discount(self):
        """Manual POS discount uses sale-time price_unit as normal retail."""
        product = self.create_product("Report Pct", self.categ_basic, 150.0, 100.0)
        order, _session = self._create_paid_order(lines=[(product, 1)], uuid="report-pct")
        line = order.lines[0]
        line.write({"discount": 20.0, "price_subtotal": 120.0, "price_subtotal_incl": 120.0})
        financial = self._financial(order)
        self.assertAlmostEqual(financial["revenue_ex_tax"], 120.0, places=2)
        self.assertAlmostEqual(financial["discounts_given"], 30.0, places=2)

    def test_avea_cost_unchanged_for_stock(self):
        """I) Reporting does not alter avea_cost_ex_tax."""
        product = self.create_product("Report Stock", self.categ_basic, 200.0, 50.0)
        template = product.product_tmpl_id
        template.avea_cost_ex_tax = 50.0
        self._create_paid_order(lines=[(product, 1)], uuid="report-stock")
        template.avea_cost_ex_tax = 88.0
        self.assertAlmostEqual(template._avea_get_cost_ex_tax(), 88.0, places=2)
