from odoo import api, models
from odoo.exceptions import ValidationError
from odoo.tools.translate import _


class PosPayment(models.Model):
    _inherit = "pos.payment"

    @api.constrains("amount", "payment_method_id", "pos_order_id")
    def _check_avea_store_credit_payment(self):
        Ledger = self.env["avea.credit.ledger.entry"]
        for payment in self.filtered(
            lambda line: line.payment_method_id.is_avea_store_credit
            and not line.is_change
        ):
            order = payment.pos_order_id
            if not order or not order.config_id.avea_credit_enabled:
                continue
            partner = order.partner_id
            if not partner:
                raise ValidationError(
                    _("Select a customer before using Store Credit.")
                )
            amount = abs(payment.amount)
            if order.currency_id.compare_amounts(amount, 0.0) <= 0:
                continue
            if order.is_refund or order.amount_total < 0:
                refund_total = abs(order.amount_total)
                other_payments = order.payment_ids.filtered(
                    lambda line: not line.payment_method_id.is_avea_store_credit
                    and not line.is_change
                    and line.id != payment.id
                )
                other_sc_payments = order.payment_ids.filtered(
                    lambda line: line.payment_method_id.is_avea_store_credit
                    and not line.is_change
                    and line.id != payment.id
                )
                max_refund = refund_total - sum(
                    abs(line.amount) for line in other_payments
                )
                requested_total = amount + sum(
                    abs(line.amount) for line in other_sc_payments
                )
                currency = partner.avea_credit_currency_id or order.currency_id
                if currency.compare_amounts(requested_total, max_refund) > 0:
                    raise ValidationError(
                        _(
                            "Only %(amount)s Store Credit can be refunded to this customer for this order.",
                            amount=currency.format(max_refund),
                        )
                    )
                continue
            other_payments = order.payment_ids.filtered(
                lambda line: line.payment_method_id.is_avea_store_credit
                and not line.is_change
                and line.id != payment.id
            )
            requested_total = amount + sum(abs(line.amount) for line in other_payments)
            available = Ledger.get_partner_available_balance(
                partner,
                company=order.company_id,
            )
            currency = partner.avea_credit_currency_id or order.currency_id
            if currency.compare_amounts(requested_total, available) > 0:
                raise ValidationError(
                    _(
                        "Only %(amount)s Store Credit is available for this customer.",
                        amount=currency.format(available),
                    )
                )
