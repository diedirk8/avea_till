# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import Command, fields
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaFinancialDrilldown(TestPoSCommon):
    """Drill-down reports reconcile to dashboard financial totals."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.config.write({"payment_method_ids": [(6, 0, cls.cash_pm1.ids)]})
        cls.Line = cls.env["pos.order.line"]
        cls.Overview = cls.env["avea.business.overview"]
        cls.Performance = cls.env["avea.business.performance"]
        cls.ProfitReport = cls.env["avea.profit.report"]
        cls.DiscountReport = cls.env["avea.discount.report"]

    def _create_paid_order(self, *, lines, uuid="drilldown", session=None, payments=None):
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

    def _open_profit_report(self, period="today"):
        overview = self.Overview.create({"period": period})
        action = overview.action_open_profit_report()
        return self.ProfitReport.browse(action["res_id"])

    def _open_discount_report(self, period="today"):
        overview = self.Overview.create({"period": period})
        action = overview.action_open_discount_report()
        return self.DiscountReport.browse(action["res_id"])

    def test_overview_matches_performance_for_periods(self):
        self._create_paid_order(
            lines=[(self.create_product("Drill Match", self.categ_basic, 120.0, 50.0), 1)],
            uuid="drill-match",
        )
        fields_to_check = [
            "sales_ex_tax",
            "cost_of_goods_sold",
            "gross_profit",
            "gross_margin_percent",
            "discounts_given",
        ]
        for period in ("today", "wtd", "mtd"):
            overview = self.Overview.create({"period": period})
            performance = self.Performance.create({"period": period})
            for field_name in fields_to_check:
                self.assertAlmostEqual(
                    getattr(overview, field_name),
                    getattr(performance, field_name),
                    places=2,
                    msg=f"{field_name} mismatch for {period}",
                )

    def test_profit_report_reconciles_to_dashboard(self):
        product = self.create_product("Drill Profit", self.categ_basic, 150.0, 100.0)
        self._create_paid_order(lines=[(product, 2)], uuid="drill-profit")
        overview = self.Overview.create({"period": "today"})
        report = self._open_profit_report("today")
        self.assertAlmostEqual(report.sales_ex_tax, overview.sales_ex_tax, places=2)
        self.assertAlmostEqual(report.cost_of_goods_sold, overview.cost_of_goods_sold, places=2)
        self.assertAlmostEqual(report.gross_profit, overview.gross_profit, places=2)
        line_sales = sum(report.line_ids.mapped("sales"))
        line_cogs = sum(report.line_ids.mapped("cost_total"))
        line_gp = sum(report.line_ids.mapped("gross_profit"))
        self.assertAlmostEqual(line_sales, report.sales_ex_tax, places=2)
        self.assertAlmostEqual(line_cogs, report.cost_of_goods_sold, places=2)
        self.assertAlmostEqual(line_gp, report.gross_profit, places=2)

    def test_discount_report_reconciles_to_dashboard(self):
        product = self.create_product("Drill Discount", self.categ_basic, 150.0, 100.0)
        self._create_paid_order(
            lines=[
                {
                    "product": product,
                    "quantity": 1,
                    "price_unit": 130.0,
                    "price_subtotal": 130.0,
                    "price_subtotal_incl": 130.0,
                }
            ],
            uuid="drill-discount",
        )
        overview = self.Overview.create({"period": "today"})
        report = self._open_discount_report("today")
        self.assertAlmostEqual(report.discounts_given, overview.discounts_given, places=2)
        self.assertAlmostEqual(
            sum(report.line_ids.mapped("discount_amount")),
            report.discounts_given,
            places=2,
        )

    def test_manual_discount_reason(self):
        product = self.create_product("Drill Manual", self.categ_basic, 100.0, 40.0)
        order, _session = self._create_paid_order(
            lines=[
                {
                    "product": product,
                    "quantity": 1,
                    "price_unit": 80.0,
                    "price_subtotal": 80.0,
                    "price_subtotal_incl": 80.0,
                    "discount": 20.0,
                }
            ],
            uuid="drill-manual",
        )
        line = order.lines[0]
        self.assertEqual(self.Line._avea_discount_reason_label(line), "Manual discount")
        report = self._open_discount_report("today")
        reason = report.line_ids.filtered(lambda row: row.pos_line_id == line).discount_reason
        self.assertEqual(reason, "Manual discount")

    def test_promotion_discount_reason(self):
        product = self.create_product("Drill Promo", self.categ_basic, 100.0, 40.0)
        order, _session = self._create_paid_order(lines=[(product, 1)], uuid="drill-promo-sale")
        line = order.lines[0]
        line.write({"is_reward_line": True})
        self.assertEqual(self.Line._avea_discount_reason_label(line), "Promotion")
        report = self._open_discount_report("today")
        reason = report.line_ids.filtered(lambda row: row.pos_line_id == line).discount_reason
        self.assertEqual(reason, "Promotion")

    def test_combo_price_discount_reason(self):
        product_a = self.create_product("Drill Combo A", self.categ_basic, 100.0, 40.0)
        product_b = self.create_product("Drill Combo B", self.categ_basic, 80.0, 30.0)
        promotion = self.env["avea.promotion"].create(
            {
                "name": "Drill Combo Price",
                "deal_type": "combo_price",
                "open_ended": True,
                "combo_price": 150.0,
                "combo_line_ids": [
                    Command.create({"product_id": product_a.id, "quantity": 1.0}),
                    Command.create({"product_id": product_b.id, "quantity": 1.0}),
                ],
            }
        )
        program = promotion.program_id
        discount_product = program.reward_ids.discount_line_product_id[:1]
        session = self.open_new_session(0)
        line_cmds = []
        catalog_incl = 0.0
        for combo_line in promotion.combo_line_ids:
            product = combo_line.product_id
            subtotal = product.lst_price * combo_line.quantity
            incl = subtotal
            catalog_incl += incl
            line_cmds.append(
                Command.create(
                    {
                        "product_id": product.id,
                        "qty": combo_line.quantity,
                        "price_unit": product.lst_price,
                        "price_subtotal": subtotal,
                        "price_subtotal_incl": incl,
                        "price_type": "manual",
                    }
                )
            )
        discount_incl = catalog_incl - promotion.combo_price
        line_cmds.append(
            Command.create(
                {
                    "product_id": discount_product.id,
                    "qty": 1,
                    "price_unit": -discount_incl,
                    "price_subtotal": -discount_incl,
                    "price_subtotal_incl": -discount_incl,
                    "price_type": "manual",
                    "full_product_name": promotion.name,
                    "avea_combo_program_id": program.id,
                }
            )
        )
        order = self.env["pos.order"].create(
            {
                "session_id": session.id,
                "config_id": self.config.id,
                "company_id": self.env.company.id,
                "uuid": "drill-combo",
                "amount_tax": 0.0,
                "amount_total": 0.0,
                "amount_paid": 0.0,
                "amount_return": 0.0,
                "lines": line_cmds,
            }
        )
        amount_total = sum(order.lines.mapped("price_subtotal_incl"))
        order.write(
            {
                "amount_total": amount_total,
                "amount_tax": 0.0,
                "amount_paid": amount_total,
            }
        )
        self.env["pos.payment"].create(
            {
                "pos_order_id": order.id,
                "amount": amount_total,
                "payment_method_id": self.cash_pm1.id,
                "session_id": session.id,
            }
        )
        order.action_pos_order_paid()
        combo_line = order.lines.filtered("avea_combo_program_id")
        self.assertEqual(self.Line._avea_discount_reason_label(combo_line), "Combo Price")
        report = self._open_discount_report("today")
        reason = report.line_ids.filtered(lambda row: row.pos_line_id == combo_line).discount_reason
        self.assertEqual(reason, "Combo Price")

    def test_historical_cost_and_retail_remain_on_drilldown(self):
        product = self.create_product("Drill Historical", self.categ_basic, 150.0, 100.0)
        order, _session = self._create_paid_order(lines=[(product, 1)], uuid="drill-historical")
        line = order.lines[0]
        before = self.Line._avea_performance_line_metrics(line)
        product.product_tmpl_id.write(
            {
                "avea_cost_ex_tax": 500.0,
                "list_price": 500.0,
                "standard_price": 500.0,
            }
        )
        after = self.Line._avea_performance_line_metrics(line)
        self.assertEqual(before, after)
        report = self._open_profit_report("today")
        row = report.line_ids.filtered(lambda record: record.pos_line_id == line)
        self.assertAlmostEqual(row.sales, before["revenue_ex_tax"], places=2)
        self.assertAlmostEqual(row.cost_total, before["cost_total"], places=2)

    def test_refund_and_zero_price_in_profit_report(self):
        product = self.create_product("Drill Refund", self.categ_basic, 80.0, 30.0)
        order_sale, session = self._create_paid_order(
            lines=[(product, 2)],
            uuid="drill-refund-sale",
        )
        order_refund, _session = self._create_paid_order(
            lines=[(product, -1)],
            uuid="drill-refund-return",
            session=session,
        )
        zero_product = self.create_product("Drill Zero", self.categ_basic, 0.0, 10.0)
        self._create_paid_order(lines=[(zero_product, 1)], uuid="drill-zero", session=session)
        overview = self.Overview.create({"period": "today"})
        report = self._open_profit_report("today")
        self.assertAlmostEqual(report.gross_profit, overview.gross_profit, places=2)
        self.assertTrue(any(row.quantity < 0 for row in report.line_ids))
        self.assertTrue(any(row.sales == 0.0 for row in report.line_ids))

    def test_period_filter_excludes_old_orders(self):
        product = self.create_product("Drill Period", self.categ_basic, 50.0, 20.0)
        order, _session = self._create_paid_order(lines=[(product, 1)], uuid="drill-period-old")
        order.write({"date_order": fields.Datetime.now() - timedelta(days=20)})
        self._create_paid_order(lines=[(product, 1)], uuid="drill-period-new")
        report_last_7 = self._open_profit_report("last_7")
        report_last_30 = self._open_profit_report("last_30")
        self.assertEqual(len(report_last_7.line_ids), 1)
        self.assertEqual(len(report_last_30.line_ids), 2)

    def test_profit_report_back_to_performance(self):
        performance = self.Performance.create({"period": "mtd"})
        action = performance.action_open_profit_report()
        report = self.ProfitReport.browse(action["res_id"])
        back = report.action_back()
        self.assertEqual(back["res_model"], "avea.business.performance")
        reopened = self.Performance.browse(back["res_id"])
        self.assertEqual(reopened.period, "mtd")
