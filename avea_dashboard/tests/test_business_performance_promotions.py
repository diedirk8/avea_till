# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till", "avea_promo_perf")
class TestAveaBusinessPerformancePromotions(TestPoSCommon):
    """Promotions analysis on the Business Performance workspace."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.config.write({"payment_method_ids": [(6, 0, cls.cash_pm1.ids)]})
        cls.Line = cls.env["pos.order.line"]
        cls.Performance = cls.env["avea.business.performance"]
        cls.Promotion = cls.env["avea.promotion"]
        cls.product_a = cls.create_product("Promo Biscuit A", cls.categ_basic, 100.0, 40.0)
        cls.product_b = cls.create_product("Promo Biscuit B", cls.categ_basic, 80.0, 30.0)
        cls.product_plain = cls.create_product("Full Price Kibble", cls.categ_basic, 50.0, 20.0)

    def _create_paid_order(self, *, lines, uuid="perf-promo", session=None):
        if session is None:
            session = self.open_new_session(0)
        total = 0.0
        for param in lines:
            if isinstance(param, dict):
                total += param.get("price_subtotal_incl") or param.get("price_subtotal") or 0.0
            else:
                total += param[0].lst_price * param[1]
        order_data = self.create_ui_order_data(
            pos_order_lines_ui_args=lines,
            payments=[(self.cash_pm1, total)],
            uuid=uuid,
        )
        sync_result = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(sync_result["pos.order"][0]["id"])
        return order, session

    def _add_reward_line(self, order, *, product, program, amount, name, code="perf-promo-code"):
        product_line = order.lines.filtered(lambda line: line.product_id == product)[:1]
        if product_line and code:
            product_line.write({"reward_identifier_code": code})
        return self.env["pos.order.line"].create(
            {
                "order_id": order.id,
                "product_id": product.id,
                "name": name,
                "full_product_name": f"{name} on {product.name}",
                "is_reward_line": True,
                "reward_id": program.reward_ids[:1].id,
                "reward_identifier_code": code,
                "qty": 1.0,
                "price_unit": amount,
                "price_subtotal": amount,
                "price_subtotal_incl": amount,
            }
        )

    def test_no_promotions_in_period_hides_tables(self):
        self._create_paid_order(
            lines=[(self.product_plain, 1)],
            uuid="perf-promo-none",
        )
        dashboard = self.Performance.create({"period": "today"})
        self.assertFalse(dashboard.show_promotions)
        self.assertEqual(dashboard.promo_ticket_count, 0)
        self.assertFalse(dashboard.promotion_line_ids)
        self.assertFalse(dashboard.promotion_product_line_ids)

    def test_manual_discount_is_not_a_promotion(self):
        order, _session = self._create_paid_order(
            lines=[
                {
                    "product": self.product_plain,
                    "quantity": 1,
                    "price_unit": 40.0,
                    "price_subtotal": 40.0,
                    "price_subtotal_incl": 40.0,
                    "discount": 20.0,
                }
            ],
            uuid="perf-promo-manual",
        )
        analysis = self.Line._avea_promotion_analysis(order)
        self.assertEqual(analysis["summary"]["promotion_count"], 0)
        dashboard = self.Performance.create({"period": "today"})
        self.assertFalse(dashboard.show_promotions)

    def test_fixed_amount_promotion_lists_product_and_discount(self):
        promo = self.Promotion.create(
            {
                "name": "BarkVember biscuits",
                "deal_type": "fixed_amount",
                "discount_amount": 60.0,
                "product_scope": "products",
                "product_ids": [Command.set([self.product_a.id, self.product_b.id])],
                "open_ended": True,
            }
        )
        order, _session = self._create_paid_order(
            lines=[(self.product_a, 2)],
            uuid="perf-promo-fixed",
        )
        self._add_reward_line(
            order,
            product=self.product_a,
            program=promo.program_id,
            amount=-120.0,
            name="R 60.00 off each",
        )
        analysis = self.Line._avea_promotion_analysis(order)
        self.assertEqual(analysis["summary"]["promotion_count"], 1)
        self.assertEqual(analysis["summary"]["order_count"], 1)
        self.assertAlmostEqual(analysis["summary"]["discount_given"], 120.0, places=2)
        self.assertGreater(analysis["summary"]["unit_count"], 0.0)
        promo_row = analysis["promotions"][0]
        self.assertEqual(promo_row["promotion_id"], promo.id)
        self.assertEqual(promo_row["name"], "BarkVember biscuits")
        self.assertIn("off each", promo_row["deal_summary"])
        self.assertAlmostEqual(promo_row["discount_given"], 120.0, places=2)
        self.assertNotEqual(promo_row["discount_display"], "Fixed amount off")
        product_row = next(
            row for row in analysis["products"] if row["product_id"] == self.product_a.id
        )
        self.assertEqual(product_row["promotion_name"], "BarkVember biscuits")
        self.assertAlmostEqual(product_row["quantity"], 2.0, places=2)
        self.assertAlmostEqual(product_row["discount_given"], 120.0, places=2)

        dashboard = self.Performance.create({"period": "today"})
        self.assertTrue(dashboard.show_promotions)
        self.assertEqual(dashboard.promo_ticket_count, 1)
        self.assertAlmostEqual(dashboard.promo_discount, 120.0, places=2)
        self.assertEqual(dashboard.promotion_line_ids.name, "BarkVember biscuits")
        self.assertIn(self.product_a.name, dashboard.promotion_product_line_ids.mapped("product_display"))

    def test_combo_price_shows_type_and_component_products(self):
        promo = self.Promotion.create(
            {
                "name": "Weekend combo",
                "deal_type": "combo_price",
                "open_ended": True,
                "combo_price": 150.0,
                "combo_line_ids": [
                    Command.create({"product_id": self.product_a.id, "quantity": 1.0}),
                    Command.create({"product_id": self.product_b.id, "quantity": 1.0}),
                ],
            }
        )
        program = promo.program_id
        discount_product = program.reward_ids.discount_line_product_id[:1]
        session = self.open_new_session(0)
        line_cmds = []
        catalog = 0.0
        for combo_line in promo.combo_line_ids:
            product = combo_line.product_id
            subtotal = product.lst_price * combo_line.quantity
            catalog += subtotal
            line_cmds.append(
                Command.create(
                    {
                        "product_id": product.id,
                        "qty": combo_line.quantity,
                        "price_unit": product.lst_price,
                        "price_subtotal": subtotal,
                        "price_subtotal_incl": subtotal,
                        "price_type": "manual",
                    }
                )
            )
        discount_incl = catalog - promo.combo_price
        line_cmds.append(
            Command.create(
                {
                    "product_id": discount_product.id,
                    "qty": 1,
                    "price_unit": -discount_incl,
                    "price_subtotal": -discount_incl,
                    "price_subtotal_incl": -discount_incl,
                    "price_type": "manual",
                    "full_product_name": promo.name,
                    "avea_combo_program_id": program.id,
                }
            )
        )
        order = self.env["pos.order"].create(
            {
                "session_id": session.id,
                "config_id": self.config.id,
                "company_id": self.env.company.id,
                "uuid": "perf-promo-combo",
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

        analysis = self.Line._avea_promotion_analysis(order)
        self.assertEqual(analysis["summary"]["promotion_count"], 1)
        promo_row = analysis["promotions"][0]
        self.assertEqual(promo_row["name"], "Weekend combo")
        self.assertEqual(promo_row["deal_type_label"], "Combo Price")
        self.assertAlmostEqual(promo_row["discount_given"], discount_incl, places=2)
        product_ids = {row["product_id"] for row in analysis["products"]}
        self.assertIn(self.product_a.id, product_ids)
        self.assertIn(self.product_b.id, product_ids)

        dashboard = self.Performance.create({"period": "today"})
        self.assertTrue(dashboard.show_promotions)
        self.assertAlmostEqual(dashboard.promo_discount, discount_incl, places=2)

    def test_extra_loyalty_points_shows_type_when_no_discount(self):
        promo = self.Promotion.create(
            {
                "name": "Double stamps",
                "deal_type": "extra_loyalty_points",
                "loyalty_points": 2,
                "loyalty_points_mode": "order",
                "product_scope": "products",
                "product_ids": [Command.set([self.product_a.id])],
                "open_ended": True,
            }
        )
        order, _session = self._create_paid_order(
            lines=[(self.product_a, 1)],
            uuid="perf-promo-points",
        )
        self._add_reward_line(
            order,
            product=self.product_a,
            program=promo.program_id,
            amount=0.0,
            name="Extra loyalty points",
        )
        analysis = self.Line._avea_promotion_analysis(order)
        self.assertEqual(analysis["summary"]["promotion_count"], 1)
        self.assertAlmostEqual(analysis["summary"]["discount_given"], 0.0, places=2)
        promo_row = analysis["promotions"][0]
        self.assertEqual(promo_row["deal_type_label"], "Extra Loyalty Points")
        self.assertEqual(promo_row["discount_display"], "Extra Loyalty Points")
        product_row = analysis["products"][0]
        self.assertEqual(product_row["product_id"], self.product_a.id)
        self.assertEqual(product_row["discount_display"], "Extra Loyalty Points")

        dashboard = self.Performance.create({"period": "today"})
        self.assertTrue(dashboard.show_promotions)
        self.assertEqual(dashboard.promotion_line_ids.discount_display, "Extra Loyalty Points")

    def test_unrelated_ticket_products_are_not_attributed(self):
        promo = self.Promotion.create(
            {
                "name": "Biscuits only",
                "deal_type": "fixed_amount",
                "discount_amount": 60.0,
                "product_scope": "products",
                "product_ids": [Command.set([self.product_a.id])],
                "open_ended": True,
            }
        )
        order, _session = self._create_paid_order(
            lines=[(self.product_a, 1), (self.product_plain, 1)],
            uuid="perf-promo-scope",
        )
        self._add_reward_line(
            order,
            product=self.product_a,
            program=promo.program_id,
            amount=-60.0,
            name="R 60.00 off each",
            code="",
        )
        analysis = self.Line._avea_promotion_analysis(order)
        product_ids = {row["product_id"] for row in analysis["products"]}
        self.assertEqual(product_ids, {self.product_a.id})
        self.assertAlmostEqual(analysis["promotions"][0]["discount_given"], 60.0, places=2)
