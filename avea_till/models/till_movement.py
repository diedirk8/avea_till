from odoo import api, fields, models


class AveaTillMovement(models.Model):
    _name = "avea.till.movement"
    _description = "Till Cash Movement"
    _order = "movement_date desc"

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
    )

    currency_id = fields.Many2one(
        "res.currency",
        related="session_id.currency_id",
        store=True,
    )

    reason = fields.Char(
        string="Reason",
    )

    notes = fields.Text(
        string="Notes",
    )
