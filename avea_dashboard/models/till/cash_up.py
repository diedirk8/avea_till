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
        return self._avea_receipt_payload(
            session,
            amounts,
            cashier,
            counted_is_expected=True,
        )

    @api.model
    def pos_confirm_cash_up(self, session_id, counted_cash, cashier_name=False):
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
        cashier = self._avea_session_cashier_name(session, cashier_name)
        statement_line = self.env["account.bank.statement.line"]
        if session.currency_id.compare_amounts(amounts["cash_to_bag"], 0.0) > 0:
            statement_line = self._avea_post_safe_drop(
                session, till_journal, safe_journal, amounts
            )
            self.env["avea.till.movement"]._create_cash_up_safe_drop(
                session, statement_line, amounts["cash_to_bag"], safe_journal
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
        return {
            "successful": True,
            "cash_up_id": cash_up.id,
            "receipt": cash_up._avea_receipt_payload(session, amounts, cashier),
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
    def _avea_receipt_payload(self, session, amounts, cashier, counted_is_expected=False):
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
        }
