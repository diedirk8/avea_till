# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_till")
class TestAveaPromotionLoyaltyMapping(TransactionCase):
    """Product-scoped amount-off must apply to every matching unit, not once per ticket."""

    def _product(self, name, price=100.0):
        return self.env["product.product"].create(
            {
                "name": name,
                "lst_price": price,
                "sale_ok": True,
                "available_in_pos": True,
                "type": "consu",
            }
        )

    def _assert_specific_products(self, records, products):
        self.assertEqual(set(records.ids), set(products.ids))

    def test_fixed_amount_on_products_is_per_unit(self):
        product_a = self._product("Promo Biscuit A")
        product_b = self._product("Promo Biscuit B")
        promo = self.env["avea.promotion"].create(
            {
                "name": "BarkVember biscuits",
                "deal_type": "fixed_amount",
                "discount_amount": 60.0,
                "product_scope": "products",
                "product_ids": [Command.set([product_a.id, product_b.id])],
                "open_ended": True,
            }
        )
        rule = promo.program_id.rule_ids
        reward = promo.program_id.reward_ids
        self.assertEqual(len(rule), 1)
        self.assertEqual(len(reward), 1)
        self.assertEqual(rule.reward_point_mode, "unit")
        self.assertEqual(rule.reward_point_amount, 1.0)
        self.assertEqual(reward.discount_mode, "per_point")
        self.assertEqual(reward.discount, 60.0)
        self.assertEqual(reward.required_points, 1.0)
        self.assertEqual(reward.discount_applicability, "specific")
        self._assert_specific_products(rule.product_ids, product_a | product_b)
        self._assert_specific_products(reward.discount_product_ids, product_a | product_b)
        self.assertEqual(promo.apply_on, "product")
        self.assertEqual(promo.deal_summary, f"{promo.currency_id.symbol} 60.00 off each")

    def test_fixed_amount_on_all_products_stays_once_per_order(self):
        promo = self.env["avea.promotion"].create(
            {
                "name": "R20 off the ticket",
                "deal_type": "fixed_amount",
                "discount_amount": 20.0,
                "product_scope": "all",
                "open_ended": True,
            }
        )
        rule = promo.program_id.rule_ids
        reward = promo.program_id.reward_ids
        self.assertEqual(rule.reward_point_mode, "order")
        self.assertEqual(reward.discount_mode, "per_order")
        self.assertEqual(reward.discount, 20.0)
        self.assertEqual(reward.discount_applicability, "order")
        self.assertEqual(promo.apply_on, "ticket")
        self.assertEqual(promo.deal_summary, f"{promo.currency_id.symbol} 20.00 off the ticket")

    def test_fixed_amount_on_category_is_per_unit(self):
        category = self.env["product.category"].create({"name": "Promo biscuits"})
        promo = self.env["avea.promotion"].create(
            {
                "name": "Category amount off",
                "deal_type": "fixed_amount",
                "discount_amount": 15.0,
                "product_scope": "category",
                "product_category_id": category.id,
                "open_ended": True,
            }
        )
        self.assertEqual(promo.program_id.rule_ids.reward_point_mode, "unit")
        self.assertEqual(promo.program_id.reward_ids.discount_mode, "per_point")
        self.assertEqual(
            promo.program_id.reward_ids.discount_product_category_id,
            category,
        )

    def test_percent_off_on_products_uses_unit_points(self):
        product = self._product("Percent spray")
        promo = self.env["avea.promotion"].create(
            {
                "name": "15 percent spray",
                "deal_type": "percent_off",
                "discount_percent": 15.0,
                "product_scope": "products",
                "product_ids": [Command.set(product.ids)],
                "open_ended": True,
            }
        )
        rule = promo.program_id.rule_ids
        reward = promo.program_id.reward_ids
        self.assertEqual(rule.reward_point_mode, "unit")
        self.assertEqual(reward.discount_mode, "percent")
        self.assertEqual(reward.discount, 15.0)
        self.assertEqual(reward.discount_applicability, "specific")
        self._assert_specific_products(reward.discount_product_ids, product)

    def test_write_resyncs_existing_once_per_order_amount_off(self):
        product = self._product("Resync biscuit")
        promo = self.env["avea.promotion"].create(
            {
                "name": "Needs remap",
                "deal_type": "fixed_amount",
                "discount_amount": 60.0,
                "product_scope": "products",
                "product_ids": [Command.set(product.ids)],
                "open_ended": True,
            }
        )
        promo.program_id.rule_ids.write({"reward_point_mode": "order"})
        promo.program_id.reward_ids.write({"discount_mode": "per_order"})
        promo.write({"discount_amount": 55.0})
        self.assertEqual(promo.program_id.rule_ids.reward_point_mode, "unit")
        self.assertEqual(promo.program_id.reward_ids.discount_mode, "per_point")
        self.assertEqual(promo.program_id.reward_ids.discount, 55.0)

    def test_resync_keeps_existing_reward_records(self):
        product = self._product("Historic biscuit")
        promo = self.env["avea.promotion"].create(
            {
                "name": "Keep reward ids",
                "deal_type": "fixed_amount",
                "discount_amount": 60.0,
                "product_scope": "products",
                "product_ids": [Command.set(product.ids)],
                "open_ended": True,
            }
        )
        rule_id = promo.program_id.rule_ids.id
        reward_id = promo.program_id.reward_ids.id
        promo.write({"discount_amount": 45.0})
        self.assertEqual(promo.program_id.rule_ids.id, rule_id)
        self.assertEqual(promo.program_id.reward_ids.id, reward_id)
        self.assertEqual(promo.program_id.reward_ids.discount, 45.0)
        self.assertEqual(promo.program_id.reward_ids.discount_mode, "per_point")

    def test_specific_products_can_apply_once_to_the_ticket(self):
        product = self._product("Ticket biscuit")
        promo = self.env["avea.promotion"].create(
            {
                "name": "Once off the ticket",
                "deal_type": "fixed_amount",
                "discount_amount": 60.0,
                "product_scope": "products",
                "product_ids": [Command.set(product.ids)],
                "apply_on": "ticket",
                "open_ended": True,
            }
        )
        self.assertEqual(promo.apply_on, "ticket")
        self.assertEqual(promo.program_id.rule_ids.reward_point_mode, "order")
        self.assertEqual(promo.program_id.rule_ids.minimum_qty, 1.0)
        self.assertEqual(promo.program_id.reward_ids.discount_mode, "per_order")
        self.assertEqual(promo.program_id.reward_ids.discount_applicability, "order")
        self.assertEqual(promo.deal_summary, f"{promo.currency_id.symbol} 60.00 off the ticket")

    def test_all_products_can_apply_per_item(self):
        promo = self.env["avea.promotion"].create(
            {
                "name": "Every item R5 off",
                "deal_type": "fixed_amount",
                "discount_amount": 5.0,
                "product_scope": "all",
                "apply_on": "product",
                "open_ended": True,
            }
        )
        self.assertEqual(promo.program_id.rule_ids.reward_point_mode, "unit")
        self.assertEqual(promo.program_id.reward_ids.discount_mode, "per_point")
        self.assertEqual(promo.program_id.reward_ids.discount_applicability, "order")
        self.assertEqual(promo.deal_summary, f"{promo.currency_id.symbol} 5.00 off each")

    def test_write_apply_on_switches_mapping(self):
        product = self._product("Switch biscuit")
        promo = self.env["avea.promotion"].create(
            {
                "name": "Switch apply on",
                "deal_type": "fixed_amount",
                "discount_amount": 60.0,
                "product_scope": "products",
                "product_ids": [Command.set(product.ids)],
                "open_ended": True,
            }
        )
        self.assertEqual(promo.apply_on, "product")
        promo.write({"apply_on": "ticket"})
        self.assertEqual(promo.program_id.rule_ids.reward_point_mode, "order")
        self.assertEqual(promo.program_id.reward_ids.discount_mode, "per_order")
        self.assertEqual(promo.program_id.reward_ids.discount_applicability, "order")
