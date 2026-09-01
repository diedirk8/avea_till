from markupsafe import Markup

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import formatLang

from .till_movement import CASH_REFUND_REASON, CASH_SALE_REASON


class PosOrder(models.Model):
    _inherit = "pos.order"

    avea_can_correct_payment = fields.Boolean(
        compute="_compute_avea_can_correct_payment",
    )

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

    def _avea_till_find_cash_movements(self):
        self.ensure_one()
        Movement = self.env["avea.till.movement"]
        linked = Movement.search(
            [
                ("pos_order_id", "=", self.id),
                ("reason", "in", (CASH_SALE_REASON, CASH_REFUND_REASON)),
            ]
        )
        if linked:
            return linked
        identifiers = {
            value
            for value in (self.name, self.pos_reference)
            if value and value != "/"
        }
        if not identifiers or not self.session_id:
            return Movement.browse()
        return Movement.search(
            [
                ("session_id", "=", self.session_id.id),
                ("pos_order_id", "=", False),
                ("reason", "in", (CASH_SALE_REASON, CASH_REFUND_REASON)),
                "|",
                ("name", "in", list(identifiers)),
                ("notes", "in", list(identifiers)),
            ]
        )

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
                    ("reason", "in", (CASH_SALE_REASON, CASH_REFUND_REASON)),
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
                reason = CASH_REFUND_REASON
            else:
                movement_type = "in"
                reason = CASH_SALE_REASON
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

    def _avea_till_sync_cash_movement_after_payment_correction(self):
        """Create or remove Cash Sale/Refund so Cash Up matches the new tender."""
        for order in self:
            cash_payments = order.payment_ids.filtered(
                lambda payment: payment.payment_method_id.type == "cash"
            )
            movements = order._avea_till_find_cash_movements()
            if cash_payments:
                if not movements:
                    order._avea_till_create_cash_movement()
                continue
            if movements:
                movements.unlink()

    @api.depends(
        "state",
        "account_move",
        "session_id.state",
        "payment_ids.payment_method_id",
        "payment_ids.amount",
        "payment_ids.is_change",
    )
    def _compute_avea_can_correct_payment(self):
        for order in self:
            order.avea_can_correct_payment = not bool(
                order._avea_payment_correction_block_reason()
            )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        if fields_list and "avea_can_correct_payment" not in fields_list:
            fields_list = list(fields_list) + ["avea_can_correct_payment"]
        return fields_list

    @api.model
    def _load_pos_data_read(self, records, config):
        data = super()._load_pos_data_read(records, config)
        orders = {order.id: order for order in records}
        for row in data:
            order = orders.get(row.get("id"))
            if order is not None:
                row["avea_can_correct_payment"] = bool(order.avea_can_correct_payment)
        return data

    @api.model
    def _avea_user_can_correct_payment(self):
        return self.env.user.has_group("avea_till.group_avea_correct_payment")

    def _avea_non_change_payments(self):
        self.ensure_one()
        currency = self.currency_id
        return self.payment_ids.filtered(
            lambda payment: not payment.is_change
            and currency.compare_amounts(abs(payment.amount), 0.0) > 0
        )

    def _avea_change_payments(self):
        self.ensure_one()
        currency = self.currency_id
        return self.payment_ids.filtered(
            lambda payment: payment.is_change
            and currency.compare_amounts(abs(payment.amount), 0.0) > 0
        )

    def _avea_payment_correction_block_reason(self):
        """Return a cashier-facing block message, or False if correction is allowed."""
        self.ensure_one()
        session = self.session_id
        if not session or session.state != "opened":
            return _(
                "Payment method can only be corrected while this till session is still open."
            )
        if self.account_move or self.state == "invoiced":
            return _("Invoiced orders cannot be corrected this way.")
        if self.state not in ("paid", "done"):
            return _("This order is not completed.")
        tenders = self._avea_non_change_payments()
        if len(tenders) != 1:
            return _(
                "This order used more than one payment method. Split payments cannot be corrected here."
            )
        if self._avea_change_payments():
            return _(
                "This order includes change. Payment method can only be corrected on exact payments."
            )
        method = tenders.payment_method_id
        if method.is_avea_store_credit or method._avea_tender_kind() == "store_credit":
            return _("Store Credit payments cannot be corrected this way.")
        if not method._avea_is_open_session_correctable_tender():
            return _(
                "Only Cash, Card and EFT payments can be corrected while the session is open."
            )
        return False

    def _avea_correctable_tender(self):
        self.ensure_one()
        return self._avea_non_change_payments()[:1]

    def _avea_open_session_correction_methods(self):
        self.ensure_one()
        return self.session_id.config_id.payment_method_ids.filtered(
            lambda method: method._avea_is_open_session_correctable_tender()
        )

    def _avea_assert_can_correct_payment(self):
        self.ensure_one()
        if not self._avea_user_can_correct_payment():
            raise AccessError(
                _("You do not have permission to correct a payment method.")
            )
        block = self._avea_payment_correction_block_reason()
        if block:
            raise UserError(block)

    def action_avea_correct_payment_method(self):
        self.ensure_one()
        self._avea_assert_can_correct_payment()
        return {
            "type": "ir.actions.act_window",
            "name": _("Correct Payment Method"),
            "res_model": "avea.payment.correction.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_order_id": self.id},
        }

    def avea_get_payment_correction_options(self):
        """POS payload: current tender and allowed Cash/Card/EFT replacements."""
        self.ensure_one()
        if not self._avea_user_can_correct_payment():
            raise AccessError(
                _("You do not have permission to correct a payment method.")
            )
        block = self._avea_payment_correction_block_reason()
        tender = self._avea_correctable_tender()
        current_method = tender.payment_method_id if tender else self.env["pos.payment.method"]
        methods = []
        if not block and current_method:
            methods = [
                {
                    "id": method.id,
                    "name": method.name,
                    "kind": method._avea_tender_kind(),
                }
                for method in self._avea_open_session_correction_methods()
                if method != current_method
            ]
        return {
            "blocked": bool(block),
            "block_reason": block or "",
            "order_id": self.id,
            "order_name": self.pos_reference or self.name,
            "amount": tender.amount if tender else 0.0,
            "amount_display": formatLang(
                self.env,
                abs(tender.amount) if tender else 0.0,
                currency_obj=self.currency_id,
            ),
            "current_method_id": current_method.id or False,
            "current_method_name": current_method.name or "",
            "current_method_kind": current_method._avea_tender_kind()
            if current_method
            else "",
            "methods": methods,
        }

    def avea_correct_payment_method(self, payment_method_id, reason):
        """Change only the tender on an open-session order and sync the till ledger."""
        self.ensure_one()
        self._avea_assert_can_correct_payment()
        reason_text = (reason or "").strip()
        if not reason_text:
            raise UserError(_("Enter a reason for the correction."))
        tender = self._avea_correctable_tender()
        new_method = self.env["pos.payment.method"].browse(payment_method_id).exists()
        if not new_method:
            raise UserError(_("Select a payment method."))
        if new_method not in self._avea_open_session_correction_methods():
            raise UserError(
                _("Only Cash, Card and EFT payments can be corrected while the session is open.")
            )
        if new_method == tender.payment_method_id:
            raise UserError(_("Select a different payment method."))

        original_method = tender.payment_method_id
        original_name = original_method.name
        amount = tender.amount
        self.write(
            {
                "payment_ids": [
                    Command.update(
                        tender.id,
                        {
                            "payment_method_id": new_method.id,
                            "name": new_method.name,
                        },
                    )
                ]
            }
        )
        self.invalidate_recordset(["payment_ids"])
        self._avea_till_sync_cash_movement_after_payment_correction()
        self.session_id.invalidate_recordset(
            ["cash_register_balance_end", "cash_register_difference"]
        )
        self.message_post(
            body=Markup("<p>%s</p><p>%s</p>")
            % (
                _(
                    "Corrected payment method from %(original)s to %(corrected)s (%(amount)s).",
                    original=original_name,
                    corrected=new_method.name,
                    amount=formatLang(self.env, amount, currency_obj=self.currency_id),
                ),
                _("Reason: %s", reason_text),
            )
        )
        expected_cash = self.session_id.cash_register_balance_end or 0.0
        return {
            "successful": True,
            "payment_id": tender.id,
            "payment_method_id": new_method.id,
            "payment_method_name": new_method.name,
            "expected_cash": expected_cash,
        }
