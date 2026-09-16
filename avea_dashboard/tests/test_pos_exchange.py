# -*- coding: utf-8 -*-
from odoo import Command, fields
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaPosExchange(TestPoSCommon):
    """POS exchange: net payment, store credit, loyalty and accounting correctness."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.config.write({"avea_credit_enabled": True})
        cls.company = cls.env.company
        company = cls.company.sudo()
        company._avea_credit_setup_all_companies()
        cls.store_credit_pm = company._avea_credit_ensure_store_credit_payment_method(
            company._avea_credit_ensure_store_credit_journal(),
            company._avea_credit_ref("liability_account"),
        )
        cls.config.write(
            {
                "payment_method_ids": [
                    Command.link(cls.cash_pm1.id),
                    Command.link(cls.store_credit_pm.id),
                ]
            }
        )
        cls.product_return = cls.create_product(
            "Exchange Return", cls.categ_basic, 300.0, 150.0
        )
        cls.product_replace_a = cls.create_product(
            "Exchange Replace A", cls.categ_basic, 350.0, 175.0
        )
        cls.product_replace_b = cls.create_product(
            "Exchange Replace B", cls.categ_basic, 250.0, 125.0
        )
        cls.product_replace_even = cls.create_product(
            "Exchange Replace Even", cls.categ_basic, 300.0, 150.0
        )
        cls.Ledger = cls.env["avea.credit.ledger.entry"]

    def _open_session(self):
        return self.open_new_session(0)

    def _create_paid_sale(self, *, product, qty=1, customer=None, payments=None, uuid="exchange-sale"):
        session = self._open_session()
        total = product.lst_price * qty
        if payments is None:
            payments = [(self.cash_pm1, total)]
        order_data = self.create_ui_order_data(
            pos_order_lines_ui_args=[(product, qty)],
            customer=customer or self.customer,
            payments=payments,
            uuid=uuid,
        )
        sync = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(sync["pos.order"][0]["id"])
        self.assertEqual(order.state, "paid")
        return order, session

    def _exchange_order_data(
        self,
        *,
        original_line,
        return_qty,
        replacement_lines,
        payments,
        uuid="exchange-order",
        session=None,
    ):
        return_lines = [
            (
                0,
                0,
                {
                    "product_id": original_line.product_id.id,
                    "qty": -return_qty,
                    "price_unit": original_line.price_unit,
                    "price_subtotal": -original_line.price_unit * return_qty,
                    "price_subtotal_incl": -original_line.price_unit * return_qty,
                    "tax_ids": [(6, 0, original_line.tax_ids.ids)],
                    "refunded_orderline_id": original_line.id,
                    "price_type": "automatic",
                },
            )
        ]
        for product, qty in replacement_lines:
            price = product.lst_price
            return_lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "qty": qty,
                        "price_unit": price,
                        "price_subtotal": price * qty,
                        "price_subtotal_incl": price * qty,
                        "tax_ids": [(6, 0, [])],
                        "price_type": "automatic",
                    },
                )
            )
        amount_total = sum(line[2]["price_subtotal_incl"] for line in return_lines)
        payment_vals = [
            (
                0,
                0,
                {
                    "amount": amount,
                    "name": fields.Datetime.now(),
                    "payment_method_id": pm.id,
                },
            )
            for pm, amount in payments
        ]
        return {
            "name": uuid,
            "uuid": uuid,
            "session_id": session.id,
            "partner_id": original_line.order_id.partner_id.id,
            "pricelist_id": self.config.pricelist_id.id,
            "fiscal_position_id": False,
            "amount_paid": sum(amount for _pm, amount in payments),
            "amount_tax": 0.0,
            "amount_return": 0.0,
            "amount_total": amount_total,
            "lines": return_lines,
            "payment_ids": payment_vals,
            "avea_is_exchange": True,
            "last_order_preparation_change": "{}",
            "date_order": fields.Datetime.to_string(fields.Datetime.now()),
        }

    def _order_from_sync(self, sync_result, uuid):
        """Return the synced order matching uuid (not the refunded source order)."""
        order = self.env["pos.order"].search([("uuid", "=", uuid)], limit=1)
        if not order:
            order = self.env["pos.order"].browse(sync_result["pos.order"][-1]["id"])
        return order

    def _create_paid_exchange(self, **kwargs):
        uuid = kwargs.get("uuid", "exchange-order")
        sync = self.env["pos.order"].sync_from_ui([self._exchange_order_data(**kwargs)])
        order = self._order_from_sync(sync, uuid)
        self.assertEqual(order.state, "paid")
        return order

    def test_exchange_customer_pays_net_50(self):
        original, session = self._create_paid_sale(
            product=self.product_return, uuid="exchange-pay-50-original"
        )
        exchange = self._create_paid_exchange(
            original_line=original.lines[0],
            return_qty=1,
            replacement_lines=[(self.product_replace_a, 1)],
            payments=[(self.cash_pm1, 50.0)],
            uuid="exchange-pay-50",
            session=session,
        )
        self.assertTrue(exchange.avea_is_exchange)
        self.assertFalse(exchange.is_refund)
        self.assertEqual(exchange.amount_total, 50.0)
        self.assertEqual(exchange.lines.filtered("refunded_orderline_id").qty, -1.0)

    def test_exchange_customer_receives_net_50(self):
        original, session = self._create_paid_sale(
            product=self.product_return, uuid="exchange-receive-50-original"
        )
        exchange = self._create_paid_exchange(
            original_line=original.lines[0],
            return_qty=1,
            replacement_lines=[(self.product_replace_b, 1)],
            payments=[(self.cash_pm1, -50.0)],
            uuid="exchange-receive-50",
            session=session,
        )
        self.assertEqual(exchange.amount_total, -50.0)
        self.assertFalse(exchange.is_refund)

    def test_exchange_zero_net_payment(self):
        original, session = self._create_paid_sale(
            product=self.product_return, uuid="exchange-zero-original"
        )
        exchange = self._create_paid_exchange(
            original_line=original.lines[0],
            return_qty=1,
            replacement_lines=[(self.product_replace_even, 1)],
            payments=[(self.cash_pm1, 0.0)],
            uuid="exchange-zero",
            session=session,
        )
        self.assertEqual(exchange.amount_total, 0.0)

    def test_pure_refund_remains_separate_from_exchange(self):
        original, session = self._create_paid_sale(
            product=self.product_return, uuid="pure-refund-original"
        )
        refund_data = self._exchange_order_data(
            original_line=original.lines[0],
            return_qty=1,
            replacement_lines=[],
            payments=[(self.cash_pm1, -300.0)],
            uuid="pure-refund-order",
            session=session,
        )
        refund_data["is_refund"] = True
        refund_data.pop("avea_is_exchange")
        refund_data["amount_total"] = -300.0
        refund_data["amount_paid"] = -300.0
        sync = self.env["pos.order"].sync_from_ui([refund_data])
        refund = self._order_from_sync(sync, "pure-refund-order")
        self.assertTrue(refund.is_refund)
        self.assertFalse(refund.avea_is_exchange)
        self.assertEqual(refund.amount_total, -300.0)

    def test_exchange_store_credit_net_balance(self):
        partner = self.customer
        self.Ledger.create_issued_credit(
            partner,
            300.0,
            self.Ledger._get_pos_refund_reason(),
        )
        partner.invalidate_recordset(["avea_credit_balance"])
        self.assertEqual(partner.avea_credit_balance, 300.0)

        original, session = self._create_paid_sale(
            product=self.product_return,
            customer=partner,
            payments=[(self.store_credit_pm, 300.0)],
            uuid="exchange-sc-original",
        )
        partner.invalidate_recordset(["avea_credit_balance"])
        self.assertEqual(partner.avea_credit_balance, 0.0)

        exchange = self._create_paid_exchange(
            original_line=original.lines[0],
            return_qty=1,
            replacement_lines=[(self.product_replace_b, 1)],
            payments=[
                (self.store_credit_pm, -300.0),
                (self.store_credit_pm, 250.0),
            ],
            uuid="exchange-sc-net",
            session=session,
        )
        self.assertTrue(exchange.avea_is_exchange)
        partner.invalidate_recordset(["avea_credit_balance"])
        self.assertEqual(partner.avea_credit_balance, 50.0)

    def test_exchange_customer_account_balance_unchanged(self):
        partner = self.customer
        before = partner.avea_customer_account_balance
        original, session = self._create_paid_sale(
            product=self.product_return, customer=partner, uuid="exchange-ca-original"
        )
        self._create_paid_exchange(
            original_line=original.lines[0],
            return_qty=1,
            replacement_lines=[(self.product_replace_a, 1)],
            payments=[(self.cash_pm1, 50.0)],
            uuid="exchange-ca",
            session=session,
        )
        partner.invalidate_recordset(["avea_customer_account_balance"])
        self.assertEqual(partner.avea_customer_account_balance, before)

    def test_exchange_loyalty_net_point_adjustment(self):
        self.env["loyalty.program"].search([]).write({"active": False})
        program = self.env["loyalty.program"].create(
            {
                "name": "Exchange Loyalty",
                "program_type": "loyalty",
                "trigger": "auto",
                "applies_on": "both",
                "pos_ok": True,
                "pos_config_ids": [Command.link(self.config.id)],
                "rule_ids": [
                    Command.create(
                        {
                            "reward_point_mode": "money",
                            "reward_point_amount": 0.1,
                            "minimum_amount": 1,
                        }
                    )
                ],
                "reward_ids": [
                    Command.create(
                        {
                            "reward_type": "discount",
                            "required_points": 100,
                            "discount": 1,
                            "discount_mode": "per_point",
                        }
                    )
                ],
            }
        )
        card = self.env["loyalty.card"].create(
            {
                "partner_id": self.customer.id,
                "program_id": program.id,
                "points": 0,
            }
        )
        original, session = self._create_paid_sale(
            product=self.product_return,
            customer=self.customer,
            uuid="exchange-loyalty-original",
        )
        original.confirm_coupon_programs(
            {
                card.id: {
                    "points": 30,
                    "program_id": program.id,
                    "coupon_id": card.id,
                }
            }
        )
        self.assertEqual(card.points, 30)

        exchange = self._create_paid_exchange(
            original_line=original.lines[0],
            return_qty=1,
            replacement_lines=[(self.product_replace_a, 1)],
            payments=[(self.cash_pm1, 50.0)],
            uuid="exchange-loyalty",
            session=session,
        )
        exchange.confirm_coupon_programs(
            {
                card.id: {
                    "points": 5,
                    "program_id": program.id,
                    "coupon_id": card.id,
                }
            }
        )
        self.assertEqual(card.points, 35)

    def test_exchange_cash_movement_uses_net_direction(self):
        original, session = self._create_paid_sale(
            product=self.product_return, uuid="exchange-cash-in-original"
        )
        exchange = self._create_paid_exchange(
            original_line=original.lines[0],
            return_qty=1,
            replacement_lines=[(self.product_replace_a, 1)],
            payments=[(self.cash_pm1, 50.0)],
            uuid="exchange-cash-in",
            session=session,
        )
        movement = self.env["avea.till.movement"].search(
            [("pos_order_id", "=", exchange.id)], limit=1
        )
        self.assertTrue(movement)
        self.assertEqual(movement.movement_type, "in")
        self.assertEqual(movement.amount, 50.0)

    def test_partial_exchange_preserves_remaining_returnable_qty(self):
        original, session = self._create_paid_sale(
            product=self.product_return,
            qty=2,
            uuid="partial-exchange-original",
        )
        line = original.lines[0]
        exchange = self._create_paid_exchange(
            original_line=line,
            return_qty=1,
            replacement_lines=[(self.product_replace_b, 1)],
            payments=[(self.cash_pm1, -50.0)],
            uuid="partial-exchange",
            session=session,
        )
        self.assertTrue(exchange.avea_is_exchange)
        self.assertEqual(exchange.amount_total, -50.0)
        refunded = exchange.lines.filtered("refunded_orderline_id")
        self.assertEqual(len(refunded), 1)
        self.assertEqual(refunded.qty, -1.0)
        already_refunded = abs(sum(line.refund_orderline_ids.mapped("qty")))
        self.assertEqual(already_refunded, 1.0)
        self.assertEqual(line.qty - already_refunded, 1.0)

    def test_pure_cash_refund_unaffected_by_exchange_flag(self):
        original, session = self._create_paid_sale(
            product=self.product_return, uuid="unaffected-refund-original"
        )
        refund_data = self._exchange_order_data(
            original_line=original.lines[0],
            return_qty=1,
            replacement_lines=[],
            payments=[(self.cash_pm1, -300.0)],
            uuid="unaffected-refund",
            session=session,
        )
        refund_data["is_refund"] = True
        refund_data.pop("avea_is_exchange", None)
        refund_data["amount_total"] = -300.0
        refund_data["amount_paid"] = -300.0
        refund = self._order_from_sync(
            self.env["pos.order"].sync_from_ui([refund_data]),
            "unaffected-refund",
        )
        self.assertTrue(refund.is_refund)
        self.assertFalse(refund.avea_is_exchange)
        self.assertEqual(refund.amount_total, -300.0)
        movement = self.env["avea.till.movement"].search(
            [("pos_order_id", "=", refund.id)], limit=1
        )
        self.assertEqual(movement.movement_type, "out")
        self.assertEqual(movement.amount, 300.0)

    def test_exchange_mixed_line_amounts_for_tax(self):
        original, session = self._create_paid_sale(
            product=self.product_return, uuid="exchange-tax-original"
        )
        exchange = self._create_paid_exchange(
            original_line=original.lines[0],
            return_qty=1,
            replacement_lines=[(self.product_replace_a, 1)],
            payments=[(self.cash_pm1, 50.0)],
            uuid="exchange-tax",
            session=session,
        )
        return_line = exchange.lines.filtered("refunded_orderline_id")
        sale_line = exchange.lines.filtered(lambda line: not line.refunded_orderline_id)
        self.assertEqual(return_line.qty, -1.0)
        self.assertEqual(sale_line.qty, 1.0)
        self.assertLess(return_line.price_subtotal_incl, 0)
        self.assertGreater(sale_line.price_subtotal_incl, 0)
        self.assertEqual(
            return_line.price_subtotal_incl + sale_line.price_subtotal_incl,
            exchange.amount_total,
        )
