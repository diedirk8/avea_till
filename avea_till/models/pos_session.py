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
        help="POS expected cash plus manual till movements.",
    )

    @api.depends("cash_register_balance_end")
    def _compute_avea_till_metrics(self):
        Movement = self.env["avea.till.movement"]
        manual_by_session = Movement.get_sessions_manual_net(self.ids)
        for session in self:
            manual_net = manual_by_session.get(session.id, 0.0)
            pos_expected = session.cash_register_balance_end or 0.0
            session.avea_manual_net = manual_net
            session.avea_live_balance = pos_expected + manual_net

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
