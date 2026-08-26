from odoo import _, api, fields, models


class AveaTillDashboard(models.TransientModel):
    _name = "avea.till.dashboard"
    _description = "Cash Ledger"
    _rec_name = "name"

    name = fields.Char(
        string="Title",
        default=lambda self: _("Cash Ledger"),
        required=True,
    )

    session_id = fields.Many2one(
        "pos.session",
        string="Session",
        domain="[('state', 'in', ('opened', 'closing_control', 'closed'))]",
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
    )
    session_state = fields.Selection(
        related="session_id.state",
        string="Status",
    )
    config_id = fields.Many2one(
        related="session_id.config_id",
        string="Point of Sale",
    )
    cashier_id = fields.Many2one(
        related="session_id.user_id",
        string="Cashier",
    )
    session_opening_time = fields.Datetime(
        related="session_id.start_at",
        string="Opening Time",
    )
    session_duration = fields.Char(
        string="Duration",
        compute="_compute_session_duration",
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
    session_movement_count = fields.Integer(
        string="Movements",
        compute="_compute_till_summary",
    )

    recent_movement_ids = fields.Many2many(
        "avea.till.movement",
        string="Recent Movements",
        compute="_compute_recent_movements",
    )

    @api.model
    def action_open_dashboard(self, session_id=None):
        """Open a fresh cash ledger record (used from the menu)."""
        vals = {}
        if session_id:
            vals["session_id"] = session_id
        dashboard = self.create(vals)
        return {
            "type": "ir.actions.act_window",
            "name": _("Cash Ledger"),
            "res_model": "avea.till.dashboard",
            "view_mode": "form",
            "res_id": dashboard.id,
            "target": "current",
            "context": {"clear_breadcrumbs": True},
        }

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "name" in fields_list and not res.get("name"):
            res["name"] = _("Cash Ledger")
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

    @api.depends("session_id", "session_id.start_at", "session_id.stop_at", "session_id.state")
    def _compute_session_duration(self):
        for dashboard in self:
            session = dashboard.session_id
            dashboard.session_duration = (
                session.get_avea_session_duration_display() if session else ""
            )

    def _get_session_movement_domain(self):
        self.ensure_one()
        if not self.session_id:
            return [("id", "=", 0)]
        return [("session_id", "=", self.session_id.id)]

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
                dashboard.session_movement_count = 0
                continue

            cash = session.get_avea_cash_summary()
            dashboard.summary_opening_float = cash["opening_float"]
            dashboard.summary_cash_sales = cash["cash_sales"]
            dashboard.summary_cash_in = cash["cash_in"]
            dashboard.summary_cash_out = cash["cash_out"]
            dashboard.summary_cash_refunds = cash["cash_refunds"]
            dashboard.live_balance = cash["expected_cash"]
            dashboard.pos_expected_cash = cash["expected_cash"]
            dashboard.manual_net = 0.0
            dashboard.session_movement_count = cash["movement_count"]

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

    def action_open_session_dashboard(self):
        self.ensure_one()
        session_id = self.session_id.id if self.session_id else None
        return self.env["avea.till.session.dashboard"].action_open_session_dashboard(
            session_id=session_id
        )

    def action_open_cash_ledger(self):
        self.ensure_one()
        session_id = self.session_id.id if self.session_id else None
        return self.env["avea.till.dashboard"].action_open_dashboard(
            session_id=session_id
        )

    def action_refresh(self):
        self.ensure_one()
        session_id = self.session_id.id if self.session_id else None
        return self.env["avea.till.dashboard"].action_open_dashboard(
            session_id=session_id
        )
