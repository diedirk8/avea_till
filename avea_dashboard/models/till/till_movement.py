from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

OPENING_FLOAT_REASON = "Opening Float"
CASH_SALE_REASON = "Cash Sale"
CASH_REFUND_REASON = "Cash Refund"
POS_CASH_IN_REASON = "POS Cash In"
POS_CASH_OUT_REASON = "POS Cash Out"


class AveaTillMovement(models.Model):
    _name = "avea.till.movement"
    _description = "Till Cash Movement"
    _order = "movement_date desc, id desc"
    _sql_constraints = [
        (
            "statement_line_unique",
            "unique(statement_line_id)",
            "Each bank statement line can only be linked to one till movement.",
        ),
    ]

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

    pos_order_id = fields.Many2one(
        "pos.order",
        string="POS Order",
        ondelete="set null",
        index=True,
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

    statement_line_id = fields.Many2one(
        "account.bank.statement.line",
        string="Bank Statement Line",
        ondelete="set null",
        index=True,
        copy=False,
    )

    ledger_reference = fields.Char(
        string="Reference",
        compute="_compute_ledger_reference",
        store=True,
        readonly=True,
    )

    @api.depends(
        "pos_order_id",
        "pos_order_id.pos_reference",
        "pos_order_id.name",
        "name",
        "notes",
        "reason",
        "session_id",
        "amount",
        "movement_date",
        "movement_type",
    )
    def _compute_ledger_reference(self):
        for movement in self:
            order = movement.pos_order_id
            if not order and movement.reason in ("Cash Sale", "Cash Refund"):
                order = movement._find_pos_order_for_movement()
            if order:
                movement.ledger_reference = movement._pos_order_ledger_reference(order)
                continue
            reference = movement.name
            if reference and reference != "/":
                movement.ledger_reference = reference
                continue
            reference = (
                movement.notes if movement.notes and movement.notes != "/" else False
            )
            movement.ledger_reference = reference or ""

    @api.model
    def _pos_order_ledger_reference(self, order):
        if order.pos_reference and order.pos_reference != "/":
            return order.pos_reference
        if order.name and order.name != "/":
            return order.name
        return ""

    def _find_pos_order_for_movement(self):
        self.ensure_one()
        if self.reason not in ("Cash Sale", "Cash Refund") or not self.session_id:
            return self.env["pos.order"]
        Order = self.env["pos.order"]
        identifiers = {
            value
            for value in (self.name, self.notes)
            if value and value != "/"
        }
        if identifiers:
            order = Order.search(
                [
                    ("session_id", "=", self.session_id.id),
                    "|",
                    ("name", "in", list(identifiers)),
                    ("pos_reference", "in", list(identifiers)),
                ],
                limit=1,
                order="id desc",
            )
            if order:
                return order
        orders = Order.search([("session_id", "=", self.session_id.id)])
        candidates = []
        for order in orders:
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
            if order.currency_id.compare_amounts(amount, self.amount) != 0:
                continue
            is_refund = order.is_refund or net_cash < 0
            if self.reason == "Cash Refund" and not is_refund:
                continue
            if self.reason == "Cash Sale" and is_refund:
                continue
            payment_date = max(cash_payments.mapped("payment_date"))
            candidates.append((order, payment_date))
        if not candidates:
            return Order
        if len(candidates) == 1:
            return candidates[0][0]
        movement_dt = self.movement_date
        return min(
            candidates,
            key=lambda item: abs((item[1] - movement_dt).total_seconds()),
        )[0]

    @api.model
    def _parse_manual_pos_cash_statement_line(self, session, line):
        """Return (reason, movement_type, notes) for a manual POS cash line, or None."""
        ref = (line.payment_ref or "").strip()
        session_name = (session.name or "").strip()
        if not ref or not session_name or ref == session_name:
            return None
        if ref.startswith("Cash difference observed"):
            return None
        prefix = f"{session_name}-"
        if not ref.startswith(prefix):
            return None
        suffix = ref[len(prefix) :]
        currency = session.currency_id or session.company_id.currency_id
        amount = abs(line.amount)
        if currency.compare_amounts(amount, 0.0) <= 0:
            return None
        if suffix.startswith("in-"):
            if currency.compare_amounts(line.amount, 0.0) <= 0:
                return None
            return (POS_CASH_IN_REASON, "in", suffix[3:])
        if suffix.startswith("out-"):
            if currency.compare_amounts(line.amount, 0.0) >= 0:
                return None
            return (POS_CASH_OUT_REASON, "out", suffix[4:])
        return None

    @api.model
    def _find_movement_for_statement_line(self, session, line, reason, amount):
        existing = self.search([("statement_line_id", "=", line.id)], limit=1)
        if existing:
            return existing
        ref = line.payment_ref or ""
        if ref:
            existing = self.search(
                [
                    ("session_id", "=", session.id),
                    ("name", "=", ref),
                    ("reason", "in", (POS_CASH_IN_REASON, POS_CASH_OUT_REASON)),
                    ("amount", "=", amount),
                ],
                limit=1,
            )
            if existing and (
                not existing.statement_line_id
                or existing.statement_line_id.id == line.id
            ):
                return existing
        existing = self.search(
            [
                ("session_id", "=", session.id),
                ("statement_line_id", "=", False),
                ("reason", "=", reason),
                ("amount", "=", amount),
            ],
            limit=1,
        )
        return existing

    @api.model
    def _upsert_manual_cash_movement_from_statement_line(self, session, line):
        parsed = self._parse_manual_pos_cash_statement_line(session, line)
        if not parsed:
            return self.browse()
        reason, movement_type, notes = parsed
        currency = session.currency_id or session.company_id.currency_id
        amount = abs(line.amount)
        existing = self._find_movement_for_statement_line(session, line, reason, amount)
        ref = line.payment_ref or reason
        if existing:
            vals = {}
            if not existing.statement_line_id:
                vals["statement_line_id"] = line.id
            if ref and existing.name != ref:
                vals["name"] = ref
            if vals:
                existing.write(vals)
            return existing
        return self.create(
            {
                "name": ref,
                "movement_date": line.create_date or fields.Datetime.now(),
                "session_id": session.id,
                "user_id": session.user_id.id or self.env.user.id,
                "movement_type": movement_type,
                "amount": amount,
                "reason": reason,
                "notes": notes or "",
                "statement_line_id": line.id,
            }
        )

    @api.model
    def _sync_manual_cash_movements_from_statement_lines(self, session):
        if not session:
            return
        for line in session.statement_line_ids.sorted("create_date asc, id asc"):
            self._upsert_manual_cash_movement_from_statement_line(session, line)

    @api.model
    def _backfill_session_pos_order_links(self, session):
        movements = self.search(
            [
                ("session_id", "=", session.id),
                ("reason", "in", ("Cash Sale", "Cash Refund")),
                ("pos_order_id", "=", False),
            ]
        )
        for movement in movements:
            order = movement._find_pos_order_for_movement()
            if not order:
                continue
            vals = {"pos_order_id": order.id}
            if not movement.name or movement.name == "/":
                vals["name"] = self._pos_order_ledger_reference(order)
            movement.write(vals)

    @api.model
    def _recompute_session_running_balances(self, session_id):
        if not session_id:
            return
        movements = self.search(
            [("session_id", "=", session_id)],
            order="movement_date asc, id asc",
        )
        balance = 0.0
        for movement in movements:
            balance += movement._signed_amount()
            movement.running_balance = balance

    @api.model
    def _ensure_opening_float(self, sessions):
        """Create the opening float ledger line for a POS session if missing."""
        for session in sessions:
            if self.search(
                [
                    ("session_id", "=", session.id),
                    ("reason", "=", OPENING_FLOAT_REASON),
                ],
                limit=1,
            ):
                continue
            amount = session.cash_register_balance_start or 0.0
            currency = session.currency_id or session.company_id.currency_id
            if currency.compare_amounts(amount, 0.0) <= 0:
                continue
            movement_date = session.start_at or fields.Datetime.now()
            earliest = self.search(
                [("session_id", "=", session.id)],
                order="movement_date asc, id asc",
                limit=1,
            )
            if earliest and earliest.movement_date <= movement_date:
                movement_date = earliest.movement_date - timedelta(seconds=1)
            reference = session.name
            if not reference or reference == "/":
                reference = f"Session {session.id}"
            self.create(
                {
                    "name": reference,
                    "movement_date": movement_date,
                    "session_id": session.id,
                    "user_id": session.user_id.id or self.env.user.id,
                    "movement_type": "in",
                    "amount": amount,
                    "reason": OPENING_FLOAT_REASON,
                    "notes": session.opening_notes or "",
                }
            )

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
    def prepare_session_ledger(self, session):
        if not session:
            return
        self._ensure_opening_float(session)
        self._sync_manual_cash_movements_from_statement_lines(session)
        self._backfill_session_pos_order_links(session)

    @api.model
    def get_session_ledger_balance(self, session_id):
        if not session_id:
            return 0.0
        last = self.search(
            [("session_id", "=", session_id)],
            order="movement_date desc, id desc",
            limit=1,
        )
        return last.running_balance if last else 0.0

    @api.model
    def get_sessions_ledger_balance(self, session_ids):
        if not session_ids:
            return {}
        balances = {session_id: 0.0 for session_id in session_ids}
        movements = self.search(
            [("session_id", "in", session_ids)],
            order="movement_date desc, id desc",
        )
        seen = set()
        for movement in movements:
            session_id = movement.session_id.id
            if session_id in seen:
                continue
            balances[session_id] = movement.running_balance
            seen.add(session_id)
            if len(seen) == len(session_ids):
                break
        return balances

    @api.model
    def sum_amount_for_domain(self, domain):
        groups = self._read_group(domain, [], ["amount:sum"])
        if not groups:
            return 0.0
        row = groups[0]
        if isinstance(row, dict):
            return row.get("amount:sum") or 0.0
        return row[0] or 0.0

    @api.model
    def get_session_manual_net(self, session_id):
        return self.get_sessions_manual_net([session_id]).get(session_id, 0.0)

    @api.model
    def get_sessions_manual_net(self, session_ids):
        if not session_ids:
            return {}
        groups = self._read_group(
            [
                ("session_id", "in", session_ids),
                ("reason", "!=", OPENING_FLOAT_REASON),
            ],
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
        Movement = self.env["avea.till.movement"]
        session_ids = {
            vals["session_id"]
            for vals in vals_list
            if vals.get("session_id")
            and vals.get("reason") != OPENING_FLOAT_REASON
        }
        for session_id in session_ids:
            Movement._ensure_opening_float(self.env["pos.session"].browse(session_id))
        records = super().create(vals_list)
        for session_id in records.mapped("session_id").ids:
            records._recompute_session_running_balances(session_id)
        return records
