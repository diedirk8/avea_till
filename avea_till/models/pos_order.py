from odoo import models


class PosOrder(models.Model):
    _inherit = "pos.order"

    def action_pos_order_paid(self):
        orders_to_record = self.filtered(
            lambda order: order.state not in ("paid", "done", "invoiced")
        )
        result = super().action_pos_order_paid()
        orders_to_record._avea_till_create_cash_movement()
        return result

    def _avea_till_create_cash_movement(self):
        Movement = self.env["avea.till.movement"]
        for order in self:
            cash_payments = order.payment_ids.filtered(
                lambda payment: payment.payment_method_id.type == "cash"
            )
            if not cash_payments:
                continue
            net_cash = 0.0
            for payment in cash_payments:
                if payment.is_change:
                    net_cash -= abs(payment.amount)
                else:
                    net_cash += payment.amount
            amount = abs(net_cash)
            if order.currency_id.compare_amounts(amount, 0.0) <= 0:
                continue
            if order.is_refund or net_cash < 0:
                movement_type = "out"
                reason = "Cash Refund"
            else:
                movement_type = "in"
                reason = "Cash Sale"
            payment_date = max(cash_payments.mapped("payment_date"))
            reference = order.name
            if not reference or reference == "/":
                reference = order.pos_reference
            Movement.create(
                {
                    "name": reference,
                    "movement_date": payment_date,
                    "session_id": order.session_id.id,
                    "user_id": order.user_id.id or self.env.user.id,
                    "movement_type": movement_type,
                    "amount": amount,
                    "reason": reason,
                    "notes": order.name,
                }
            )
