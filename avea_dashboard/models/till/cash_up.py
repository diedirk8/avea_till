from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import formatLang


class AveaCashUp(models.Model):
    _name = "avea.cash.up"
    _description = "POS Cash Up"
    _order = "create_date desc, id desc"
    _session_unique = models.Constraint(
        "unique(session_id)",
        "This session has already been cashed up.",
    )

    name = fields.Char(string="Reference", required=True, copy=False, default="/")
    session_id = fields.Many2one(
        "pos.session",
        string="Session",
        required=True,
        index=True,
        ondelete="restrict",
    )
    config_id = fields.Many2one(
        related="session_id.config_id",
        string="Till",
        store=True,
    )
    company_id = fields.Many2one(
        related="session_id.config_id.company_id",
        store=True,
    )
    currency_id = fields.Many2one(
        related="session_id.currency_id",
        store=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Cashed Up By",
        required=True,
        default=lambda self: self.env.user,
    )
    cashier_name = fields.Char(string="Cashier")
    cash_up_date = fields.Datetime(
        string="Date",
        required=True,
        default=fields.Datetime.now,
    )
    opening_cash = fields.Monetary(currency_field="currency_id")
    expected_cash = fields.Monetary(currency_field="currency_id")
    counted_cash = fields.Monetary(string="Counted Cash", currency_field="currency_id")
    difference = fields.Monetary(string="Difference", currency_field="currency_id")
    cash_to_bag = fields.Monetary(string="Cash to Safe", currency_field="currency_id")
    remaining_cash = fields.Monetary(
        string="Remaining in Till",
        currency_field="currency_id",
    )
    variance_reason = fields.Text(string="Reason for Variance")
    payment_line_ids = fields.One2many(
        "avea.cash.up.payment.line",
        "cash_up_id",
        string="Payment Reconciliation",
        copy=False,
    )
    total_payments_expected = fields.Monetary(
        string="Total Payments Expected",
        currency_field="currency_id",
    )
    total_payments_counted = fields.Monetary(
        string="Total Payments Counted",
        currency_field="currency_id",
    )
    total_payments_difference = fields.Monetary(
        string="Total Payments Difference",
        currency_field="currency_id",
    )
    till_journal_id = fields.Many2one("account.journal", string="Till Journal")
    safe_journal_id = fields.Many2one(
        "account.journal",
        string="Cash Safe / Company Cash Journal",
    )
    statement_line_id = fields.Many2one(
        "account.bank.statement.line",
        string="Safe Drop Line",
        copy=False,
        ondelete="restrict",
    )
    state = fields.Selection(
        [("confirmed", "Confirmed")],
        default="confirmed",
        required=True,
    )
    transaction_count = fields.Integer(string="Transactions", readonly=True)
    has_variance = fields.Boolean(string="Has Variance", readonly=True)

    def write(self, vals):
        if self.env.context.get("avea_cash_up_setup"):
            return super().write(vals)
        if self.filtered(lambda rec: rec.state == "confirmed"):
            raise UserError(_("A confirmed cash-up cannot be changed."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda rec: rec.state == "confirmed"):
            raise UserError(_("A confirmed cash-up cannot be deleted."))
        return super().unlink()

    def _avea_payment_kind_label_map(self):
        return dict(self.env["pos.session"]._avea_payment_kind_labels())

    def _avea_stored_has_variance(self):
        self.ensure_one()
        currency = self.currency_id
        if currency.compare_amounts(self.difference, 0.0) != 0:
            return True
        if currency.compare_amounts(self.total_payments_difference, 0.0) != 0:
            return True
        return any(
            currency.compare_amounts(line.difference, 0.0) != 0
            for line in self.payment_line_ids
            if line.payment_kind != "cash"
        )

    def _avea_payment_line_has_activity(self, line_payload):
        for key in ("expected_amount", "counted_amount", "difference_amount"):
            if abs(line_payload.get(key) or 0.0) > 0.0000001:
                return True
        return False

    def get_receipt_payload(self):
        """Rebuild the Cash Up slip payload from stored record data only."""
        self.ensure_one()
        currency = self.currency_id

        def money(value):
            return formatLang(self.env, value, currency_obj=currency)

        kind_labels = self._avea_payment_kind_label_map()
        payment_lines = []
        for line in self.payment_line_ids.sorted("sequence"):
            kind = line.payment_kind
            payment_lines.append(
                {
                    "kind": kind,
                    "label": kind_labels.get(kind, kind),
                    "expected": money(line.expected),
                    "counted": money(line.counted),
                    "difference": money(line.difference),
                    "variance": money(line.difference),
                    "expected_amount": line.expected,
                    "counted_amount": line.counted,
                    "difference_amount": line.difference,
                    "variance_amount": line.difference,
                }
            )
        has_variance = bool(self.has_variance) or self._avea_stored_has_variance()

        if currency.compare_amounts(self.total_payments_difference, 0.0) != 0:
            variance_label = money(self.total_payments_difference)
            variance_amount = self.total_payments_difference
        else:
            variance_label = money(self.difference)
            variance_amount = self.difference

        cash_up_date = fields.Datetime.context_timestamp(self, self.cash_up_date)
        return {
            "company": self.company_id.name,
            "company_logo_url": (
                f"/web/image/res.company/{self.company_id.id}/logo"
                if self.company_id.logo
                else False
            ),
            "till": self.config_id.name,
            "session": self.session_id.name,
            "date": cash_up_date.strftime("%Y-%m-%d %H:%M"),
            "cashier": self.cashier_name or "",
            "opening_cash": money(self.opening_cash),
            "expected_cash": money(self.expected_cash),
            "counted_cash": money(self.counted_cash),
            "difference": money(self.difference),
            "cash_to_bag": money(self.cash_to_bag),
            "remaining_cash": money(self.remaining_cash),
            "opening_cash_amount": self.opening_cash,
            "expected_cash_amount": self.expected_cash,
            "counted_cash_amount": self.counted_cash,
            "difference_amount": self.difference,
            "cash_to_bag_amount": self.cash_to_bag,
            "remaining_cash_amount": self.remaining_cash,
            "payment_lines": payment_lines,
            "active_payment_lines": [
                line
                for line in payment_lines
                if self._avea_payment_line_has_activity(line)
            ],
            "total_payments_expected": money(self.total_payments_expected),
            "total_payments_counted": money(self.total_payments_counted),
            "total_payments_difference": money(self.total_payments_difference),
            "total_payments_expected_amount": self.total_payments_expected,
            "total_payments_counted_amount": self.total_payments_counted,
            "total_payments_difference_amount": self.total_payments_difference,
            "total_variance": money(self.total_payments_difference),
            "total_variance_amount": self.total_payments_difference,
            "transaction_count": self.transaction_count,
            "variance_reason": self.variance_reason or "",
            "has_variance": has_variance,
            "variance_label": variance_label,
            "variance_amount": variance_amount,
        }

    def action_reprint_receipt(self):
        self.ensure_one()
        report = self.env.ref("avea_till.action_report_avea_cash_up_receipt")
        return {
            "type": "ir.actions.act_url",
            "url": f"/report/html/{report.report_name}/{self.id}",
            "target": "new",
        }

    @api.model
    def _avea_user_is_cash_up_manager(self):
        return self.env.user.has_group("avea_till.group_avea_cash_up_manager")

    @api.model
    def _avea_user_can_cash_up(self):
        return self.env.user.has_group("avea_till.group_avea_cash_up_user")

    @api.model
    def _avea_check_own_till(self, session):
        user = self.env.user
        if self._avea_user_is_cash_up_manager():
            return
        if not self._avea_user_can_cash_up():
            raise AccessError(_("You do not have permission to cash up a till."))
        if session.config_id.current_session_id != session:
            raise AccessError(_("You can only cash up the till you are operating."))
        current_user = session.config_id.current_user_id
        employee_user = self.env["res.users"]
        if "employee_id" in session._fields and session.employee_id:
            employee_user = session.employee_id.user_id
        if user not in (session.user_id | current_user | employee_user):
            raise AccessError(_("You can only cash up the till you are operating."))

    @api.model
    def _avea_unconfigured_error(self):
        return UserError(
            _(
                "Cash management has not been configured. "
                "Please contact an administrator."
            )
        )

    @api.model
    def _avea_session_cashier_name(self, session, cashier_name=False):
        if cashier_name:
            return cashier_name
        if "employee_id" in session._fields and session.employee_id:
            return session.employee_id.name
        return session.user_id.name

    @api.model
    def _avea_safe_journal(self, company):
        journal = company.avea_cash_safe_journal_id
        if not journal or not company._avea_is_physical_cash_journal(journal):
            raise self._avea_unconfigured_error()
        return journal

    @api.model
    def _avea_opening_cash(self, session):
        return session.cash_register_balance_start or 0.0

    @api.model
    def _avea_expected_cash(self, session):
        session.invalidate_recordset(
            ["cash_register_balance_end", "cash_register_difference"]
        )
        return session.cash_register_balance_end or 0.0

    @api.model
    def _avea_amounts(self, session, counted_cash):
        currency = session.currency_id
        opening = self._avea_opening_cash(session)
        expected = self._avea_expected_cash(session)
        counted = counted_cash or 0.0
        if currency.compare_amounts(counted, 0.0) < 0:
            raise UserError(_("Counted Cash cannot be negative."))
        difference = currency.round(counted - expected)
        if currency.compare_amounts(counted, opening) >= 0:
            cash_to_bag = currency.round(counted - opening)
            remaining = opening
        else:
            cash_to_bag = 0.0
            remaining = counted
        return {
            "opening": opening,
            "expected": expected,
            "counted": counted,
            "difference": difference,
            "cash_to_bag": cash_to_bag,
            "remaining": remaining,
        }

    @api.model
    def _avea_normalize_counted_payments(self, counted_payments):
        if not counted_payments:
            return {}
        if not isinstance(counted_payments, dict):
            raise UserError(_("Payment counts must be provided as a mapping."))
        allowed = {"card", "eft", "store_credit", "other"}
        normalized = {}
        for key, value in counted_payments.items():
            if key not in allowed:
                continue
            if value in (None, ""):
                continue
            amount = float(value)
            if amount < 0:
                raise UserError(
                    _("Counted amounts cannot be negative (%(method)s).", method=key)
                )
            normalized[key] = amount
        return normalized

    @api.model
    def _avea_payment_reconciliation(self, session, counted_cash, counted_payments=None):
        currency = session.currency_id
        base = session.get_avea_payment_reconciliation_expected()
        opening = base["opening_cash"]
        counted_map = self._avea_normalize_counted_payments(counted_payments)
        physical_cash = counted_cash or 0.0
        cash_register_expected = base["cash_register_expected"]
        cash_payments_expected = base["cash_payments_expected"]
        lines = []
        total_counted = 0.0
        for line in base["lines"]:
            kind = line["kind"]
            expected = line["expected"]
            if kind == "cash":
                line_expected = cash_register_expected
                counted = physical_cash
                total_counted += cash_payments_expected
            elif line.get("is_editable"):
                line_expected = expected
                counted = counted_map.get(kind, expected)
                total_counted += counted
            else:
                line_expected = expected
                counted = counted_map.get(kind, expected)
                total_counted += counted
            difference = currency.round(counted - line_expected)
            lines.append(
                {
                    "kind": kind,
                    "label": line["label"],
                    "expected": line_expected,
                    "counted": counted,
                    "difference": difference,
                    "sequence": line["sequence"],
                    "is_editable": line.get("is_editable", False),
                    "is_visible": line.get("is_visible", True),
                }
            )
        total_expected = base["total_expected"]
        total_counted = currency.round(total_counted)
        total_difference = currency.round(total_counted - total_expected)
        return {
            "lines": lines,
            "total_expected": total_expected,
            "total_counted": total_counted,
            "total_difference": total_difference,
            "opening_cash": opening,
            "transaction_count": base["transaction_count"],
            "cash_register_expected": base["cash_register_expected"],
            "cash_payments_expected": base["cash_payments_expected"],
        }

    @api.model
    def _avea_has_payment_variance(self, reconciliation, currency, cash_difference=0.0):
        if currency.compare_amounts(reconciliation["total_difference"], 0.0) != 0:
            return True
        if currency.compare_amounts(cash_difference, 0.0) != 0:
            return True
        return any(
            currency.compare_amounts(line["difference"], 0.0) != 0
            for line in reconciliation["lines"]
            if line["kind"] != "cash"
        )

    @api.model
    def _avea_validate_variance_reason(
        self, reconciliation, variance_reason, currency, cash_difference=0.0
    ):
        if not self._avea_has_payment_variance(
            reconciliation, currency, cash_difference=cash_difference
        ):
            return
        reason = (variance_reason or "").strip()
        if not reason:
            raise UserError(
                _("Enter a reason for the variance before confirming Cash Up.")
            )

    @api.model
    def pos_get_cash_up_preview(self, session_id):
        session = self.env["pos.session"].browse(session_id).exists()
        if not session:
            raise UserError(_("This POS session was not found."))
        self._avea_check_own_till(session)
        if session.state == "closed":
            raise UserError(_("This session is already closed."))
        if self.search_count([("session_id", "=", session.id)]):
            raise UserError(_("This session has already been cashed up."))
        self._avea_safe_journal(session.company_id)
        if session.config_id._avea_pos_needs_dedicated_cash_journal():
            raise self._avea_unconfigured_error()
        amounts = self._avea_amounts(session, session.cash_register_balance_end or 0.0)
        cashier = self._avea_session_cashier_name(session)
        reconciliation = self._avea_payment_reconciliation(
            session,
            amounts["expected"],
            counted_payments=None,
        )
        return self._avea_receipt_payload(
            session,
            amounts,
            cashier,
            reconciliation,
            counted_is_expected=True,
        )

    @api.model
    def pos_confirm_cash_up(
        self,
        session_id,
        counted_cash,
        counted_payments=None,
        variance_reason=False,
        cashier_name=False,
    ):
        # Backward compatibility: older clients passed cashier_name positionally.
        if isinstance(counted_payments, str) and not cashier_name:
            cashier_name = counted_payments
            counted_payments = None
        session = self.env["pos.session"].browse(session_id).exists()
        if not session:
            raise UserError(_("This POS session was not found."))
        self._avea_check_own_till(session)
        if session.state == "closed":
            raise UserError(_("This session is already closed."))
        if self.search_count([("session_id", "=", session.id)]):
            raise UserError(_("This session has already been cashed up."))

        blocked = session._cannot_close_session()
        if blocked:
            raise UserError(blocked.get("message") or _("This session cannot be closed."))

        safe_journal = self._avea_safe_journal(session.company_id)
        till_journal = session.cash_journal_id
        if not till_journal or not till_journal.default_account_id:
            raise self._avea_unconfigured_error()
        if till_journal == safe_journal:
            raise self._avea_unconfigured_error()
        if till_journal.default_account_id == safe_journal.default_account_id:
            raise self._avea_unconfigured_error()
        if session.config_id._avea_pos_needs_dedicated_cash_journal():
            raise self._avea_unconfigured_error()

        amounts = self._avea_amounts(session, counted_cash)
        reconciliation = self._avea_payment_reconciliation(
            session,
            counted_cash,
            counted_payments,
        )
        self._avea_validate_variance_reason(
            reconciliation,
            variance_reason,
            session.currency_id,
            cash_difference=amounts["difference"],
        )
        cashier = self._avea_session_cashier_name(session, cashier_name)
        statement_line = self.env["account.bank.statement.line"]
        if session.currency_id.compare_amounts(amounts["cash_to_bag"], 0.0) > 0:
            statement_line = self._avea_post_safe_drop(
                session, till_journal, safe_journal, amounts
            )
            self.env["avea.till.movement"]._create_cash_up_safe_drop(
                session, statement_line, amounts["cash_to_bag"], safe_journal
            )
        recorded_has_variance = self._avea_has_payment_variance(
            reconciliation,
            session.currency_id,
            cash_difference=amounts["difference"],
        )
        cash_up = self.sudo().create(
            {
                "name": session.name or "/",
                "session_id": session.id,
                "user_id": self.env.user.id,
                "cashier_name": cashier,
                "cash_up_date": fields.Datetime.now(),
                "opening_cash": amounts["opening"],
                "expected_cash": amounts["expected"],
                "counted_cash": amounts["counted"],
                "difference": amounts["difference"],
                "cash_to_bag": amounts["cash_to_bag"],
                "remaining_cash": amounts["remaining"],
                "variance_reason": (variance_reason or "").strip() or False,
                "transaction_count": session.get_avea_transaction_count(),
                "has_variance": recorded_has_variance,
                "total_payments_expected": reconciliation["total_expected"],
                "total_payments_counted": reconciliation["total_counted"],
                "total_payments_difference": reconciliation["total_difference"],
                "payment_line_ids": [
                    (
                        0,
                        0,
                        {
                            "payment_kind": line["kind"],
                            "sequence": line["sequence"],
                            "expected": line["expected"],
                            "counted": line["counted"],
                            "difference": line["difference"],
                        },
                    )
                    for line in reconciliation["lines"]
                ],
                "till_journal_id": till_journal.id,
                "safe_journal_id": safe_journal.id,
                "statement_line_id": statement_line.id or False,
                "state": "confirmed",
            }
        )

        session.invalidate_recordset(
            ["cash_register_balance_end", "cash_register_difference"]
        )
        details = session.post_closing_cash_details(amounts["remaining"])
        if not details.get("successful"):
            raise UserError(
                details.get("message") or _("The counted cash could not be stored.")
            )

        close_result = session.close_session_from_ui()
        session.invalidate_recordset(["state"])
        if (
            not close_result
            or not close_result.get("successful")
            or session.state != "closed"
        ):
            raise UserError(
                _("The session could not be closed. Cash Up was not recorded.")
            )

        self.env["avea.till.movement"]._sync_cash_difference_from_statement_lines(session)
        reconciliation["variance_reason"] = (variance_reason or "").strip()
        return {
            "successful": True,
            "cash_up_id": cash_up.id,
            "receipt": cash_up._avea_receipt_payload(
                session,
                amounts,
                cashier,
                reconciliation,
            ),
        }

    @api.model
    def _avea_post_safe_drop(self, session, till_journal, safe_journal, amounts):
        return (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(
                {
                    "pos_session_id": session.id,
                    "journal_id": till_journal.id,
                    "amount": -amounts["cash_to_bag"],
                    "date": fields.Date.context_today(self),
                    "payment_ref": _("Cash Up / Safe Drop"),
                    "partner_id": session.company_id.partner_id.id,
                    "counterpart_account_id": safe_journal.default_account_id.id,
                }
            )
        )

    @api.model
    def _avea_receipt_payload(
        self,
        session,
        amounts,
        cashier,
        reconciliation,
        counted_is_expected=False,
    ):
        currency = session.currency_id
        counted = amounts["expected"] if counted_is_expected else amounts["counted"]
        difference = (
            0.0
            if counted_is_expected
            else amounts["difference"]
        )
        cash_to_bag = (
            max(counted - amounts["opening"], 0.0)
            if counted_is_expected
            else amounts["cash_to_bag"]
        )

        def money(value):
            return formatLang(self.env, value, currency_obj=currency)

        payment_lines = []
        for line in reconciliation["lines"]:
            payment_expected = line["expected"]
            if line["kind"] == "cash":
                line_counted = (
                    line["expected"] if counted_is_expected else line["counted"]
                )
            else:
                line_counted = (
                    line["expected"] if counted_is_expected else line["counted"]
                )
            line_difference = (
                0.0
                if counted_is_expected
                else currency.round(line_counted - payment_expected)
            )
            payment_lines.append(
                {
                    "kind": line["kind"],
                    "label": line["label"],
                    "expected": money(payment_expected),
                    "counted": money(line_counted),
                    "difference": money(line_difference),
                    "variance": money(line_difference),
                    "expected_amount": payment_expected,
                    "counted_amount": line_counted,
                    "difference_amount": line_difference,
                    "variance_amount": line_difference,
                    "is_editable": line.get("is_editable", False),
                }
            )
        total_counted = (
            reconciliation["total_expected"]
            if counted_is_expected
            else reconciliation["total_counted"]
        )
        total_difference = (
            0.0 if counted_is_expected else reconciliation["total_difference"]
        )
        variance_reason = reconciliation.get("variance_reason") or ""
        has_variance = (
            not counted_is_expected
            and self._avea_has_payment_variance(
                reconciliation,
                currency,
                cash_difference=difference,
            )
        )
        payment_summary = []
        summary_labels = {
            "cash": _("Cash Payments"),
            "card": _("Card Payments"),
            "eft": _("EFT Payments"),
            "store_credit": _("Store Credit"),
            "other": _("Other"),
        }
        payment_expected = session.get_avea_payment_reconciliation_expected()
        kind_amounts = {
            line["kind"]: line["expected"] for line in payment_expected["lines"]
        }
        for kind, label in session._avea_payment_kind_labels():
            if kind == "cash":
                amount = payment_expected["cash_payments_expected"]
            else:
                amount = kind_amounts.get(kind, 0.0)
            payment_summary.append(
                {
                    "kind": kind,
                    "label": summary_labels.get(kind, label),
                    "amount": money(amount),
                    "amount_value": amount,
                }
            )

        return {
            "company": session.company_id.name,
            "till": session.config_id.name,
            "session": session.name,
            "date": fields.Datetime.context_timestamp(
                session, fields.Datetime.now()
            ).strftime("%Y-%m-%d %H:%M"),
            "cashier": cashier or "",
            "opening_cash": money(amounts["opening"]),
            "expected_cash": money(amounts["expected"]),
            "counted_cash": money(counted),
            "difference": money(difference),
            "cash_to_bag": money(cash_to_bag),
            "remaining_cash": money(amounts["remaining"]),
            "opening_cash_amount": amounts["opening"],
            "expected_cash_amount": amounts["expected"],
            "counted_cash_amount": counted,
            "difference_amount": difference,
            "cash_to_bag_amount": cash_to_bag,
            "remaining_cash_amount": amounts["remaining"],
            "payment_lines": payment_lines,
            "payment_summary": payment_summary,
            "total_payments_expected": money(reconciliation["total_expected"]),
            "total_payments_counted": money(total_counted),
            "total_payments_difference": money(total_difference),
            "total_payments_expected_amount": reconciliation["total_expected"],
            "total_payments_counted_amount": total_counted,
            "total_payments_difference_amount": total_difference,
            "total_variance": money(total_difference),
            "total_variance_amount": total_difference,
            "transaction_count": session.get_avea_transaction_count(),
            "cash_payments_expected": money(
                reconciliation.get("cash_payments_expected", 0.0)
            ),
            "cash_payments_expected_amount": reconciliation.get(
                "cash_payments_expected", 0.0
            ),
            "variance_reason": variance_reason,
            "has_variance": has_variance,
        }
