from odoo import Command, _, api, fields, models


class AveaTillSessionDashboardProductLine(models.TransientModel):
    _name = "avea.till.session.dashboard.product.line"
    _description = "Session Dashboard Product Sold Line"
    _order = "rank, id"

    dashboard_id = fields.Many2one(
        "avea.till.session.dashboard",
        string="Dashboard",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(
        related="dashboard_id.currency_id",
    )
    rank = fields.Integer(
        string="Rank",
        readonly=True,
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product Record",
        readonly=True,
    )
    product_name = fields.Char(
        string="Product",
        readonly=True,
    )
    quantity_sold = fields.Float(
        string="Quantity Sold",
        digits="Product Unit",
        readonly=True,
    )
    sales_value = fields.Monetary(
        string="Sales Value",
        currency_field="currency_id",
        readonly=True,
    )


class AveaTillSessionDashboard(models.TransientModel):
    _name = "avea.till.session.dashboard"
    _description = "Session Dashboard"
    _rec_name = "session_id"

    session_id = fields.Many2one(
        "pos.session",
        string="Session",
        domain="[('state', 'in', ('opened', 'closing_control', 'closed'))]",
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
    )
    config_id = fields.Many2one(
        related="session_id.config_id",
        string="Till",
    )
    cashier_id = fields.Many2one(
        related="session_id.user_id",
        string="Cashier",
    )
    session_state = fields.Selection(
        related="session_id.state",
        string="Status",
    )
    session_opening_time = fields.Datetime(
        related="session_id.start_at",
        string="Opening Time",
    )
    session_duration = fields.Char(
        string="Duration",
        compute="_compute_session_info",
    )

    total_sales = fields.Monetary(
        string="Total Sales",
        compute="_compute_session_metrics",
        currency_field="currency_id",
    )
    cash_sales = fields.Monetary(
        string="Cash Sales",
        compute="_compute_session_metrics",
        currency_field="currency_id",
    )
    card_sales = fields.Monetary(
        string="Card Sales",
        compute="_compute_session_metrics",
        currency_field="currency_id",
    )
    other_payments = fields.Monetary(
        string="Other Payments",
        compute="_compute_session_metrics",
        currency_field="currency_id",
    )
    order_count = fields.Integer(
        string="Transactions",
        compute="_compute_session_metrics",
    )
    average_order_value = fields.Monetary(
        string="Average Sale",
        compute="_compute_session_metrics",
        currency_field="currency_id",
    )
    expected_cash = fields.Monetary(
        string="Cash in Drawer",
        compute="_compute_session_metrics",
        currency_field="currency_id",
    )

    activity_items_sold = fields.Float(
        string="Items Sold",
        compute="_compute_session_metrics",
    )
    activity_discount_total = fields.Monetary(
        string="Discounts",
        compute="_compute_session_metrics",
        currency_field="currency_id",
    )
    activity_refund_count = fields.Integer(
        string="Refunds",
        compute="_compute_session_metrics",
    )
    activity_cash_movement_count = fields.Integer(
        string="Cash Movements",
        compute="_compute_session_metrics",
    )
    activity_cash_in_count = fields.Integer(
        string="Cash In",
        compute="_compute_session_metrics",
    )
    activity_cash_out_count = fields.Integer(
        string="Cash Out",
        compute="_compute_session_metrics",
    )
    activity_cash_in_total = fields.Monetary(
        string="Cash In Total",
        compute="_compute_session_metrics",
        currency_field="currency_id",
    )
    activity_cash_out_total = fields.Monetary(
        string="Cash Out Total",
        compute="_compute_session_metrics",
        currency_field="currency_id",
    )
    product_line_ids = fields.One2many(
        "avea.till.session.dashboard.product.line",
        "dashboard_id",
        string="Products Sold",
        readonly=True,
    )
    show_products_sold = fields.Boolean(
        compute="_compute_show_products_sold",
    )
    show_refund_attention = fields.Boolean(
        compute="_compute_session_metrics",
    )

    @api.model_create_multi
    def create(self, vals_list):
        dashboards = super().create(vals_list)
        dashboards._populate_product_lines()
        return dashboards

    def write(self, vals):
        res = super().write(vals)
        if "session_id" in vals:
            self._populate_product_lines()
        return res

    @api.onchange("session_id")
    def _onchange_session_id_products(self):
        self.product_line_ids = self._prepare_product_line_commands()

    @api.depends("product_line_ids")
    def _compute_show_products_sold(self):
        for dashboard in self:
            dashboard.show_products_sold = bool(dashboard.product_line_ids)

    def _get_product_rows(self):
        self.ensure_one()
        if not self.session_id:
            return []
        return self.session_id.get_avea_products_sold()

    def _prepare_product_line_commands(self):
        self.ensure_one()
        commands = [Command.clear()]
        for index, row in enumerate(self._get_product_rows(), start=1):
            commands.append(
                Command.create(
                    {
                        "rank": index,
                        "product_id": row["product_id"],
                        "product_name": row["product_name"],
                        "quantity_sold": row["quantity_sold"],
                        "sales_value": row["sales_value"],
                    }
                )
            )
        return commands

    def _populate_product_lines(self):
        ProductLine = self.env["avea.till.session.dashboard.product.line"]
        for dashboard in self:
            if not dashboard.id:
                continue
            ProductLine.search([("dashboard_id", "=", dashboard.id)]).unlink()
            rows = dashboard._get_product_rows()
            if not rows:
                continue
            ProductLine.create(
                [
                    {
                        "dashboard_id": dashboard.id,
                        "rank": index,
                        "product_id": row["product_id"],
                        "product_name": row["product_name"],
                        "quantity_sold": row["quantity_sold"],
                        "sales_value": row["sales_value"],
                    }
                    for index, row in enumerate(rows, start=1)
                ]
            )

    @api.model
    def action_open_session_dashboard(self, session_id=None):
        vals = {}
        if session_id:
            vals["session_id"] = session_id
        dashboard = self.create(vals)
        return {
            "type": "ir.actions.act_window",
            "name": _("Session Dashboard"),
            "res_model": "avea.till.session.dashboard",
            "view_mode": "form",
            "res_id": dashboard.id,
            "target": "current",
        }

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
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
    def _compute_session_info(self):
        for dashboard in self:
            session = dashboard.session_id
            dashboard.session_duration = (
                session.get_avea_session_duration_display() if session else ""
            )

    @api.depends("session_id", "session_id.currency_id")
    def _compute_session_metrics(self):
        zero_metrics = {
            "total_sales": 0.0,
            "cash_sales": 0.0,
            "card_sales": 0.0,
            "other_payments": 0.0,
            "order_count": 0,
            "average_order_value": 0.0,
            "expected_cash": 0.0,
            "activity_items_sold": 0.0,
            "activity_discount_total": 0.0,
            "activity_refund_count": 0,
            "activity_cash_movement_count": 0,
            "activity_cash_in_count": 0,
            "activity_cash_out_count": 0,
            "activity_cash_in_total": 0.0,
            "activity_cash_out_total": 0.0,
            "show_refund_attention": False,
        }
        for dashboard in self:
            session = dashboard.session_id
            if not session:
                dashboard.update(zero_metrics)
                continue

            sales = session.get_avea_sales_summary()
            activity = session.get_avea_activity_metrics()
            cash = session.get_avea_cash_summary()

            dashboard.update(
                {
                    "total_sales": sales["total_sales"],
                    "cash_sales": sales["cash_sales"],
                    "card_sales": sales["card_sales"],
                    "other_payments": sales["other_payments"],
                    "order_count": sales["order_count"],
                    "average_order_value": sales["average_order_value"],
                    "expected_cash": cash["expected_cash"],
                    "activity_items_sold": activity["items_sold"],
                    "activity_discount_total": activity["discount_total"],
                    "activity_refund_count": activity["refund_count"],
                    "activity_cash_movement_count": activity["cash_movement_count"],
                    "activity_cash_in_count": activity["cash_in_count"],
                    "activity_cash_out_count": activity["cash_out_count"],
                    "activity_cash_in_total": activity["cash_in_total"],
                    "activity_cash_out_total": activity["cash_out_total"],
                    "show_refund_attention": bool(activity["refund_count"]),
                }
            )

    def action_open_sessions(self):
        return self.env["ir.actions.act_window"]._for_xml_id(
            "avea_till.action_avea_sessions"
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
        return self.env["avea.till.session.dashboard"].action_open_session_dashboard(
            session_id=session_id
        )
