from odoo import api, fields, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    avea_store_credit_payment_total = fields.Monetary(
        string="Store Credit Paid",
        compute="_compute_avea_store_credit_payment_total",
        currency_field="currency_id",
    )

    @api.depends(
        "payment_ids.amount",
        "payment_ids.is_change",
        "payment_ids.payment_method_id.is_avea_store_credit",
    )
    def _compute_avea_store_credit_payment_total(self):
        for order in self:
            payments = order.payment_ids.filtered(
                lambda payment: payment.payment_method_id.is_avea_store_credit
                and not payment.is_change
            )
            order.avea_store_credit_payment_total = sum(
                abs(payment.amount) for payment in payments
            )

    def action_pos_order_paid(self):
        result = super().action_pos_order_paid()
        self._avea_credit_process_store_credit_payments()
        return result

    def _avea_credit_get_original_store_credit_paid(self):
        self.ensure_one()
        refunded_lines = self.lines.filtered("refunded_orderline_id")
        original_orders = refunded_lines.refunded_orderline_id.order_id
        if not original_orders:
            return 0.0
        return sum(original_orders.mapped("avea_store_credit_payment_total"))

    def _avea_credit_process_store_credit_payments(self):
        Ledger = self.env["avea.credit.ledger.entry"]
        for order in self:
            if not order.config_id.avea_credit_enabled:
                continue
            partner = order.partner_id
            if not partner:
                continue
            for payment in order.payment_ids.filtered(
                lambda line: line.payment_method_id.is_avea_store_credit
                and not line.is_change
            ):
                if Ledger.search([("pos_payment_id", "=", payment.id)], limit=1):
                    continue
                amount = abs(payment.amount)
                if order.currency_id.compare_amounts(amount, 0.0) <= 0:
                    continue
                if order.is_refund or order.amount_total < 0:
                    Ledger.create_pos_refund_credit(
                        partner=partner,
                        amount=amount,
                        pos_order=order,
                        pos_payment=payment,
                    )
                else:
                    Ledger.create_pos_redemption(
                        partner=partner,
                        amount=amount,
                        pos_order=order,
                        pos_payment=payment,
                    )
