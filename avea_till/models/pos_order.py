from odoo import models


class PosOrder(models.Model):
    _inherit = "pos.order"

    def action_pos_order_paid(self):
        result = super().action_pos_order_paid()
        self._avea_till_create_cash_movement()
        return result

    def _avea_till_display_reference(self):
        """Business reference shown on till ledger lines (receipt number preferred)."""
        self.ensure_one()
        if self.pos_reference and self.pos_reference != "/":
            return self.pos_reference
        if self.name and self.name != "/":
            return self.name
        return False

    def _avea_till_has_cash_movement(self):
        self.ensure_one()
        Movement = self.env["avea.till.movement"]
        if Movement.search([("pos_order_id", "=", self.id)], limit=1):
            return True
        identifiers = {
            value
            for value in (self.name, self.pos_reference)
            if value and value != "/"
        }
        if not identifiers:
            return False
        identifier_list = list(identifiers)
        return bool(
            Movement.search(
                [
                    ("session_id", "=", self.session_id.id),
                    ("reason", "in", ("Cash Sale", "Cash Refund")),
                    "|",
                    ("name", "in", identifier_list),
                    ("notes", "in", identifier_list),
                ],
                limit=1,
            )
        )

    def _avea_till_create_cash_movement(self):
        Movement = self.env["avea.till.movement"]
        for order in self:
            if order._avea_till_has_cash_movement():
                continue
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
            order.flush_recordset(["name", "pos_reference", "state"])
            display_reference = order._avea_till_display_reference()
            if not display_reference:
                display_reference = order._compute_order_name()
            Movement.create(
                {
                    "name": display_reference,
                    "movement_date": payment_date,
                    "session_id": order.session_id.id,
                    "user_id": order.user_id.id or self.env.user.id,
                    "movement_type": movement_type,
                    "amount": amount,
                    "reason": reason,
                    "notes": order.name if order.name and order.name != "/" else "",
                    "pos_order_id": order.id,
                }
            )
