from datetime import timedelta

from odoo import _, api, fields, models

from .till_movement import (
    CASH_REFUND_REASON,
    CASH_SALE_REASON,
    OPENING_FLOAT_REASON,
    POS_CASH_IN_REASON,
    POS_CASH_OUT_REASON,
)


class AveaTillDashboard(models.TransientModel):
    _name = "avea.till.dashboard"
    _description = "Live Till Dashboard"
    _rec_name = "name"

    name = fields.Char(
        string="Title",
        default=lambda self: _("Till Audit & Reconciliation"),
        required=True,
    )

    session_id = fields.Many2one(
        "pos.session",
        string="POS Session",
        domain="[('state', 'in', ('opened', 'closing_control', 'closed'))]",
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
    )
    session_state = fields.Selection(
        related="session_id.state",
        string="Session Status",
    )
    config_id = fields.Many2one(
        related="session_id.config_id",
        string="Point of Sale",
    )

    pos_expected_cash = fields.Monetary(
        string="POS Expected Cash",
        compute="_compute_till_summary",
        currency_field="currency_id",
        help="Opening float and cash sales recorded by Point of Sale.",
    )
    manual_net = fields.Monetary(
        string="Manual Adjustments",
        compute="_compute_till_summary",
        currency_field="currency_id",
        help="Net effect of recorded Cash In and Cash Out movements.",
    )
    live_balance = fields.Monetary(
        string="Expected Cash in Drawer",
        compute="_compute_till_summary",
        currency_field="currency_id",
        help="Expected physical cash in the till; matches the latest ledger running balance.",
    )

    summary_opening_float = fields.Monetary(
        string="Opening Float",
        compute="_compute_till_summary",
        currency_field="currency_id",
    )
    summary_cash_sales = fields.Monetary(
        string="Cash Sales",
        compute="_compute_till_summary",
        currency_field="currency_id",
    )
    summary_cash_in = fields.Monetary(
        string="Cash In",
        compute="_compute_till_summary",
        currency_field="currency_id",
    )
    summary_cash_out = fields.Monetary(
        string="Cash Out",
        compute="_compute_till_summary",
        currency_field="currency_id",
        help="Manual cash removals from the till (POS Cash Out).",
    )
    summary_cash_refunds = fields.Monetary(
        string="Cash Refunds",
        compute="_compute_till_summary",
        currency_field="currency_id",
    )
    today_movement_count = fields.Integer(
        string="Movements Today",
        compute="_compute_till_summary",
    )

    recent_movement_ids = fields.Many2many(
        "avea.till.movement",
        string="Recent Movements",
        compute="_compute_recent_movements",
    )

    @api.model
    def action_open_dashboard(self, session_id=None):
        """Open a fresh dashboard record (used from the menu)."""
        vals = {}
        if session_id:
            vals["session_id"] = session_id
        dashboard = self.create(vals)
        return {
            "type": "ir.actions.act_window",
            "name": _("Till Audit & Reconciliation"),
            "res_model": "avea.till.dashboard",
            "view_mode": "form",
            "res_id": dashboard.id,
            "target": "current",
        }

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "name" in fields_list and not res.get("name"):
            res["name"] = _("Till Audit & Reconciliation")
        if "session_id" in fields_list and not res.get("session_id"):
            session = self._default_session_id()
            if session:
                res["session_id"] = session.id
        return res

    @api.model
    def _default_session_id(self):
        Session = self.env["pos.session"]
        open_session = Session.search(
            [
                ("state", "in", ("opened", "closing_control")),
                ("user_id", "=", self.env.user.id),
            ],
            order="id desc",
            limit=1,
        )
        if open_session:
            return open_session
        return Session.search(
            [("state", "in", ("opened", "closing_control"))],
            order="id desc",
            limit=1,
        )

    @api.depends("session_id", "session_id.currency_id")
    def _compute_currency_id(self):
        for dashboard in self:
            dashboard.currency_id = (
                dashboard.session_id.currency_id or dashboard.env.company.currency_id
            )

    def _get_session_movement_domain(self):
        self.ensure_one()
        if not self.session_id:
            return [("id", "=", 0)]
        return [("session_id", "=", self.session_id.id)]

    def _get_today_movement_domain(self):
        self.ensure_one()
        domain = self._get_session_movement_domain()
        if not self.session_id:
            return domain
        today = fields.Date.context_today(self)
        start = fields.Datetime.to_datetime(today)
        end = start + timedelta(days=1)
        domain.extend(
            [
                ("movement_date", ">=", fields.Datetime.to_string(start)),
                ("movement_date", "<", fields.Datetime.to_string(end)),
            ]
        )
        return domain

    @api.depends("session_id", "session_id.currency_id")
    def _compute_till_summary(self):
        Movement = self.env["avea.till.movement"]
        for dashboard in self:
            session = dashboard.session_id
            if not session:
                dashboard.pos_expected_cash = 0.0
                dashboard.manual_net = 0.0
                dashboard.live_balance = 0.0
                dashboard.summary_opening_float = 0.0
                dashboard.summary_cash_sales = 0.0
                dashboard.summary_cash_in = 0.0
                dashboard.summary_cash_out = 0.0
                dashboard.summary_cash_refunds = 0.0
                dashboard.today_movement_count = 0
                continue
            Movement.prepare_session_ledger(session)
            session_domain = dashboard._get_session_movement_domain()
            dashboard.summary_opening_float = Movement.sum_amount_for_domain(
                session_domain + [("reason", "=", OPENING_FLOAT_REASON)]
            )
            dashboard.summary_cash_sales = Movement.sum_amount_for_domain(
                session_domain + [("reason", "=", CASH_SALE_REASON)]
            )
            dashboard.summary_cash_in = Movement.sum_amount_for_domain(
                session_domain + [("reason", "=", POS_CASH_IN_REASON)]
            )
            dashboard.summary_cash_out = Movement.sum_amount_for_domain(
                session_domain + [("reason", "=", POS_CASH_OUT_REASON)]
            )
            dashboard.summary_cash_refunds = Movement.sum_amount_for_domain(
                session_domain + [("reason", "=", CASH_REFUND_REASON)]
            )
            ledger_balance = Movement.get_session_ledger_balance(session.id)
            dashboard.pos_expected_cash = ledger_balance
            dashboard.manual_net = 0.0
            dashboard.live_balance = ledger_balance
            dashboard.today_movement_count = Movement.search_count(
                dashboard._get_today_movement_domain()
            )

    @api.depends("session_id")
    def _compute_recent_movements(self):
        Movement = self.env["avea.till.movement"]
        for dashboard in self:
            if dashboard.session_id:
                Movement.prepare_session_ledger(dashboard.session_id)
            domain = []
            if dashboard.session_id:
                domain = [
                    ("session_id", "in", [dashboard.session_id.id, False]),
                ]
            movements = Movement.search(domain, order="movement_date desc, id desc", limit=15)
            dashboard.recent_movement_ids = movements

    def action_refresh(self):
        self.ensure_one()
        session_id = self.session_id.id if self.session_id else None
        return self.env["avea.till.dashboard"].action_open_dashboard(
            session_id=session_id
        )
