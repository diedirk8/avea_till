import base64
import logging

from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import formataddr
from odoo.tools.misc import formatLang

_logger = logging.getLogger(__name__)


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
            # Store Credit issuance (e.g. exchange credit) is a negative payment total.
            if amount < 0 and key != "store_credit":
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
        self._avea_schedule_register_closure_report_email(cash_up.id, session.id)
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
    def _avea_schedule_register_closure_report_email(self, cash_up_id, session_id):
        if not cash_up_id or not session_id:
            return
        registry = self.env.registry
        dbname = self.env.cr.dbname

        def _send_after_commit():
            try:
                with registry.cursor() as cr:
                    env = api.Environment(cr, api.SUPERUSER_ID, {})
                    cash_up = env["avea.cash.up"].browse(cash_up_id).exists()
                    session = env["pos.session"].browse(session_id).exists()
                    if cash_up and session:
                        cash_up._send_register_closure_report_email(session)
                    cr.commit()
            except Exception:
                _logger.exception(
                    "Failed to email register closure report for session %s",
                    session_id,
                )

        self.env.cr.postcommit.add(_send_after_commit)

    def _avea_register_closure_report_date_label(self):
        self.ensure_one()
        if self.cash_up_date:
            local_dt = fields.Datetime.context_timestamp(self, self.cash_up_date)
            return fields.Date.to_string(local_dt.date())
        return fields.Date.to_string(fields.Date.context_today(self))

    def _avea_register_closure_report_subject(self, session):
        self.ensure_one()
        session_name = session.name or str(session.id)
        return _("Register Closure Report - %s - %s") % (
            session_name,
            self._avea_register_closure_report_date_label(),
        )

    def _avea_register_closure_report_sale_summary(self, session):
        self.ensure_one()
        report = self.env["report.point_of_sale.report_saledetails"]
        details = report.get_sale_details(
            False,
            False,
            session.config_id.ids,
            session.ids,
        )
        payments_per_method = []
        for payment in details.get("payments_per_method") or []:
            payments_per_method.append(
                {
                    "name": payment.get("name") or _("Payment"),
                    "total": payment.get("total") or 0.0,
                }
            )
        return {
            "order_count": details.get("nbr_orders") or 0,
            "total_sales": details.get("total_paid") or 0.0,
            "payments_per_method": payments_per_method,
        }

    def _avea_register_closure_report_body_html(self, session):
        self.ensure_one()
        company = session.company_id
        currency = session.currency_id
        till_name = session.config_id.name or _("POS")
        session_name = session.name or str(session.id)
        cashier = self.cashier_name or self.user_id.display_name or _("Unknown")
        report_date = self._avea_register_closure_report_date_label()
        sale_summary = self._avea_register_closure_report_sale_summary(session)
        accent = (company.avea_receipt_email_accent_color or "#c45c26").strip() or "#c45c26"

        def money(value):
            return formatLang(self.env, value or 0.0, currency_obj=currency)

        kind_labels = self._avea_payment_kind_label_map()
        payment_rows = ""
        for line in self.payment_line_ids.sorted("sequence"):
            label = kind_labels.get(line.payment_kind, line.payment_kind)
            payment_rows += (
                "<tr>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #eef0f3;'>{escape(label)}</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #eef0f3;text-align:right;'>{escape(money(line.expected))}</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #eef0f3;text-align:right;'>{escape(money(line.counted))}</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #eef0f3;text-align:right;'>{escape(money(line.difference))}</td>"
                "</tr>"
            )

        variance_block = ""
        if self.has_variance:
            variance_lines = [
                "<p style='margin:0 0 8px 0;font-weight:600;color:#9a3412;'>"
                + escape(_("Cash up discrepancy noticed"))
                + "</p>",
                "<ul style='margin:0;padding-left:18px;color:#7c2d12;'>",
            ]
            if currency.compare_amounts(self.difference, 0.0) != 0:
                variance_lines.append(
                    "<li>"
                    + escape(_("Cash variance: %s") % money(self.difference))
                    + "</li>"
                )
            if currency.compare_amounts(self.total_payments_difference, 0.0) != 0:
                variance_lines.append(
                    "<li>"
                    + escape(
                        _("Total payment variance: %s") % money(self.total_payments_difference)
                    )
                    + "</li>"
                )
            if self.variance_reason:
                variance_lines.append(
                    "<li>"
                    + escape(_("Reason: %s") % self.variance_reason)
                    + "</li>"
                )
            variance_lines.append("</ul>")
            variance_block = (
                "<div style='margin:18px 0;padding:14px 16px;background:#fff7ed;"
                "border:1px solid #fdba74;border-radius:8px;'>"
                + "".join(variance_lines)
                + "</div>"
            )
        else:
            variance_block = (
                "<div style='margin:18px 0;padding:14px 16px;background:#f0fdf4;"
                "border:1px solid #86efac;border-radius:8px;color:#166534;'>"
                + escape(_("Cash up completed with no discrepancies recorded."))
                + "</div>"
            )

        return f"""
<div style="font-family:Arial,Helvetica,sans-serif;color:#1f2937;font-size:14px;line-height:1.5;max-width:640px;">
  <div style="border-bottom:3px solid {escape(accent)};padding-bottom:12px;margin-bottom:18px;">
    <div style="font-size:12px;letter-spacing:0.04em;text-transform:uppercase;color:#6b7280;">
      {escape(company.name)}
    </div>
    <h1 style="margin:6px 0 0 0;font-size:22px;line-height:1.25;color:#111827;">
      {escape(_("Register Closure Report"))}
    </h1>
    <p style="margin:8px 0 0 0;color:#6b7280;">
      {escape(_("Session"))} <strong>{escape(session_name)}</strong>
      &nbsp;·&nbsp; {escape(report_date)}
    </p>
  </div>

  <p style="margin:0 0 16px 0;">
    {escape(_("The full Sales Details (Z) report for this session is attached as a PDF."))}
  </p>

  <table style="width:100%;border-collapse:collapse;margin:0 0 18px 0;">
    <tr>
      <td style="width:50%;padding:10px 12px;background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px 0 0 8px;">
        <div style="font-size:12px;color:#6b7280;">{escape(_("Till"))}</div>
        <div style="font-weight:600;">{escape(till_name)}</div>
      </td>
      <td style="width:50%;padding:10px 12px;background:#f8fafc;border:1px solid #e5e7eb;border-left:none;border-radius:0 8px 8px 0;">
        <div style="font-size:12px;color:#6b7280;">{escape(_("Cashier"))}</div>
        <div style="font-weight:600;">{escape(cashier)}</div>
      </td>
    </tr>
  </table>

  <h2 style="margin:0 0 10px 0;font-size:16px;color:#111827;">{escape(_("Session summary"))}</h2>
  <table style="width:100%;border-collapse:collapse;margin:0 0 18px 0;">
    <tr>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;">{escape(_("Transactions"))}</td>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;text-align:right;font-weight:600;">{self.transaction_count}</td>
    </tr>
    <tr>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;">{escape(_("Total sales"))}</td>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;text-align:right;font-weight:600;">{escape(money(sale_summary["total_sales"]))}</td>
    </tr>
    <tr>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;">{escape(_("Orders"))}</td>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;text-align:right;font-weight:600;">{sale_summary["order_count"]}</td>
    </tr>
    <tr>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;">{escape(_("Opening cash"))}</td>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;text-align:right;">{escape(money(self.opening_cash))}</td>
    </tr>
    <tr>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;">{escape(_("Expected cash in till"))}</td>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;text-align:right;">{escape(money(self.expected_cash))}</td>
    </tr>
    <tr>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;">{escape(_("Counted cash"))}</td>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;text-align:right;">{escape(money(self.counted_cash))}</td>
    </tr>
    <tr>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;">{escape(_("Cash to safe"))}</td>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;text-align:right;font-weight:600;">{escape(money(self.cash_to_bag))}</td>
    </tr>
    <tr>
      <td style="padding:8px 0;">{escape(_("Remaining in till"))}</td>
      <td style="padding:8px 0;text-align:right;">{escape(money(self.remaining_cash))}</td>
    </tr>
  </table>

  {variance_block}

  <h2 style="margin:0 0 10px 0;font-size:16px;color:#111827;">{escape(_("Payment reconciliation"))}</h2>
  <table style="width:100%;border-collapse:collapse;margin:0 0 18px 0;">
    <thead>
      <tr>
        <th style="padding:8px 10px;background:#f8fafc;border-bottom:1px solid #e5e7eb;text-align:left;font-size:12px;color:#6b7280;">{escape(_("Method"))}</th>
        <th style="padding:8px 10px;background:#f8fafc;border-bottom:1px solid #e5e7eb;text-align:right;font-size:12px;color:#6b7280;">{escape(_("Expected"))}</th>
        <th style="padding:8px 10px;background:#f8fafc;border-bottom:1px solid #e5e7eb;text-align:right;font-size:12px;color:#6b7280;">{escape(_("Counted"))}</th>
        <th style="padding:8px 10px;background:#f8fafc;border-bottom:1px solid #e5e7eb;text-align:right;font-size:12px;color:#6b7280;">{escape(_("Difference"))}</th>
      </tr>
    </thead>
    <tbody>
      {payment_rows}
    </tbody>
  </table>

  <p style="margin:0;color:#6b7280;font-size:12px;">
    {escape(_("This is an automated register closure notification from Avea POS."))}
  </p>
</div>
"""

    def _send_register_closure_report_email(self, session):
        self.ensure_one()
        session.ensure_one()
        company = session.company_id
        recipients = company._avea_register_closure_report_recipients()
        if not recipients:
            return False

        sender_email = company._avea_receipt_email_sender_email()
        if not sender_email:
            _logger.warning(
                "Skipping register closure report for session %s: no sender email configured.",
                session.id,
            )
            return False

        report = self.env.ref("point_of_sale.sale_details_report")
        report_data = {
            "date_start": False,
            "date_stop": False,
            "config_ids": session.config_id.ids,
            "session_ids": session.ids,
        }
        pdf_content, _report_format = report._render_qweb_pdf(
            "point_of_sale.sale_details_report",
            res_ids=session.ids,
            data=report_data,
        )
        if not pdf_content:
            _logger.warning(
                "Register closure report for session %s rendered empty PDF.",
                session.id,
            )
            return False

        session_name = session.name or str(session.id)
        attachment = self.env["ir.attachment"].create(
            {
                "name": _("Register closure - %s.pdf") % session_name,
                "type": "binary",
                "datas": base64.b64encode(pdf_content),
                "mimetype": "application/pdf",
                "res_model": "pos.session",
                "res_id": session.id,
            }
        )
        sender_name = company._avea_receipt_email_business_name()
        mail = self.env["mail.mail"].sudo().create(
            {
                "subject": self._avea_register_closure_report_subject(session),
                "body_html": self._avea_register_closure_report_body_html(session),
                "email_from": formataddr((sender_name, sender_email)),
                "email_to": ", ".join(recipients),
                "reply_to": company._avea_receipt_email_reply_to(),
                "attachment_ids": [(4, attachment.id)],
                "auto_delete": True,
            }
        )
        mail.send()
        _logger.info(
            "Register closure report emailed for session %s to %s",
            session.id,
            ", ".join(recipients),
        )
        return True

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
