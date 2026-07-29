from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AveaTillMovement(models.Model):
    _name = "avea.till.movement"
    _description = "Till Cash Movement"
    _order = "movement_date desc, id desc"

    name = fields.Char(
        string="Reference",
        required=True,
    )

    movement_date = fields.Datetime(
        string="Date",
        default=fields.Datetime.now,
        required=True,
    )

    session_id = fields.Many2one(
        "pos.session",
        string="POS Session",
    )

    user_id = fields.Many2one(
        "res.users",
        string="User",
        default=lambda self: self.env.user,
        required=True,
    )

    movement_type = fields.Selection(
        [
            ("in", "Cash In"),
            ("out", "Cash Out"),
        ],
        string="Movement",
        required=True,
    )

    amount = fields.Monetary(
        string="Amount",
        required=True,
        currency_field="currency_id",
    )
    running_balance = fields.Monetary(
        string="Running Balance",
        currency_field="currency_id",
        readonly=True,
        copy=False,
    )

    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
        store=True,
        readonly=False,
    )

    reason = fields.Char(
        string="Reason",
    )

    notes = fields.Text(
        string="Notes",
    )

    ledger_reference = fields.Char(
        string="Reference",
        compute="_compute_ledger_reference",
        store=True,
        readonly=True,
    )

    @api.depends("name", "notes", "reason", "session_id")
    def _compute_ledger_reference(self):
        Order = self.env["pos.order"]
        for movement in self:
            reference = movement.name
            if reference and reference != "/":
                movement.ledger_reference = reference
                continue
            reference = (
                movement.notes if movement.notes and movement.notes != "/" else False
            )
            if movement.reason in ("Cash Sale", "Cash Refund") and movement.session_id:
                domain = [("session_id", "=", movement.session_id.id)]
                order = Order.browse()
                if reference:
                    order = Order.search(
                        domain
                        + [
                            "|",
                            ("name", "=", reference),
                            ("pos_reference", "=", reference),
                        ],
                        limit=1,
                        order="id desc",
                    )
                movement.ledger_reference = (
                    (order.pos_reference or order.name)
                    if order
                    else (reference or "")
                )
            else:
                movement.ledger_reference = reference or ""

    @api.depends("session_id", "session_id.currency_id")
    def _compute_currency_id(self):
        for movement in self:
            movement.currency_id = (
                movement.session_id.currency_id or movement.env.company.currency_id
            )

    @api.constrains("amount")
    def _check_amount_positive(self):
        for movement in self:
            if movement.currency_id.compare_amounts(movement.amount, 0.0) <= 0:
                raise ValidationError("Movement amount must be greater than zero.")

    def _signed_amount(self):
        self.ensure_one()
        if self.movement_type == "out":
            return -self.amount
        return self.amount

    @api.model
    def get_session_manual_net(self, session_id):
        return self.get_sessions_manual_net([session_id]).get(session_id, 0.0)

    @api.model
    def get_sessions_manual_net(self, session_ids):
        if not session_ids:
            return {}
        groups = self._read_group(
            [("session_id", "in", session_ids)],
            ["session_id", "movement_type"],
            ["amount:sum"],
        )
        nets = {session_id: 0.0 for session_id in session_ids}
        for session, movement_type, amount_sum in groups:
            if not session:
                continue
            signed = amount_sum or 0.0
            if movement_type == "out":
                signed = -signed
            nets[session.id] = nets.get(session.id, 0.0) + signed
        return nets

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._assign_running_balances()
        return records

    def _assign_running_balances(self):
        for movement in self:
            prior = self.search(
                [
                    ("session_id", "=", movement.session_id.id),
                    ("id", "!=", movement.id),
                    "|",
                    ("movement_date", "<", movement.movement_date),
                    "&",
                    ("movement_date", "=", movement.movement_date),
                    ("id", "<", movement.id),
                ],
                order="movement_date desc, id desc",
                limit=1,
            )
            prior_balance = prior.running_balance if prior else 0.0
            movement.running_balance = prior_balance + movement._signed_amount()
