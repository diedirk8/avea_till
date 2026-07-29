from odoo import api, fields, models


class PosSession(models.Model):
    _inherit = "pos.session"

    avea_manual_net = fields.Monetary(
        string="Manual Cash Adjustments",
        compute="_compute_avea_till_metrics",
        currency_field="currency_id",
        help="Net Cash In and Cash Out recorded in Avea Till for this session.",
    )
    avea_live_balance = fields.Monetary(
        string="Expected Drawer Cash",
        compute="_compute_avea_till_metrics",
        currency_field="currency_id",
        help="Expected cash in the till from the Avea ledger running balance.",
    )

    @api.depends("state")
    def _compute_avea_till_metrics(self):
        Movement = self.env["avea.till.movement"]
        for session in self:
            Movement.prepare_session_ledger(session)
        balance_by_session = Movement.get_sessions_ledger_balance(self.ids)
        for session in self:
            ledger_balance = balance_by_session.get(session.id, 0.0)
            session.avea_manual_net = 0.0
            session.avea_live_balance = ledger_balance

    def set_opening_control(self, cashbox_value, notes):
        super().set_opening_control(cashbox_value, notes)
        self.env["avea.till.movement"]._ensure_opening_float(self)

    def try_cash_in_out(self, _type, amount, reason, partner_id, extras):
        sign = 1 if _type == "in" else -1
        result = super().try_cash_in_out(_type, amount, reason, partner_id, extras)
        Movement = self.env["avea.till.movement"]
        label = "POS Cash In" if _type == "in" else "POS Cash Out"
        movement_type = "in" if _type == "in" else "out"
        for session in self.filtered("cash_journal_id"):
            statement_line = session.statement_line_ids.filtered(
                lambda line: line.currency_id.compare_amounts(line.amount, sign * amount) == 0
            ).sorted("create_date desc")[:1]
            if not statement_line:
                statement_line = session.statement_line_ids.sorted("create_date desc")[:1]
            reference = statement_line.payment_ref if statement_line else label
            Movement.create(
                {
                    "name": reference,
                    "movement_date": fields.Datetime.now(),
                    "session_id": session.id,
                    "user_id": self.env.user.id,
                    "movement_type": movement_type,
                    "amount": amount,
                    "reason": label,
                    "notes": reason or "",
                }
            )
        return result
