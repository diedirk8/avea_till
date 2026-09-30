# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaBusinessPlatformReporting(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        manager_group = cls.env.ref("avea_till.group_avea_manager")
        cls.env.user.write({"group_ids": [(4, manager_group.id)]})
        cls.config = cls.basic_config
        cls.config.write({"payment_method_ids": [(6, 0, cls.cash_pm1.ids)]})
        cls.Overview = cls.env["avea.business.overview"]
        cls.Performance = cls.env["avea.business.performance"]
        cls.Platform = cls.env["avea.sales.platform"]
        cls.product = cls.create_product("Platform Report Product", cls.categ_basic, 150.0, 100.0)

    def _create_platform(self):
        return self.Platform.create(
            {
                "name": "Reporting Platform",
                "commission_percent": 10.0,
                "commission_vat": False,
                "price_rounding_rule": "none",
            }
        )

    def _create_paid_order(self, *, pricelist=None, uuid="platform-report", session=None):
        if session is None:
            session = self.open_new_session(0)
        lines = [(self.product, 1)]
        order_data = self.create_ui_order_data(
            pos_order_lines_ui_args=lines,
            payments=[(self.cash_pm1, self.product.lst_price)],
            uuid=uuid,
        )
        sync_result = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(sync_result["pos.order"][0]["id"])
        if pricelist:
            order.write({"pricelist_id": pricelist.id})
        return order, session

    def test_no_platform_activity_hides_section(self):
        self._create_paid_order(uuid="retail-only")
        overview = self.Overview.create({"period": "today"})
        performance = self.Performance.create({"period": "today"})
        self.assertFalse(overview.show_platform_reporting)
        self.assertFalse(overview.platform_line_ids)
        self.assertFalse(performance.show_platform_reporting)
        self.assertFalse(performance.platform_line_ids)

    def test_platform_sale_surfaces_same_metrics_on_overview_and_performance(self):
        platform = self._create_platform()
        self._create_paid_order(pricelist=platform.pricelist_id, uuid="platform-sale")
        overview = self.Overview.create({"period": "today"})
        performance = self.Performance.create({"period": "today"})
        self.assertTrue(overview.show_platform_reporting)
        self.assertTrue(performance.show_platform_reporting)
        self.assertEqual(len(overview.platform_line_ids), 1)
        self.assertEqual(len(performance.platform_line_ids), 1)
        o_line = overview.platform_line_ids[0]
        p_line = performance.platform_line_ids[0]
        self.assertEqual(o_line.platform_id, platform)
        self.assertEqual(p_line.platform_id, platform)
        self.assertAlmostEqual(o_line.sales_ex_tax, 150.0, places=2)
        self.assertAlmostEqual(p_line.sales_ex_tax, 150.0, places=2)
        self.assertAlmostEqual(o_line.cost_total, 100.0, places=2)
        self.assertAlmostEqual(o_line.gross_profit, 50.0, places=2)
        self.assertAlmostEqual(o_line.commission, 15.0, places=2)
        self.assertAlmostEqual(o_line.contribution, 35.0, places=2)
        self.assertAlmostEqual(overview.platform_sales_ex_tax, p_line.sales_ex_tax, places=2)
        self.assertAlmostEqual(overview.platform_contribution, performance.platform_contribution, places=2)

    def test_retail_totals_unchanged_with_platform_sale(self):
        platform = self._create_platform()
        self._create_paid_order(uuid="retail-mix")
        self._create_paid_order(pricelist=platform.pricelist_id, uuid="platform-mix")
        overview = self.Overview.create({"period": "today"})
        self.assertAlmostEqual(overview.sales_ex_tax, 300.0, places=2)
        self.assertAlmostEqual(overview.platform_sales_ex_tax, 150.0, places=2)
