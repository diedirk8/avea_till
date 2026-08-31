from odoo import _, api, fields, models

from .till_movement import (
    CASH_REFUND_REASON,
    CASH_SALE_REASON,
    OPENING_FLOAT_REASON,
    POS_CASH_IN_REASON,
    POS_CASH_OUT_REASON,
)

class PosSession(models.Model):
    _inherit = "pos.session"

    @api.depends("config_id", "payment_method_ids")
    def _compute_cash_journal(self):
        closed = self.filtered(lambda session: session.state == "closed")
        active = self - closed
        if active:
            super(PosSession, active)._compute_cash_journal()
        for session in closed:
            session.cash_journal_id = session.cash_journal_id

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

    @api.model
    def _avea_paid_order_states(self):
        valid_states = {
            state
            for state, _label in self.env["pos.order"]._fields["state"].selection
        }
        paid_states = [
            state for state in ("paid", "done", "invoiced") if state in valid_states
        ]
        return paid_states or ["paid"]

    def _avea_paid_order_domain(self):
        self.ensure_one()
        return [
            ("session_id", "=", self.id),
            ("state", "in", self._avea_paid_order_states()),
        ]

    def get_avea_paid_orders(self):
        self.ensure_one()
        return self.env["pos.order"].search(self._avea_paid_order_domain())

    @api.model
    def _avea_net_cash_from_payments(self, payments):
        """Cash applied to the sale: tender minus change given back."""
        net_cash = 0.0
        for payment in payments.filtered(
            lambda line: line.payment_method_id.type == "cash"
        ):
            if payment.is_change:
                net_cash -= abs(payment.amount)
            else:
                net_cash += payment.amount
        return net_cash

    @api.model
    def _avea_sales_summary_from_orders(self, orders):
        """Payment and order totals for a paid POS order recordset."""
        order_count = len(orders)
        # amount_total is the POS gross (tax-inclusive). amount_tax is Odoo's
        # computed tax on the order (VAT, GST, sales tax, mixed, or zero).
        total_sales = sum(orders.mapped("amount_total"))
        sales_tax = sum(orders.mapped("amount_tax"))
        average_order_value = total_sales / order_count if order_count else 0.0

        # Cash is the sale amount paid in cash, not cash tendered.
        cash_sales = self._avea_net_cash_from_payments(orders.payment_ids)
        card_sales = 0.0
        other_payments = 0.0
        for payment in orders.payment_ids.filtered(lambda p: not p.is_change):
            method_type = payment.payment_method_id.type
            if method_type == "cash":
                continue
            elif method_type == "bank":
                card_sales += payment.amount
            else:
                other_payments += payment.amount

        return {
            "total_sales": total_sales,
            "cash_sales": cash_sales,
            "card_sales": card_sales,
            "other_payments": other_payments,
            "order_count": order_count,
            "average_order_value": average_order_value,
            "sales_after_tax": total_sales,
            "sales_tax": sales_tax,
            "sales_before_tax": total_sales - sales_tax,
        }

    @api.model
    def _avea_activity_from_orders(self, orders):
        """Operational counts for a paid POS order recordset."""
        lines = orders.lines
        discount_total = 0.0
        for line in lines:
            if line.discount:
                discount_total += line.qty * line.price_unit * (line.discount / 100.0)

        refund_orders = orders.filtered(
            lambda order: order.is_refund
            or order.currency_id.compare_amounts(order.amount_total, 0.0) < 0
        )
        return {
            "order_count": len(orders),
            "items_sold": sum(lines.mapped("qty")),
            "discount_total": discount_total,
            "refund_count": len(refund_orders),
            "refund_amount": abs(sum(refund_orders.mapped("amount_total"))),
        }

    @api.model
    def _avea_products_from_orders(self, orders, limit=None):
        """Products sold on the given orders, ranked by net quantity sold."""
        Line = self.env["pos.order.line"]
        order_ids = orders.ids
        if not order_ids:
            return []

        groups = Line._read_group(
            [
                ("order_id", "in", order_ids),
                ("product_id.type", "not in", ("service", "combo")),
                ("combo_line_ids", "=", False),
            ],
            groupby=["product_id"],
            aggregates=["qty:sum", "price_subtotal_incl:sum"],
        )

        ranked = sorted(
            (
                (product, quantity_sold, sales_value)
                for product, quantity_sold, sales_value in groups
                if product and quantity_sold > 0
            ),
            key=lambda row: (-row[1], -row[2], row[0].id),
        )
        if limit:
            ranked = ranked[:limit]

        return [
            {
                "product_id": product.id,
                "product_name": product.display_name,
                "quantity_sold": quantity_sold,
                "sales_value": sales_value,
            }
            for product, quantity_sold, sales_value in ranked
        ]

    def get_avea_cash_summary(self):
        """Cash drawer breakdown from the Avea till ledger."""
        self.ensure_one()
        Movement = self.env["avea.till.movement"]
        Movement.prepare_session_ledger(self)
        domain = [("session_id", "=", self.id)]
        return {
            "opening_float": Movement.sum_amount_for_domain(
                domain + [("reason", "=", OPENING_FLOAT_REASON)]
            ),
            "cash_sales": Movement.sum_amount_for_domain(
                domain + [("reason", "=", CASH_SALE_REASON)]
            ),
            "cash_in": Movement.sum_amount_for_domain(
                domain + [("reason", "=", POS_CASH_IN_REASON)]
            ),
            "cash_out": Movement.sum_amount_for_domain(
                domain + [("reason", "=", POS_CASH_OUT_REASON)]
            ),
            "cash_refunds": Movement.sum_amount_for_domain(
                domain + [("reason", "=", CASH_REFUND_REASON)]
            ),
            "expected_cash": Movement.get_session_ledger_balance(self.id),
            "movement_count": Movement.search_count(domain),
        }

    def get_avea_sales_summary(self):
        """Payment and order totals for the full POS session."""
        self.ensure_one()
        return self._avea_sales_summary_from_orders(self.get_avea_paid_orders())

    def get_avea_activity_metrics(self):
        """Operational counts for the full POS session."""
        self.ensure_one()
        Movement = self.env["avea.till.movement"]
        Movement.prepare_session_ledger(self)
        activity = self._avea_activity_from_orders(self.get_avea_paid_orders())

        session_domain = [("session_id", "=", self.id)]
        cash_in_domain = session_domain + [("reason", "=", POS_CASH_IN_REASON)]
        cash_out_domain = session_domain + [("reason", "=", POS_CASH_OUT_REASON)]

        activity.update(
            {
                "cash_movement_count": Movement.search_count(session_domain),
                "cash_in_count": Movement.search_count(cash_in_domain),
                "cash_out_count": Movement.search_count(cash_out_domain),
                "cash_in_total": Movement.sum_amount_for_domain(cash_in_domain),
                "cash_out_total": Movement.sum_amount_for_domain(cash_out_domain),
            }
        )
        return activity

    def get_avea_products_sold(self):
        """All products sold during the session, ranked by net quantity sold."""
        return self.get_avea_top_products(limit=None)

    def get_avea_top_products(self, limit=None):
        """Products sold in the session ranked by net quantity sold.

        Pass limit to cap the result set. Session Dashboard uses the uncapped
        list via get_avea_products_sold().
        """
        self.ensure_one()
        return self._avea_products_from_orders(
            self.get_avea_paid_orders(),
            limit=limit,
        )

    def action_avea_open_session_dashboard(self):
        self.ensure_one()
        return self.env["avea.till.session.dashboard"].action_open_session_dashboard(
            session_id=self.id
        )

    def get_formview_action(self, access_uid=None):
        if self.env.context.get("avea_open_session_dashboard"):
            self.ensure_one()
            return self.action_avea_open_session_dashboard()
        return super().get_formview_action(access_uid=access_uid)

    def get_avea_session_duration_display(self):
        self.ensure_one()
        if not self.start_at:
            return ""
        end = self.stop_at or fields.Datetime.now()
        total_seconds = max(int((end - self.start_at).total_seconds()), 0)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _seconds = divmod(remainder, 60)
        if hours:
            return _("%(hours)sh %(minutes)sm", hours=hours, minutes=minutes)
        return _("%(minutes)sm", minutes=minutes or 1)

    def set_opening_control(self, cashbox_value, notes):
        super().set_opening_control(cashbox_value, notes)
        self.env["avea.till.movement"]._ensure_opening_float(self)

    def load_data(self, models_to_load):
        response = super().load_data(models_to_load)
        cash_up_xmlid = "avea_till.group_avea_cash_up_user"
        manager_xmlid = "avea_till.group_avea_cash_up_manager"
        correct_xmlid = "avea_till.group_avea_correct_payment"
        for user_data in response.get("res.users", []):
            user = self.env["res.users"].browse(user_data["id"])
            can_cash_up = user.has_group(cash_up_xmlid)
            can_correct = user.has_group(correct_xmlid)
            user_data["can_cash_up_own_till"] = can_cash_up
            user_data["_can_cash_up_own_till"] = can_cash_up
            user_data["can_cash_up_manager"] = user.has_group(manager_xmlid)
            user_data["_can_cash_up_manager"] = user.has_group(manager_xmlid)
            user_data["can_correct_payment_method"] = can_correct
            user_data["_can_correct_payment_method"] = can_correct
        for employee_data in response.get("hr.employee", []):
            user = self.env["hr.employee"].browse(employee_data["id"]).user_id
            can_cash_up = bool(user) and user.has_group(cash_up_xmlid)
            can_correct = bool(user) and user.has_group(correct_xmlid)
            employee_data["can_cash_up_own_till"] = can_cash_up
            employee_data["_can_cash_up_own_till"] = can_cash_up
            employee_data["can_cash_up_manager"] = bool(user) and user.has_group(
                manager_xmlid
            )
            employee_data["_can_cash_up_manager"] = bool(user) and user.has_group(
                manager_xmlid
            )
            employee_data["can_correct_payment_method"] = can_correct
            employee_data["_can_correct_payment_method"] = can_correct
        return response

    def try_cash_in_out(self, _type, amount, reason, partner_id, extras):
        sign = 1 if _type == "in" else -1
        result = super().try_cash_in_out(_type, amount, reason, partner_id, extras)
        Movement = self.env["avea.till.movement"]
        for session in self.filtered("cash_journal_id"):
            statement_line = session.statement_line_ids.filtered(
                lambda line: line.currency_id.compare_amounts(line.amount, sign * amount) == 0
            ).sorted("create_date desc")[:1]
            if statement_line:
                Movement._upsert_manual_cash_movement_from_statement_line(
                    session, statement_line
                )
        return result
