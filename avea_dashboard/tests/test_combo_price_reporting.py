# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaComboPriceReporting(TestPoSCommon):
    """Combo Price promotion end-to-end: promotion setup, POS order, Discounts Given."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.config.write({"payment_method_ids": [(6, 0, cls.cash_pm1.ids)]})
        cls.Line = cls.env["pos.order.line"]
        cls.Promotion = cls.env["avea.promotion"]
        cls.product_a = cls.create_product("Combo A", cls.categ_basic, 100.0, 40.0)
        cls.product_b = cls.create_product("Combo B", cls.categ_basic, 80.0, 30.0)
        cls.promotion = cls.Promotion.create(
            {
                "name": "QA Combo Price Reporting",
                "deal_type": "combo_price",
                "open_ended": True,
                "combo_price": 150.0,
                "combo_line_ids": [
                    Command.create(
                        {"product_id": cls.product_a.id, "quantity": 1.0}
                    ),
                    Command.create(
                        {"product_id": cls.product_b.id, "quantity": 1.0}
                    ),
                ],
            }
        )
        cls.program = cls.promotion.program_id
        cls.discount_product = cls.program.reward_ids.discount_line_product_id[:1]

    def _line_amounts(self, product, qty, price_unit):
        taxes = product.taxes_id
        currency = self.env.company.currency_id
        if taxes:
            result = taxes.compute_all(price_unit, currency, qty, product=product)
            return result["total_excluded"], result["total_included"]
        return price_unit * qty, price_unit * qty

    def _create_combo_paid_order(self, *, uuid="combo-report", session=None):
        """Paid POS order with component lines at retail plus Combo Price discount line."""
        self.assertTrue(self.program.avea_is_combo)
        self.assertAlmostEqual(self.program.avea_combo_price, 150.0, places=2)
        if session is None:
            session = self.open_new_session(0)

        line_cmds = []
        catalog_ex = 0.0
        catalog_incl = 0.0
        for combo_line in self.promotion.combo_line_ids:
            product = combo_line.product_id
            sub, incl = self._line_amounts(product, combo_line.quantity, product.lst_price)
            catalog_ex += sub
            catalog_incl += incl
            line_cmds.append(
                Command.create(
                    {
                        "product_id": product.id,
                        "qty": combo_line.quantity,
                        "price_unit": product.lst_price,
                        "price_subtotal": sub,
                        "price_subtotal_incl": incl,
                        "price_type": "manual",
                    }
                )
            )

        combo_incl = self.promotion.combo_price
        discount_incl = self.env.company.currency_id.round(catalog_incl - combo_incl)
        self.assertGreater(discount_incl, 0.0)
        disc_sub, disc_incl = self._line_amounts(
            self.discount_product, 1, -discount_incl
        )
        line_cmds.append(
            Command.create(
                {
                    "product_id": self.discount_product.id,
                    "qty": 1,
                    "price_unit": -discount_incl,
                    "price_subtotal": disc_sub,
                    "price_subtotal_incl": disc_incl,
                    "price_type": "manual",
                    "full_product_name": self.promotion.name,
                    "avea_combo_program_id": self.program.id,
                    "is_reward_line": False,
                }
            )
        )

        order = self.env["pos.order"].create(
            {
                "session_id": session.id,
                "config_id": self.config.id,
                "company_id": self.env.company.id,
                "uuid": uuid,
                "amount_tax": 0.0,
                "amount_total": 0.0,
                "amount_paid": 0.0,
                "amount_return": 0.0,
                "lines": line_cmds,
            }
        )
        amount_total = sum(order.lines.mapped("price_subtotal_incl"))
        amount_tax = sum(
            line.price_subtotal_incl - line.price_subtotal for line in order.lines
        )
        order.write(
            {
                "amount_total": amount_total,
                "amount_tax": amount_tax,
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
        self.assertIn(order.state, self.env["pos.session"]._avea_paid_order_states())
        return order, session

    def test_combo_price_promotion_sync_and_discounts_given(self):
        """G) Combo Price: catalog R180, combo R150 → net sales R150, discounts R30."""
        order, _session = self._create_combo_paid_order(uuid="combo-report-main")
        component_lines = order.lines.filtered(
            lambda line: line.product_id.type not in ("service",)
            and not line.avea_combo_program_id
        )
        combo_line = order.lines.filtered("avea_combo_program_id")
        self.assertEqual(len(component_lines), 2)
        self.assertEqual(len(combo_line), 1)

        catalog_ex = sum(component_lines.mapped("price_subtotal"))
        expected_discount = catalog_ex - self.promotion.combo_price
        financial = self.Line._avea_performance_financial_summary(order)
        self.assertAlmostEqual(catalog_ex, 180.0, places=2)
        self.assertAlmostEqual(expected_discount, 30.0, places=2)
        self.assertAlmostEqual(financial["revenue_ex_tax"], 150.0, places=2)
        self.assertAlmostEqual(financial["discounts_given"], 30.0, places=2)
        self.assertAlmostEqual(
            financial["gross_profit"],
            financial["revenue_ex_tax"] - financial["cost_total"],
            places=2,
        )
        self.assertAlmostEqual(combo_line._avea_discount_given_ex_tax(), 30.0, places=2)
        for line in component_lines:
            self.assertAlmostEqual(line._avea_discount_given_ex_tax(), 0.0, places=2)

    def test_combo_price_refund_reverses_discount(self):
        """Combo refund reverses net sales and discounts given."""
        order_sale, session = self._create_combo_paid_order(uuid="combo-report-sale")
        sale = self.Line._avea_performance_financial_summary(order_sale)

        refund_cmds = []
        for src in order_sale.lines:
            sub, incl = self._line_amounts(src.product_id, -src.qty, src.price_unit)
            refund_cmds.append(
                Command.create(
                    {
                        "product_id": src.product_id.id,
                        "qty": -src.qty,
                        "price_unit": src.price_unit,
                        "price_subtotal": sub,
                        "price_subtotal_incl": incl,
                        "price_type": "manual",
                        "full_product_name": src.full_product_name,
                        "avea_combo_program_id": src.avea_combo_program_id,
                        "is_reward_line": False,
                    }
                )
            )
        order_refund = self.env["pos.order"].create(
            {
                "session_id": session.id,
                "config_id": self.config.id,
                "company_id": self.env.company.id,
                "uuid": "combo-report-refund",
                "amount_tax": 0.0,
                "amount_total": 0.0,
                "amount_paid": 0.0,
                "amount_return": 0.0,
                "lines": refund_cmds,
            }
        )
        amount_total = sum(order_refund.lines.mapped("price_subtotal_incl"))
        order_refund.write(
            {
                "amount_total": amount_total,
                "amount_tax": 0.0,
                "amount_paid": amount_total,
            }
        )
        self.env["pos.payment"].create(
            {
                "pos_order_id": order_refund.id,
                "amount": amount_total,
                "payment_method_id": self.cash_pm1.id,
                "session_id": session.id,
            }
        )
        order_refund.action_pos_order_paid()

        combined = self.Line._avea_performance_financial_summary(
            order_sale | order_refund
        )
        self.assertAlmostEqual(combined["revenue_ex_tax"], 0.0, places=2)
        self.assertAlmostEqual(combined["discounts_given"], 0.0, places=2)
        self.assertGreater(sale["discounts_given"], 0.0)
