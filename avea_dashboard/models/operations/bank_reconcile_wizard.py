# -*- coding: utf-8 -*-
import base64
import re
from datetime import datetime, timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .bank_reconcile_booking_rules import AveaBankReconcileBookingRules
from .bank_statement_parser import AveaBankStatementParser
from .merchant_payout_parser import AveaMerchantPayoutParser

# Exact amount is 50. Exact date adds 25 (auto). A shared description adds 20
# and is enough to auto-match. A nearby date alone stays a suggestion.
_MATCH_AUTO = 70.0
_MATCH_SUGGEST = 60.0
# Supplier EFTs often hit the bank before the receive is dated in Avea
# (Akwa 5 Oct vs a September statement). Keep those payments visible.
_BOOK_MATCH_GRACE_DAYS = 45
# Auto-suggest (never auto-accept) when the partner is identifiable.
_MATCH_NEAR_TOLERANCE = 0.05
# User-confirmed Match may write off up to a rand (Akwa 62c stays manual).
_MATCH_MANUAL_NEAR_TOLERANCE = 1.00
_NAME_STOPWORDS = {
    "internet",
    "pmt",
    "payment",
    "paid",
    "to",
    "from",
    "fnb",
    "app",
    "the",
    "and",
    "cc",
    "pty",
    "ltd",
    "limited",
    "magtape",
    "credit",
    "debit",
    "pos",
    "purchase",
    "account",
    "off-us",
    "payshap",
    "eft",
}

# Pets Empire FNB Gold Business Account — Avea live months from the
# May–August 2026 working papers. New recons start from the last closing.
_AVEA_BROUGHT_FORWARD_BANK_RECONS = (
    {
        "date_from": "2026-05-13",
        "date_to": "2026-05-31",
        "opening_balance": 4760.98,
        "closing_balance": 10315.77,
    },
    {
        "date_from": "2026-06-01",
        "date_to": "2026-06-30",
        "opening_balance": 10315.77,
        "closing_balance": 7907.38,
    },
    {
        "date_from": "2026-07-01",
        "date_to": "2026-07-31",
        "opening_balance": 7907.38,
        "closing_balance": 7584.04,
    },
    {
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
        "opening_balance": 7584.04,
        "closing_balance": 9873.06,
    },
)


class AveaBankReconciliation(models.Model):
    _name = "avea.bank.reconciliation"
    _description = "Bank Reconciliation"
    _order = "date_to desc, id desc"

    name = fields.Char(string="Reference", compute="_compute_name", store=True)
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("in_progress", "In progress"),
            ("done", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Owner",
        default=lambda self: self.env.user,
        required=True,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Bank account",
        required=True,
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]",
    )
    statement_file = fields.Binary(string="Statement file", attachment=True)
    statement_filename = fields.Char(string="Filename")
    source_format = fields.Char(string="Detected format", readonly=True)
    account_number = fields.Char(string="Bank account number", readonly=True)
    date_from = fields.Date(
        string="From",
        help="Taken from the statement. Change this only for a part-month, "
        "for example the week you went live on Avea.",
    )
    date_to = fields.Date(
        string="To",
        help="Taken from the statement. Change this only for a part-month.",
    )
    opening_balance = fields.Monetary(
        string="Opening balance (bank)",
        currency_field="currency_id",
    )
    closing_balance = fields.Monetary(
        string="Closing balance (bank)",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )
    line_ids = fields.One2many(
        "avea.bank.reconcile.line",
        "reconciliation_id",
        string="Bank transactions",
    )
    book_line_ids = fields.One2many(
        "avea.bank.reconcile.book.line",
        "reconciliation_id",
        string="On your books, not on statement",
    )
    merchant_file_ids = fields.One2many(
        "avea.bank.reconcile.merchant.file",
        "reconciliation_id",
        string="Card machine files",
    )
    merchant_payout_ids = fields.One2many(
        "avea.bank.reconcile.merchant.payout",
        "reconciliation_id",
        string="Card machine payouts",
    )
    till_card_sales = fields.Monetary(
        string="Till card sales",
        currency_field="currency_id",
        compute="_compute_card_machine_summary",
    )
    merchant_card_sales = fields.Monetary(
        string="Card sales on the machines",
        currency_field="currency_id",
        compute="_compute_card_machine_summary",
    )
    merchant_card_fees = fields.Monetary(
        string="Card fees",
        currency_field="currency_id",
        compute="_compute_card_machine_summary",
    )
    merchant_card_capital = fields.Monetary(
        string="Yoco capital repaid",
        currency_field="currency_id",
        compute="_compute_card_machine_summary",
    )
    card_banked = fields.Monetary(
        string="Card money in the bank",
        currency_field="currency_id",
        compute="_compute_card_machine_summary",
    )
    card_sales_gap = fields.Monetary(
        string="Till vs machines",
        currency_field="currency_id",
        compute="_compute_card_machine_summary",
        help="Till card sales minus the card-machine totals on the attached files. "
        "A large gap usually means a Yoco or Capitec file is for the wrong month.",
    )
    ready_card_batch_count = fields.Integer(compute="_compute_card_machine_summary")
    unmatched_card_batch_count = fields.Integer(compute="_compute_card_machine_summary")
    merchant_warning = fields.Char(compute="_compute_card_machine_summary")
    has_merchant_payouts = fields.Boolean(compute="_compute_card_machine_summary")
    matched_count = fields.Integer(compute="_compute_counts")
    possible_match_count = fields.Integer(compute="_compute_counts")
    unmatched_bank_count = fields.Integer(compute="_compute_counts")
    orphan_book_count = fields.Integer(compute="_compute_counts")
    import_count = fields.Integer(compute="_compute_counts")
    work_remaining_count = fields.Integer(compute="_compute_counts")
    matched_display = fields.Char(compute="_compute_counts")
    line_filter = fields.Selection(
        selection=[
            ("needs_work", "Still to do"),
            ("possible", "Possible matches"),
            ("cards", "Card deposits"),
            ("matched", "Done"),
            ("all", "All lines"),
        ],
        string="Show",
        default="needs_work",
    )
    display_line_ids = fields.Many2many(
        "avea.bank.reconcile.line",
        compute="_compute_display_line_ids",
        string="Bank transactions",
    )
    display_line_count = fields.Integer(compute="_compute_display_line_ids")
    has_display_lines = fields.Boolean(compute="_compute_display_line_ids")
    empty_filter_message = fields.Char(compute="_compute_display_line_ids")
    period_range_display = fields.Char(compute="_compute_guidance")
    next_step_kind = fields.Selection(
        selection=[
            ("upload", "Upload"),
            ("load", "Load"),
            ("settle_cards", "Settle cards"),
            ("accept_matches", "Accept matches"),
            ("work_lines", "Work remaining lines"),
            ("complete", "Complete"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        compute="_compute_guidance",
    )
    next_step_title = fields.Char(compute="_compute_guidance")
    next_step_message = fields.Char(compute="_compute_guidance")
    can_complete = fields.Boolean(compute="_compute_guidance")
    is_balanced = fields.Boolean(compute="_compute_guidance")
    difference_headline = fields.Char(compute="_compute_guidance")
    balances_from_file = fields.Boolean(
        string="Balances read from the statement",
        readonly=True,
    )
    prior_items_outstanding = fields.Boolean(
        string="Older entries are still missing from the bank",
        help="Leave this off when you are starting bank reconciliation and the "
        "opening balances already agree. Entries from before this statement "
        "then stay in the opening balance. Turn it on when a payment from before "
        "this statement has still not appeared on the bank.",
    )
    gl_balance = fields.Monetary(
        string="Balance in Avea",
        currency_field="currency_id",
        compute="_compute_reconciliation_balance",
    )
    outstanding_amount = fields.Monetary(
        string="Not on this statement yet",
        currency_field="currency_id",
        compute="_compute_reconciliation_balance",
        help="Payments already entered in Avea, up to the statement end, that this statement does not show.",
    )
    adjusted_book_balance = fields.Monetary(
        string="Avea after those items",
        currency_field="currency_id",
        compute="_compute_reconciliation_balance",
    )
    has_previous_statement = fields.Boolean(compute="_compute_reconciliation_balance")
    previous_closing_balance = fields.Monetary(
        string="Previous statement balance",
        currency_field="currency_id",
        compute="_compute_reconciliation_balance",
    )
    previous_statement_label = fields.Char(
        string="Last completed statement",
        compute="_compute_reconciliation_balance",
    )
    brought_forward = fields.Boolean(
        string="Brought forward from FNB books",
        help="Opening and closing were taken from the FNB statement without "
        "loading every line into this screen.",
    )
    statement_difference = fields.Monetary(
        string="Difference",
        currency_field="currency_id",
        compute="_compute_reconciliation_balance",
        help="Statement closing balance minus the books after outstanding items. "
        "Zero means the statement and the books agree.",
    )
    balance_warning = fields.Char(compute="_compute_reconciliation_balance")
    show_prior_outstanding_option = fields.Boolean(compute="_compute_reconciliation_balance")

    @api.depends(
        "journal_id",
        "date_from",
        "date_to",
        "statement_filename",
        "state",
    )
    def _compute_name(self):
        for rec in self:
            parts = [rec.journal_id.display_name or _("Bank")]
            if rec.date_from and rec.date_to:
                parts.append(
                    "%s – %s"
                    % (
                        fields.Date.to_string(rec.date_from),
                        fields.Date.to_string(rec.date_to),
                    )
                )
            elif rec.statement_filename:
                parts.append(rec.statement_filename)
            rec.name = " · ".join(parts)

    @api.depends("line_ids.match_state", "book_line_ids")
    def _compute_counts(self):
        for reconciliation in self:
            reconciliation.import_count = len(reconciliation.line_ids)
            reconciliation.matched_count = len(
                reconciliation.line_ids.filtered(
                    lambda line: line.match_state == "matched"
                )
            )
            reconciliation.possible_match_count = len(
                reconciliation.line_ids.filtered(
                    lambda line: line.match_state == "possible"
                )
            )
            reconciliation.unmatched_bank_count = len(
                reconciliation.line_ids.filtered(
                    lambda line: line.match_state == "unmatched"
                )
            )
            reconciliation.orphan_book_count = len(reconciliation.book_line_ids)
            reconciliation.work_remaining_count = (
                reconciliation.import_count - reconciliation.matched_count
            )
            if reconciliation.import_count:
                reconciliation.matched_display = _(
                    "%(matched)s of %(total)s",
                    matched=reconciliation.matched_count,
                    total=reconciliation.import_count,
                )
            else:
                reconciliation.matched_display = False

    @api.depends(
        "state",
        "line_ids",
        "line_ids.match_state",
        "line_ids.is_card_settlement",
        "line_filter",
        "import_count",
    )
    def _compute_display_line_ids(self):
        for reconciliation in self:
            lines = reconciliation._avea_filtered_lines()
            reconciliation.display_line_ids = lines
            reconciliation.display_line_count = len(lines)
            reconciliation.has_display_lines = bool(lines)
            reconciliation.empty_filter_message = (
                reconciliation._avea_empty_filter_message()
            )

    def _avea_filtered_lines(self):
        self.ensure_one()
        lines = self.line_ids
        filt = self.line_filter or "needs_work"
        if self.state == "done" or filt == "all":
            return lines
        if filt == "needs_work":
            return lines.filtered(lambda line: line.match_state != "matched")
        if filt == "possible":
            return lines.filtered(lambda line: line.match_state == "possible")
        if filt == "cards":
            return lines.filtered("is_card_settlement")
        if filt == "matched":
            return lines.filtered(lambda line: line.match_state == "matched")
        return lines

    def _avea_empty_filter_message(self):
        self.ensure_one()
        if self.line_ids and not self._avea_filtered_lines():
            filt = self.line_filter or "needs_work"
            if filt == "needs_work":
                return _(
                    "Nothing left on this statement. Switch to All lines if you "
                    "want to review what was matched."
                )
            if filt == "possible":
                return _("No possible matches right now.")
            if filt == "cards":
                return _("No Capitec or Yoco deposits on this statement.")
            if filt == "matched":
                return _("Nothing has been matched yet.")
        return False

    @api.depends(
        "state",
        "statement_file",
        "date_from",
        "date_to",
        "matched_count",
        "possible_match_count",
        "unmatched_bank_count",
        "work_remaining_count",
        "ready_card_batch_count",
        "statement_difference",
        "currency_id",
        "import_count",
        "line_ids.match_state",
        "line_ids.statement_line_id",
        "line_ids.amount",
        "opening_balance",
        "closing_balance",
        "balances_from_file",
        "journal_id",
        "account_number",
    )
    def _compute_guidance(self):
        for reconciliation in self:
            currency = reconciliation.currency_id or self.env.company.currency_id
            reconciliation.period_range_display = (
                reconciliation._avea_period_range_label()
            )
            reconciliation.is_balanced = currency.is_zero(
                reconciliation.statement_difference or 0.0
            )
            if reconciliation.is_balanced and reconciliation.state != "draft":
                reconciliation.difference_headline = _("Balanced")
            elif reconciliation.state == "draft":
                reconciliation.difference_headline = False
            else:
                reconciliation.difference_headline = currency.format(
                    reconciliation.statement_difference or 0.0
                )
            kind, title, message, can_complete = reconciliation._avea_next_step()
            reconciliation.next_step_kind = kind
            reconciliation.next_step_title = title
            reconciliation.next_step_message = message
            reconciliation.can_complete = can_complete

    def _avea_period_range_label(self):
        self.ensure_one()
        if not self.date_from or not self.date_to:
            return False
        return self.env["avea.reporting.workspace.mixin"]._reporting_format_day_range(
            self.date_from, self.date_to
        )

    def _avea_next_step(self):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        if self.state == "cancelled":
            return (
                "cancelled",
                _("Cancelled"),
                _("This reconciliation was cancelled. Start a new one from the list."),
                False,
            )
        if self.state == "done":
            return (
                "done",
                _("This statement is complete"),
                _("The bank and Avea agree for this period. You can still open it to review."),
                False,
            )
        if self.state == "draft":
            if not self.statement_file:
                prior = self._avea_previous_reconciliation()
                if prior:
                    return (
                        "upload",
                        _("Continue from the last statement"),
                        _(
                            "Last statement closed at %(amount)s on %(date)s. "
                            "Upload the next FNB statement. Opening should be that amount.",
                            amount=currency.format(prior.closing_balance or 0.0),
                            date=self.env["avea.reporting.workspace.mixin"]._reporting_format_day_range(
                                prior.date_to, prior.date_to
                            )
                            if prior.date_to
                            else _("the last recon"),
                        ),
                        False,
                    )
                return (
                    "upload",
                    _("Upload the bank statement"),
                    _(
                        "Attach the FNB Gold Business Account PDF. Then add the Yoco "
                        "payouts CSV and Capitec merchant statement for the same month."
                    ),
                    False,
                )
            return (
                "load",
                _("Load the statement"),
                _(
                    "Click Load & match. Avea reads the dates from the file and ticks "
                    "off anything it already knows."
                ),
                False,
            )
        if self.ready_card_batch_count:
            return (
                "settle_cards",
                _("Settle card deposits"),
                _(
                    "%(count)s Capitec or Yoco deposits match the machine files. "
                    "Settle them in one step — sales, fees, and Yoco capital are split "
                    "for you.",
                    count=self.ready_card_batch_count,
                ),
                False,
            )
        if self.possible_match_count:
            return (
                "accept_matches",
                _("Check possible matches"),
                _(
                    "Avea found %(count)s likely matches. Accept them if they are the "
                    "same payment, or Record / Match the rest.",
                    count=self.possible_match_count,
                ),
                False,
            )
        if self.unmatched_bank_count:
            return (
                "work_lines",
                _("Finish the remaining lines"),
                _(
                    "%(count)s bank lines still need you. Record an expense or income, "
                    "or Match an invoice, a bill, or a transfer.",
                    count=self.unmatched_bank_count,
                ),
                False,
            )
        blockers = self._avea_completion_blockers()
        if blockers:
            return ("work_lines", _("Not ready to complete yet"), blockers[0], False)
        return (
            "complete",
            _("Ready to complete"),
            _("The statement and Avea agree. Complete the reconciliation to lock it."),
            True,
        )

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("avea_skip_period_refresh"):
            return res
        if {"date_from", "date_to"} & set(vals):
            for reconciliation in self.filtered(
                lambda rec: rec.state == "in_progress" and rec.merchant_payout_ids
            ):
                reconciliation.with_context(
                    avea_skip_period_refresh=True
                )._avea_refresh_merchant_period()
        return res

    def _avea_refresh_merchant_period(self):
        """Re-flag machine payouts after the statement dates are changed."""
        self.ensure_one()
        date_from = self.date_from
        date_to = self.date_to
        for payout in self.merchant_payout_ids:
            on_statement = bool(
                date_from and date_to and date_from <= payout.payout_date <= date_to
            )
            if payout.on_this_statement != on_statement:
                payout.on_this_statement = on_statement
        self._avea_match_merchant_payouts()

    @api.depends(
        "journal_id",
        "company_id",
        "currency_id",
        "date_from",
        "date_to",
        "opening_balance",
        "closing_balance",
        "balances_from_file",
        "prior_items_outstanding",
        "account_number",
        "state",
        "line_ids.amount",
        "line_ids.bank_date",
        "line_ids.match_state",
        "line_ids.statement_line_id",
        "line_ids.statement_line_id.date",
        "line_ids.writeoff_amount",
        "book_line_ids.amount",
    )
    def _compute_reconciliation_balance(self):
        for reconciliation in self:
            currency = reconciliation.currency_id or self.env.company.currency_id
            gl_balance = reconciliation._avea_gl_bank_balance()
            outstanding_lines = reconciliation._avea_outstanding_statement_lines()
            outstanding_amount = sum(outstanding_lines.mapped("amount"))
            later_matched = reconciliation._avea_later_matched_statement_lines()
            later_amount = sum(later_matched.mapped("amount"))
            adjusted = gl_balance - outstanding_amount + later_amount
            closing = reconciliation.closing_balance or 0.0
            reconciliation.gl_balance = gl_balance
            reconciliation.outstanding_amount = outstanding_amount
            reconciliation.adjusted_book_balance = adjusted
            reconciliation.statement_difference = closing - adjusted
            prior = reconciliation._avea_previous_reconciliation()
            reconciliation.has_previous_statement = bool(prior)
            reconciliation.previous_closing_balance = prior.closing_balance if prior else 0.0
            reconciliation.previous_statement_label = (
                prior._avea_period_range_label() or prior.display_name if prior else False
            )
            warnings = []
            earlier_count = len(reconciliation._avea_opening_book_lines())
            if (
                earlier_count
                and not reconciliation._avea_has_prior_reconciliation()
                and not reconciliation.prior_items_outstanding
            ):
                warnings.append(
                    _(
                        "%(count)s book entries from before this statement are treated "
                        "as part of the opening balance. Turn on the older-entries option "
                        "if one of them has not hit the bank yet.",
                        count=earlier_count,
                    )
                )
            if prior and not reconciliation._avea_opening_continues_from(prior):
                warnings.append(
                    _(
                        "The opening balance does not match the previous statement "
                        "closing balance."
                    )
                )
            if (
                reconciliation.balances_from_file
                and reconciliation.line_ids
                and not currency.is_zero(
                    (reconciliation.opening_balance or 0.0)
                    + sum(reconciliation.line_ids.mapped("amount"))
                    - closing
                )
            ):
                warnings.append(
                    _(
                        "The statement lines do not add up from the opening balance "
                        "to the closing balance. Check the file or type the balances "
                        "from the statement."
                    )
                )
            account_warning = reconciliation._avea_account_number_warning()
            if account_warning:
                warnings.append(account_warning)
            overlap = reconciliation._avea_overlap_warning()
            if overlap:
                warnings.append(overlap)
            if not reconciliation.journal_id.default_account_id:
                warnings.append(
                    _(
                        "This bank journal has no ledger account, so the book balance "
                        "cannot be checked."
                    )
                )
            reconciliation.balance_warning = " ".join(warnings) if warnings else False
            reconciliation.show_prior_outstanding_option = (
                reconciliation.state == "in_progress"
                and not reconciliation._avea_has_prior_reconciliation()
            )

    def _avea_gl_bank_balance(self):
        """Posted balance of the bank ledger account at the statement end date."""
        self.ensure_one()
        account = self.journal_id.default_account_id
        if not account or not self.date_to:
            return 0.0
        lines = self.env["account.move.line"].sudo().search(
            [
                ("account_id", "=", account.id),
                ("parent_state", "=", "posted"),
                ("date", "<=", self.date_to),
                ("company_id", "=", self.company_id.id),
            ]
        )
        return sum(lines.mapped("balance"))

    def _avea_previous_reconciliation(self):
        self.ensure_one()
        if not self.journal_id:
            return self.browse()
        domain = [
            ("journal_id", "=", self.journal_id.id),
            ("company_id", "=", (self.company_id or self.env.company).id),
            ("state", "=", "done"),
            ("date_to", "!=", False),
        ]
        if self.ids:
            domain.append(("id", "!=", self.id))
        if self.date_from:
            # FNB Gold Business statements start on the last day of the
            # previous cycle, so the prior recon may end on this date_from.
            domain.append(("date_to", "<=", self.date_from))
        return self.search(domain, order="date_to desc, id desc", limit=1)

    def _avea_opening_continues_from(self, prior):
        """FNB may print the previous close as opening, then still list that last day."""
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        opening = self.opening_balance or 0.0
        previous_close = prior.closing_balance or 0.0
        if currency.is_zero(opening - previous_close):
            return True
        if not (prior.date_to and self.date_from and prior.date_to == self.date_from):
            return False
        shared = sum(
            self.line_ids.filtered(
                lambda line: line.bank_date == self.date_from
            ).mapped("amount")
        )
        return currency.is_zero(opening + shared - previous_close)

    def _avea_has_prior_reconciliation(self):
        self.ensure_one()
        return bool(self._avea_previous_reconciliation())

    def _avea_matched_statement_lines(self):
        self.ensure_one()
        return self.line_ids.filtered(
            lambda line: line.match_state == "matched" and line.statement_line_id
        ).mapped("statement_line_id")

    def _avea_opening_book_lines(self):
        """Uncleared book entries dated before this statement."""
        self.ensure_one()
        if not self.journal_id or not self.date_from:
            return self.env["account.bank.statement.line"]
        return self.env["account.bank.statement.line"].search(
            [
                ("journal_id", "=", self.journal_id.id),
                ("company_id", "=", self.company_id.id),
                ("avea_cleared", "=", False),
                ("date", "<", self.date_from),
            ]
        )

    def _avea_outstanding_domain(self):
        self.ensure_one()
        cleared_here = self._avea_matched_statement_lines()
        domain = [
            ("journal_id", "=", self.journal_id.id),
            ("company_id", "=", self.company_id.id),
            ("avea_cleared", "=", False),
            ("date", "<=", self.date_to),
            ("id", "not in", cleared_here.ids or [0]),
        ]
        if (
            self.date_from
            and not self.prior_items_outstanding
            and not self._avea_has_prior_reconciliation()
        ):
            domain.append(("date", ">=", self.date_from))
        return domain

    def _avea_outstanding_statement_lines(self):
        """Uncleared book entries at the statement date that this statement does not clear."""
        self.ensure_one()
        if not self.journal_id or not self.date_to:
            return self.env["account.bank.statement.line"]
        return self.env["account.bank.statement.line"].search(self._avea_outstanding_domain())

    def _avea_later_matched_statement_lines(self):
        """Payments dated after the statement that this recon has ticked off.

        The bank already shows them; the books only have them after date_to, so
        the GL at the statement date must be reduced by these amounts.
        """
        self.ensure_one()
        if not self.date_to:
            return self.env["account.bank.statement.line"]
        return self.line_ids.filtered(
            lambda line: line.match_state == "matched"
            and line.statement_line_id
            and line.statement_line_id.date
            and line.statement_line_id.date > self.date_to
        ).mapped("statement_line_id")

    def _avea_normalize_account_number(self, value):
        return re.sub(r"\D", "", value or "")

    def _avea_account_number_warning(self):
        self.ensure_one()
        bank = self.journal_id.bank_account_id
        journal_number = self._avea_normalize_account_number(
            bank.acc_number if bank else ""
        )
        statement_number = self._avea_normalize_account_number(self.account_number)
        if journal_number and statement_number and journal_number != statement_number:
            return _(
                "The statement account %(statement)s is not the account on %(journal)s.",
                statement=self.account_number,
                journal=self.journal_id.display_name,
            )
        return False

    def _avea_overlap_warning(self):
        self.ensure_one()
        if not self.journal_id or not self.date_from or not self.date_to:
            return False
        overlap = self.search(
            [
                ("id", "!=", self.id),
                ("journal_id", "=", self.journal_id.id),
                ("state", "=", "done"),
                ("date_from", "<", self.date_to),
                ("date_to", ">", self.date_from),
            ],
            limit=1,
        )
        if not overlap:
            return False
        return _(
            "A completed reconciliation already covers this period (%(name)s).",
            name=overlap.display_name,
        )

    def _avea_completion_blockers(self):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        blockers = []
        if not self.line_ids:
            blockers.append(_("Load a statement before completing."))
        if not self.journal_id.default_account_id:
            blockers.append(
                _("This bank journal has no ledger account, so the books cannot be checked.")
            )
        if self._avea_account_number_warning():
            blockers.append(self._avea_account_number_warning())
        if self._avea_overlap_warning():
            blockers.append(self._avea_overlap_warning())
        if not self.balances_from_file and currency.is_zero(
            self.opening_balance
        ) and currency.is_zero(self.closing_balance) and self.line_ids.filtered(
            lambda line: not currency.is_zero(line.amount)
        ):
            blockers.append(
                _(
                    "Type the opening and closing balances from the statement. "
                    "They were not on the file."
                )
            )
        if self.balances_from_file or not (
            currency.is_zero(self.opening_balance) and currency.is_zero(self.closing_balance)
        ):
            expected = (self.opening_balance or 0.0) + sum(self.line_ids.mapped("amount"))
            if not currency.is_zero(expected - (self.closing_balance or 0.0)):
                blockers.append(
                    _(
                        "Opening balance plus the statement lines does not equal "
                        "the closing balance."
                    )
                )
        pending = self.line_ids.filtered(lambda line: line.match_state != "matched")
        if pending:
            blockers.append(
                _(
                    "%(count)s statement line(s) are not matched. Match them, "
                    "accept a suggestion, or book them. Skipped lines and suspense "
                    "imports cannot be completed.",
                    count=len(pending),
                )
            )
        seen = set()
        for line in self.line_ids.filtered("statement_line_id"):
            if line.statement_line_id.id in seen:
                blockers.append(
                    _("The same book entry is linked to more than one statement line.")
                )
                break
            seen.add(line.statement_line_id.id)
            book_amount = line.statement_line_id.amount + (line.writeoff_amount or 0.0)
            if not currency.is_zero(book_amount - line.amount):
                blockers.append(
                    _(
                        "%(description)s does not match the book amount.",
                        description=line.description or line.reference or _("A statement line"),
                    )
                )
                break
            if line.statement_line_id.avea_cleared and (
                line.statement_line_id.avea_cleared_reconciliation_id != self
            ):
                blockers.append(
                    _(
                        "%(description)s is already cleared on another reconciliation.",
                        description=line.description or line.reference or _("A statement line"),
                    )
                )
                break
        if self.journal_id.default_account_id and not currency.is_zero(
            self.statement_difference
        ):
            blockers.append(
                _(
                    "Difference is %(amount)s. The statement closing balance must "
                    "equal the books after outstanding items.",
                    amount=self.statement_difference,
                )
            )
        return blockers

    @api.model
    def action_open_list(self):
        self._avea_ensure_brought_forward_recons()
        list_view_id = self.env.ref(
            "avea_till.view_avea_bank_reconciliation_list"
        ).id
        return {
            "type": "ir.actions.act_window",
            "name": _("Bank reconciliations"),
            "res_model": self._name,
            "view_mode": "list,form",
            "views": [(list_view_id, "list"), (False, "form")],
            "view_id": list_view_id,
            "target": "current",
        }

    @api.model
    def action_new_reconciliation(self):
        reconciliation = self.browse(self.action_create_draft())
        return reconciliation._avea_action_form(_("New bank reconciliation"))

    @api.model
    def action_create_draft(self):
        """Public RPC entry: start the next recon from the last completed one."""
        self._avea_ensure_brought_forward_recons()
        journal = self._avea_default_bank_journal()
        empty = self.search(
            [
                ("company_id", "=", self.env.company.id),
                ("journal_id", "=", journal.id if journal else False),
                ("state", "=", "draft"),
                ("line_ids", "=", False),
            ],
            order="id desc",
            limit=1,
        )
        reconciliation = empty or self.create(
            {
                "journal_id": journal.id if journal else False,
                "state": "draft",
            }
        )
        reconciliation._avea_apply_last_completed_defaults()
        return reconciliation.id

    def _avea_apply_last_completed_defaults(self):
        """Copy the last completed closing balance onto a new draft."""
        for rec in self:
            if rec.state != "draft" or rec.line_ids:
                continue
            last = rec._avea_previous_reconciliation()
            if not last:
                continue
            vals = {}
            currency = rec.currency_id or self.env.company.currency_id
            if currency.is_zero(rec.opening_balance or 0.0):
                vals["opening_balance"] = last.closing_balance
            if not rec.date_from and last.date_to:
                vals["date_from"] = last.date_to + timedelta(days=1)
            if vals:
                rec.write(vals)

    @api.onchange("journal_id")
    def _onchange_journal_carry_last_statement(self):
        if self.state != "draft" or self.line_ids:
            return
        last = self._avea_previous_reconciliation()
        if not last:
            return
        self.opening_balance = last.closing_balance
        if last.date_to:
            self.date_from = last.date_to + timedelta(days=1)

    @api.model
    def _avea_company_uses_fnb_brought_forward(self):
        return "pets empire" in (self.env.company.name or "").lower()

    @api.model
    def _avea_ensure_brought_forward_recons(self, force=False):
        """Create the May–August FNB recons so they appear in the list."""
        if not force and not self._avea_company_uses_fnb_brought_forward():
            return self.browse()
        journal = self._avea_default_bank_journal()
        if not journal:
            return self.browse()
        created = self.browse()
        for pack in _AVEA_BROUGHT_FORWARD_BANK_RECONS:
            existing = self.search(
                [
                    ("company_id", "=", self.env.company.id),
                    ("journal_id", "=", journal.id),
                    ("date_from", "=", pack["date_from"]),
                    ("date_to", "=", pack["date_to"]),
                    ("state", "!=", "cancelled"),
                ],
                limit=1,
            )
            if existing and existing.state == "done":
                continue
            if existing and existing.line_ids:
                continue
            if existing:
                existing.state = "cancelled"
            created |= self.create(
                {
                    "journal_id": journal.id,
                    "date_from": pack["date_from"],
                    "date_to": pack["date_to"],
                    "opening_balance": pack["opening_balance"],
                    "closing_balance": pack["closing_balance"],
                    "balances_from_file": True,
                    "brought_forward": True,
                    "state": "done",
                }
            )
        return created

    def _avea_default_bank_journal(self):
        company = self.env.company

        def _not_store_credit(journal):
            return "store credit" not in (journal.name or "").lower()

        configured = company._avea_expense_journals().filtered(
            lambda journal: journal.type == "bank" and _not_store_credit(journal)
        )
        if configured:
            return configured[:1]
        return self.env["account.journal"].search(
            [
                ("type", "=", "bank"),
                ("company_id", "=", company.id),
                ("name", "not ilike", "Store Credit"),
            ],
            limit=1,
        ) or self.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", company.id)],
            limit=1,
        )

    def _avea_action_form(self, title=None):
        self.ensure_one()
        if not self.line_filter:
            self.line_filter = "needs_work"
        form_view_id = self.env.ref(
            "avea_till.view_avea_bank_reconciliation_form"
        ).id
        return {
            "type": "ir.actions.act_window",
            "name": title or self.display_name,
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(form_view_id, "form")],
            "view_id": form_view_id,
            "target": "current",
            "context": {"avea_bank_reconcile_labels": True},
        }

    def action_parse_statement(self):
        self.ensure_one()
        if not self.statement_file:
            raise UserError(_("Upload a bank statement file (FNB PDF, CSV, or OFX)."))
        if not self.journal_id:
            raise UserError(_("Choose the bank account to reconcile."))
        raw = base64.b64decode(self.statement_file)
        if not raw:
            raise UserError(_("The uploaded file is empty."))
        filename = self.statement_filename or "statement.csv"
        kind = AveaMerchantPayoutParser.detect(filename, raw)
        if kind in ("yoco", "capitec"):
            raise UserError(
                _(
                    "This is a %(kind)s card-machine file, not the FNB bank statement. "
                    "Attach the Gold Business Account PDF as the statement, and put "
                    "Yoco CSVs and Capitec merchant statements under Card machine files.",
                    kind="Yoco" if kind == "yoco" else "Capitec",
                )
            )
        parsed = AveaBankStatementParser.parse(filename, raw)
        opening = parsed.get("opening_balance")
        closing = parsed.get("closing_balance")
        balances_from_file = opening is not None and closing is not None
        self.line_ids = [Command.clear()]
        self.book_line_ids = [Command.clear()]
        line_vals = []
        for sequence, tx in enumerate(parsed["transactions"], start=1):
            line_vals.append(
                Command.create(
                    {
                        "sequence": sequence * 10,
                        "bank_date": tx["date"],
                        "description": tx["description"],
                        "reference": tx["reference"],
                        "amount": tx["amount"],
                        "balance_after": tx.get("balance"),
                        "import_action": (
                            "expense"
                            if tx["amount"] < 0
                            else "income"
                            if tx["amount"] > 0
                            else "skip"
                        ),
                    }
                )
            )
        self.write(
            {
                "source_format": parsed.get("source"),
                "account_number": parsed.get("account_number"),
                "date_from": parsed.get("date_from"),
                "date_to": parsed.get("date_to"),
                "opening_balance": opening or 0.0,
                "closing_balance": closing or 0.0,
                "balances_from_file": balances_from_file,
                "line_ids": line_vals,
                "state": "in_progress",
            }
        )
        self._avea_match_lines()
        self._avea_load_merchant_files()
        self._avea_apply_booking_suggestions()
        self._avea_find_orphan_book_lines()
        return self._avea_action_form()

    def action_refresh_matches(self):
        self.ensure_one()
        self._avea_refresh_after_merchant_files()
        self._avea_find_orphan_book_lines()
        return self._avea_action_form()

    def _avea_refresh_after_merchant_files(self):
        for reconciliation in self:
            if reconciliation.state != "in_progress":
                continue
            reconciliation._avea_load_merchant_files()
            reconciliation._avea_match_lines()
            reconciliation._avea_apply_booking_suggestions()

    def _avea_load_merchant_files(self):
        self.ensure_one()
        self.merchant_payout_ids.unlink()
        for attachment in self.merchant_file_ids:
            if not attachment.datas:
                continue
            raw = base64.b64decode(attachment.datas)
            if not raw:
                continue
            parsed = AveaMerchantPayoutParser.parse(
                attachment.filename or "merchant.csv",
                raw,
            )
            overlapping = 0
            date_from = self.date_from
            date_to = self.date_to
            rows = []
            for payout in parsed["payouts"]:
                on_statement = bool(
                    date_from
                    and date_to
                    and date_from <= payout["payout_date"] <= date_to
                )
                if on_statement:
                    overlapping += 1
                rows.append(
                    {
                        "reconciliation_id": self.id,
                        "file_id": attachment.id,
                        "provider": payout["provider"],
                        "payout_date": payout["payout_date"],
                        "trading_date": payout.get("trading_date") or False,
                        "net_amount": payout["net_amount"],
                        "gross_amount": payout["gross_amount"],
                        "fee_amount": payout["fee_amount"],
                        "capital_amount": payout["capital_amount"],
                        "reference": payout.get("reference") or "",
                        "on_this_statement": on_statement,
                    }
                )
            warning = False
            if parsed["payouts"] and not overlapping:
                warning = _(
                    "This %(provider)s file is %(date_from)s to %(date_to)s, "
                    "which has no payouts on this bank statement. "
                    "Upload the file for the same month as the FNB statement.",
                    provider=parsed["provider"].title(),
                    date_from=parsed["date_from"],
                    date_to=parsed["date_to"],
                )
            attachment.with_context(avea_skip_merchant_refresh=True).write(
                {
                    "provider": parsed["provider"],
                    "date_from": parsed.get("date_from"),
                    "date_to": parsed.get("date_to"),
                    "period_warning": warning,
                }
            )
            if rows:
                self.env["avea.bank.reconcile.merchant.payout"].create(rows)
        self._avea_match_merchant_payouts()

    def _avea_match_merchant_payouts(self):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        open_payouts = self.merchant_payout_ids.filtered("on_this_statement")
        used = set()
        for line in self.line_ids:
            if line.match_state in ("matched", "imported"):
                continue
            if not line.is_card_settlement:
                if line.merchant_payout_id:
                    line.merchant_payout_id = False
                continue
            provider = line._avea_card_provider()
            candidates = open_payouts.filtered(
                lambda payout, provider=provider: payout.provider == provider
                and payout.id not in used
                and currency.compare_amounts(payout.net_amount, line.amount) == 0
            )
            chosen = self.env["avea.bank.reconcile.merchant.payout"]
            if len(candidates) == 1:
                chosen = candidates
            elif len(candidates) > 1:
                dated = candidates.filtered(
                    lambda payout: payout.payout_date == line.bank_date
                    or payout.trading_date == line.bank_date
                )
                if len(dated) == 1:
                    chosen = dated
            if chosen:
                used.add(chosen.id)
                line.merchant_payout_id = chosen.id
            elif line.merchant_payout_id:
                line.merchant_payout_id = False

    def action_settle_card_batches(self):
        self.ensure_one()
        if self.state != "in_progress":
            raise UserError(_("Upload and review the statement first."))
        lines = self.line_ids.filtered(
            lambda line: line.is_card_settlement
            and line.merchant_payout_id
            and line.match_state not in ("matched", "imported")
        )
        if not lines:
            raise UserError(
                _(
                    "No card batches are ready. Attach the Yoco payouts CSV and the "
                    "Capitec merchant statement for this month, then Refresh matches."
                )
            )
        Apply = self.env["avea.bank.reconcile.apply"]
        fee_account = Apply._avea_fee_account(self.company_id)
        capital_account = Apply._avea_capital_account(self.company_id)
        settled = 0
        for line in lines:
            payout = line.merchant_payout_id
            values = {
                "reconcile_line_id": line.id,
                "mode": "settlement",
                "settlement_gross": payout.gross_amount,
                "settlement_capital": payout.capital_amount,
            }
            if fee_account:
                values["fee_account_id"] = fee_account.id
            if capital_account and payout.capital_amount:
                values["capital_account_id"] = capital_account.id
            Apply.create(values).action_apply()
            settled += 1
        self._avea_find_orphan_book_lines()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Card batches settled"),
                "message": _(
                    "%(count)s card deposits booked from the machine files. "
                    "Sales, fees, and Yoco capital are split automatically.",
                    count=settled,
                ),
                "type": "success",
                "next": self._avea_action_form(),
            },
        }

    @api.depends(
        "journal_id",
        "company_id",
        "date_from",
        "date_to",
        "line_ids.amount",
        "line_ids.is_card_settlement",
        "line_ids.match_state",
        "line_ids.merchant_payout_id",
        "merchant_payout_ids.net_amount",
        "merchant_payout_ids.gross_amount",
        "merchant_payout_ids.fee_amount",
        "merchant_payout_ids.capital_amount",
        "merchant_payout_ids.on_this_statement",
        "merchant_file_ids.period_warning",
        "state",
    )
    def _compute_card_machine_summary(self):
        for reconciliation in self:
            payouts = reconciliation.merchant_payout_ids.filtered("on_this_statement")
            card_lines = reconciliation.line_ids.filtered("is_card_settlement")
            ready = card_lines.filtered(
                lambda line: line.merchant_payout_id
                and line.match_state not in ("matched", "imported")
            )
            unmatched = card_lines.filtered(
                lambda line: line.match_state not in ("matched", "imported")
                and not line.merchant_payout_id
            )
            till = reconciliation._avea_till_card_sales()
            merchant_sales = sum(payouts.mapped("gross_amount"))
            reconciliation.till_card_sales = till
            reconciliation.merchant_card_sales = merchant_sales
            reconciliation.merchant_card_fees = sum(payouts.mapped("fee_amount"))
            reconciliation.merchant_card_capital = sum(payouts.mapped("capital_amount"))
            reconciliation.card_banked = sum(card_lines.mapped("amount"))
            reconciliation.card_sales_gap = till - merchant_sales
            reconciliation.ready_card_batch_count = len(ready)
            reconciliation.unmatched_card_batch_count = len(unmatched)
            reconciliation.has_merchant_payouts = bool(reconciliation.merchant_payout_ids)
            warnings = [file.period_warning for file in reconciliation.merchant_file_ids if file.period_warning]
            if unmatched and not reconciliation.merchant_file_ids:
                warnings.append(
                    _(
                        "Attach the Yoco payouts CSV and the Capitec merchant statement "
                        "for this month. They tell Avea the card sales, fees, and Yoco "
                        "capital behind each deposit."
                    )
                )
            elif unmatched:
                warnings.append(
                    _(
                        "%(count)s card deposits on the bank have no matching machine "
                        "payout. That is usually a missing file or the wrong month.",
                        count=len(unmatched),
                    )
                )
            reconciliation.merchant_warning = " ".join(warnings) if warnings else False

    def _avea_till_card_sales(self):
        self.ensure_one()
        if not self.date_from or not self.date_to:
            return 0.0
        methods = self.env["pos.payment.method"].sudo().search([])
        cards = methods.filtered(
            lambda method: "card" in (method.name or "").lower()
            or (
                hasattr(method, "_avea_tender_kind")
                and method._avea_tender_kind() == "card"
            )
        )
        if not cards:
            return 0.0
        start = datetime.combine(self.date_from, datetime.min.time())
        end = datetime.combine(self.date_to, datetime.min.time()) + timedelta(days=1)
        payments = self.env["pos.payment"].sudo().search(
            [
                ("payment_method_id", "in", cards.ids),
                ("payment_date", ">=", start),
                ("payment_date", "<", end),
            ]
        )
        return sum(payments.mapped("amount"))

    def _avea_apply_booking_suggestions(self):
        self.ensure_one()
        for line in self.line_ids:
            line._avea_apply_booking_suggestion()

    def _avea_uncleared_book_lines(self):
        """Book entries still available to tick off, including later-dated payments."""
        self.ensure_one()
        domain = [
            ("journal_id", "=", self.journal_id.id),
            ("company_id", "=", self.company_id.id),
            ("avea_cleared", "=", False),
        ]
        if self.date_to:
            domain.append(
                ("date", "<=", self.date_to + timedelta(days=_BOOK_MATCH_GRACE_DAYS))
            )
        return self.env["account.bank.statement.line"].search(
            domain, order="date desc, id desc"
        )

    def _avea_match_lines(self):
        self.ensure_one()
        self = self.with_context(
            avea_recon_name_blob_cache={},
            avea_recon_recall_cache={},
        )
        pool = self._avea_uncleared_book_lines()
        pool.mapped("partner_id")
        pool.mapped("move_id")
        locked = self.line_ids.filtered(
            lambda line: line.match_locked and line.statement_line_id
        )
        used = set(locked.mapped("statement_line_id").ids)
        open_lines = self.line_ids.filtered(lambda line: not line.match_locked)
        for line in open_lines:
            line.write(
                {
                    "match_state": "unmatched",
                    "statement_line_id": False,
                    "match_confidence": 0.0,
                    "match_hint": False,
                    "candidate_statement_line_ids": [Command.clear()],
                }
            )

        def _exact(line, candidate):
            return line._avea_amounts_equal(candidate.amount)

        assignments = {}
        amount_groups = {}
        currency = self.currency_id or self.env.company.currency_id
        for line in open_lines:
            amount_groups.setdefault(currency.round(line.amount), []).append(line)
        for lines in amount_groups.values():
            if len(lines) != 1:
                continue
            line = lines[0]
            exact = [candidate for candidate in pool if _exact(line, candidate) and candidate.id not in used]
            if len(exact) != 1:
                continue
            candidate = exact[0]
            _score, hint = line._avea_score_candidate(candidate)
            assignments[line.id] = (max(_score, _MATCH_AUTO), candidate, hint or _("only exact amount"))
            used.add(candidate.id)

        proposals = []
        for line in open_lines:
            if line.id in assignments:
                continue
            for candidate in pool:
                if candidate.id in used:
                    continue
                score, hint = line._avea_score_candidate(candidate)
                if score >= _MATCH_SUGGEST:
                    proposals.append((score, line.id, candidate.id, hint))
        proposals.sort(key=lambda row: (-row[0], row[1], row[2]))
        for score, line_id, candidate_id, hint in proposals:
            if line_id in assignments or candidate_id in used:
                continue
            assignments[line_id] = (score, pool.browse(candidate_id), hint)
            used.add(candidate_id)

        for line in open_lines:
            scored = []
            for candidate in pool:
                score, hint = line._avea_score_candidate(candidate)
                if score >= _MATCH_SUGGEST:
                    scored.append((score, candidate, hint))
            scored.sort(key=lambda row: row[0], reverse=True)
            top = scored[:20]
            vals = {}
            if top:
                vals["candidate_statement_line_ids"] = [
                    Command.set([row[1].id for row in top])
                ]
            assigned = assignments.get(line.id)
            if assigned:
                score, candidate, hint = assigned
                vals.update(
                    {
                        "statement_line_id": candidate.id,
                        "match_confidence": score,
                        "match_hint": hint or False,
                        "match_state": "matched" if score >= _MATCH_AUTO else "possible",
                    }
                )
                line._avea_remember_matched_payee(candidate)
            elif not vals.get("candidate_statement_line_ids"):
                counterpart = line._avea_supplier_payment_counterpart(pool, used)
                if counterpart:
                    vals["candidate_statement_line_ids"] = [
                        Command.set(counterpart.ids)
                    ]
            if vals:
                line.write(vals)

    def _avea_find_orphan_book_lines(self):
        self.ensure_one()
        BookLine = self.env["avea.bank.reconcile.book.line"]
        self.book_line_ids.unlink()
        rows = []
        for st_line in self._avea_outstanding_statement_lines():
            rows.append(
                {
                    "reconciliation_id": self.id,
                    "statement_line_id": st_line.id,
                    "book_date": st_line.date or st_line.move_id.date,
                    "label": st_line.payment_ref or st_line.move_id.ref or st_line.move_id.name,
                    "amount": st_line.amount,
                }
            )
        if rows:
            BookLine.create(rows)

    def action_accept_possible_matches(self):
        self.ensure_one()
        if self.state != "in_progress":
            raise UserError(_("Upload and review the statement first."))
        possible = self.line_ids.filtered(
            lambda line: line.match_state == "possible" and line.statement_line_id
        )
        if not possible:
            raise UserError(_("There are no possible matches to accept."))
        for line in possible:
            line._avea_accept_match()
        self._avea_find_orphan_book_lines()
        return self._avea_action_form()

    def action_apply_reconciliation(self):
        self.ensure_one()
        if self.state != "in_progress":
            raise UserError(_("Upload and review the statement before completing."))
        self._avea_find_orphan_book_lines()
        blockers = self._avea_completion_blockers()
        if blockers:
            raise UserError("\n".join(blockers))
        matched = 0
        for line in self.line_ids:
            line._avea_confirm_match()
            matched += 1
        if (
            not self.prior_items_outstanding
            and not self._avea_has_prior_reconciliation()
        ):
            opening_lines = self._avea_opening_book_lines()
            if opening_lines:
                opening_lines.sudo().write(
                    {
                        "avea_cleared": True,
                        "avea_cleared_reconciliation_id": self.id,
                    }
                )
        self._avea_find_orphan_book_lines()
        self.state = "done"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Bank reconciliation completed"),
                "message": _(
                    "%(matched)s statement lines cleared. Difference is zero.",
                    matched=matched,
                ),
                "type": "success",
                "next": self.env["avea.bank.reconciliation"].action_open_list(),
            },
        }

    def action_cancel_reconciliation(self):
        self.write({"state": "cancelled"})
        return self.env["avea.bank.reconciliation"].action_open_list()


class AveaBankReconcileWizard(models.TransientModel):
    """Legacy entry point — opens the persisted reconciliation list."""

    _name = "avea.bank.reconcile.wizard"
    _description = "Bank Reconciliation (launcher)"

    @api.model
    def action_open_wizard(self):
        return self.env["avea.bank.reconciliation"].action_open_list()


class AveaBankReconcileLine(models.Model):
    _name = "avea.bank.reconcile.line"
    _description = "Bank reconciliation import line"
    _order = "match_work_rank, bank_date, sequence, id"

    reconciliation_id = fields.Many2one(
        "avea.bank.reconciliation",
        required=True,
        ondelete="cascade",
    )
    journal_id = fields.Many2one(
        related="reconciliation_id.journal_id",
        string="Bank journal",
    )
    sequence = fields.Integer(default=10)
    bank_date = fields.Date(string="Date", required=True)
    description = fields.Char()
    reference = fields.Char()
    amount = fields.Monetary(currency_field="currency_id", required=True)
    amount_spent_display = fields.Char(
        string="Spent",
        compute="_compute_money_columns",
    )
    amount_received_display = fields.Char(
        string="Received",
        compute="_compute_money_columns",
    )
    is_card_settlement = fields.Boolean(compute="_compute_is_card_settlement")
    merchant_payout_id = fields.Many2one(
        "avea.bank.reconcile.merchant.payout",
        string="Card machine payout",
        ondelete="set null",
    )
    balance_after = fields.Monetary(string="Bank balance", currency_field="currency_id")
    currency_id = fields.Many2one(related="reconciliation_id.currency_id")
    match_state = fields.Selection(
        selection=[
            ("unmatched", "Unmatched"),
            ("possible", "Possible match"),
            ("matched", "Matched"),
            ("imported", "Imported"),
            ("skipped", "Skipped"),
        ],
        default="unmatched",
        required=True,
    )
    match_work_rank = fields.Integer(
        compute="_compute_match_work_rank",
        store=True,
        index=True,
    )
    work_hint = fields.Char(
        string="What to do",
        compute="_compute_work_hint",
    )
    import_action = fields.Selection(
        selection=[
            ("expense", "Record expense"),
            ("income", "Record income"),
            ("create", "Quick import (suspense)"),
            ("skip", "Skip"),
        ],
        string="Record as",
        default="expense",
        required=True,
    )
    candidate_statement_line_ids = fields.Many2many(
        "account.bank.statement.line",
        "avea_bank_reconcile_line_candidate_rel",
        "reconcile_line_id",
        "statement_line_id",
        string="Candidate book entries",
        context={"avea_bank_reconcile_labels": True},
    )
    statement_line_id = fields.Many2one(
        "account.bank.statement.line",
        string="Already in Avea",
        domain="[('journal_id', '=', journal_id), ('avea_cleared', '=', False)]",
        context={"avea_bank_reconcile_labels": True},
        ondelete="set null",
    )
    book_match_summary = fields.Char(
        string="Linked entry",
        compute="_compute_book_match_summary",
    )
    match_confidence = fields.Float(string="Match %", readonly=True)
    match_hint = fields.Char(string="Match reason", readonly=True)
    match_locked = fields.Boolean(
        string="Match kept",
        default=False,
        help="Set when you choose the book entry yourself, so a refresh does not replace it.",
    )
    writeoff_move_id = fields.Many2one(
        "account.move",
        string="Rounding write-off",
        copy=False,
        ondelete="set null",
    )
    writeoff_amount = fields.Monetary(
        string="Rounding",
        currency_field="currency_id",
        copy=False,
        help="Bank amount minus the book payment. Posted as a rounding entry on Accept.",
    )
    has_supplier_payment_counterpart = fields.Boolean(
        compute="_compute_work_hint",
    )
    booking_suggestion = fields.Char(
        string="Suggested booking",
        compute="_compute_booking_suggestion",
        help="Based on the bank description. Record creates the expense or income. "
        "Nothing is posted until you confirm.",
    )
    suggested_expense_account_id = fields.Many2one(
        "account.account",
        string="Suggested expense account",
        compute="_compute_booking_suggestion",
    )
    suggested_income_account_id = fields.Many2one(
        "account.account",
        string="Suggested income account",
        compute="_compute_booking_suggestion",
    )
    company_id = fields.Many2one(related="reconciliation_id.company_id")

    @api.depends("match_state")
    def _compute_match_work_rank(self):
        rank = {
            "unmatched": 0,
            "possible": 1,
            "imported": 2,
            "skipped": 3,
            "matched": 4,
        }
        for line in self:
            line.match_work_rank = rank.get(line.match_state, 0)

    @api.depends(
        "match_state",
        "is_card_settlement",
        "booking_suggestion",
        "book_match_summary",
        "merchant_payout_id",
        "description",
        "reference",
        "amount",
        "statement_line_id",
        "candidate_statement_line_ids",
        "reconciliation_id.date_to",
        "reconciliation_id.journal_id",
    )
    def _compute_work_hint(self):
        self = self.with_context(
            avea_recon_name_blob_cache={},
            avea_recon_recall_cache={},
        )
        pool_by_recon = {}
        used_by_recon = {}
        for line in self:
            done = line.match_state in ("matched", "imported", "skipped")
            counterpart = False
            if not done and line.match_state == "unmatched" and line.reconciliation_id:
                rec = line.reconciliation_id
                if rec.id not in pool_by_recon:
                    pool_by_recon[rec.id] = rec._avea_uncleared_book_lines()
                    used_by_recon[rec.id] = set(
                        rec.line_ids.filtered("statement_line_id").mapped(
                            "statement_line_id"
                        ).ids
                    )
                counterpart = line._avea_supplier_payment_counterpart(
                    pool_by_recon[rec.id], used_by_recon[rec.id]
                )
            line.has_supplier_payment_counterpart = bool(counterpart)
            if line.match_state == "matched":
                line.work_hint = line.book_match_summary or _("Matched")
            elif line.match_state == "possible":
                line.work_hint = line.book_match_summary or _(
                    "Possible match — Accept if this is the same payment"
                )
            elif line.is_card_settlement and line.merchant_payout_id:
                line.work_hint = _("Card deposit — Settle from the machine file")
            elif line.is_card_settlement:
                line.work_hint = _(
                    "Card deposit — attach the Yoco or Capitec file, then Settle"
                )
            elif counterpart:
                line.work_hint = _("Match to the supplier payment/invoice")
            elif line.booking_suggestion:
                line.work_hint = line.booking_suggestion
            else:
                line.work_hint = _(
                    "Record the expense or income, or Match an existing entry"
                )

    @api.depends(
        "statement_line_id",
        "match_confidence",
        "match_hint",
        "match_state",
        "booking_suggestion",
    )
    def _compute_book_match_summary(self):
        for line in self:
            if line.statement_line_id:
                label = line.statement_line_id.avea_reconcile_display_name()
                if line.match_state == "possible" and line.match_confidence:
                    line.book_match_summary = _(
                        "Possible match (%(score).0f%%): %(label)s",
                        score=line.match_confidence,
                        label=label,
                    )
                else:
                    line.book_match_summary = label
            elif line.match_hint and line.match_confidence >= _MATCH_SUGGEST:
                line.book_match_summary = _(
                    "Suggested (%(score).0f%%): %(hint)s",
                    score=line.match_confidence,
                    hint=line.match_hint,
                )
            else:
                line.book_match_summary = False

    @api.depends("amount", "currency_id")
    def _compute_money_columns(self):
        for line in self:
            currency = line.currency_id or line.env.company.currency_id
            if currency.compare_amounts(line.amount or 0.0, 0.0) < 0:
                line.amount_spent_display = currency.format(abs(line.amount))
                line.amount_received_display = ""
            elif currency.compare_amounts(line.amount or 0.0, 0.0) > 0:
                line.amount_spent_display = ""
                line.amount_received_display = currency.format(line.amount)
            else:
                line.amount_spent_display = ""
                line.amount_received_display = ""

    @api.depends("description", "reference")
    def _compute_is_card_settlement(self):
        for line in self:
            blob = " ".join(filter(None, [line.description or "", line.reference or ""])).lower()
            line.is_card_settlement = "card settlement" in blob

    def _avea_card_provider(self):
        self.ensure_one()
        blob = " ".join(filter(None, [self.description or "", self.reference or ""])).lower()
        if "capitec" in blob:
            return "capitec"
        if "yoco" in blob:
            return "yoco"
        return ""

    @api.depends(
        "description",
        "reference",
        "amount",
        "bank_date",
        "match_state",
        "company_id",
        "currency_id",
    )
    def _compute_booking_suggestion(self):
        Account = self.env["account.account"]
        for line in self:
            line.booking_suggestion = False
            line.suggested_expense_account_id = False
            line.suggested_income_account_id = False
            if line.match_state in ("matched", "imported", "skipped"):
                continue
            inferred = line._avea_infer_booking()
            line.booking_suggestion = inferred["booking_suggestion"]
            if inferred["suggested_expense_account_id"]:
                line.suggested_expense_account_id = Account.browse(
                    inferred["suggested_expense_account_id"]
                )
            if inferred["suggested_income_account_id"]:
                line.suggested_income_account_id = Account.browse(
                    inferred["suggested_income_account_id"]
                )

    def _avea_expense_wizard_payee_context(self):
        self.ensure_one()
        inferred = self._avea_infer_booking()
        role = inferred.get("partner_role") or "supplier"
        partner = AveaBankReconcileBookingRules.suggest_partner(
            self.env,
            company=self.company_id,
            partner_role=role,
            description=self.description,
            reference=self.reference,
        )
        hint = inferred.get("booking_suggestion") if inferred.get("from_memory") else (
            AveaBankReconcileBookingRules.partner_hint_for_role(role)
        )
        what_for = "expense"
        if role == "employee":
            blob = f"{self.description or ''} {self.reference or ''}".lower()
            what_for = "advance" if "advance" in blob else "salary"
        ctx = {
            "avea_booking_partner_role": role,
            "default_partner_hint": hint,
            "default_what_for": what_for,
        }
        if role == "employee":
            ctx["avea_expense_payee_person"] = True
            ctx["avea_staff_payee"] = True
            ctx["default_is_company"] = False
            ctx["default_avea_is_employee"] = True
        if inferred.get("learned_partner_id"):
            ctx["default_partner_id"] = inferred["learned_partner_id"]
        elif partner:
            ctx["default_partner_id"] = partner.id
        return ctx

    def _avea_infer_booking(self):
        self.ensure_one()
        return AveaBankReconcileBookingRules.infer(
            self.env,
            company=self.company_id,
            description=self.description,
            reference=self.reference,
            amount=self.amount,
            bank_date=self.bank_date,
            currency=self.currency_id,
        )

    @api.onchange("amount", "description", "reference", "match_state")
    def _onchange_amount_default_import(self):
        if self.reconciliation_id and self.match_state == "unmatched":
            inferred = self._avea_infer_booking()
            if inferred.get("import_action"):
                self.import_action = inferred["import_action"]
                return
        if self.amount and self.amount < 0:
            self.import_action = "expense"
        elif self.amount and self.amount > 0:
            self.import_action = "income"

    def _avea_apply_booking_suggestion(self):
        for line in self:
            if line.match_state in ("matched", "imported", "skipped"):
                continue
            inferred = line._avea_infer_booking()
            if inferred.get("import_action"):
                line.import_action = inferred["import_action"]

    @api.onchange("statement_line_id")
    def _onchange_statement_line_id(self):
        if not self.statement_line_id:
            self.match_locked = False
            return
        if not self._avea_amounts_equal(self.statement_line_id.amount):
            if self._avea_amounts_near(
                self.statement_line_id.amount, _MATCH_MANUAL_NEAR_TOLERANCE
            ):
                score, hint = self._avea_score_candidate(self.statement_line_id)
                self.match_confidence = score or _MATCH_SUGGEST
                self.match_hint = hint or _("amount close — Accept to write off rounding")
                self.match_state = "possible"
                self.match_locked = True
                return
            self.match_state = "unmatched"
            self.match_confidence = 0.0
            self.match_hint = _("Amount differs — choose a book entry with the same amount.")
            self.match_locked = False
            self.statement_line_id = False
            return
        score, hint = self._avea_score_candidate(self.statement_line_id)
        self.match_confidence = score
        self.match_hint = hint
        self.match_state = "matched"
        self.match_locked = True

    def _avea_amounts_equal(self, other_amount):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        return currency.compare_amounts(other_amount, self.amount) == 0

    def _avea_amounts_near(self, other_amount, tolerance=_MATCH_NEAR_TOLERANCE):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        if currency.compare_amounts(self.amount or 0.0, 0.0) == 0:
            return False
        if (self.amount >= 0.0) != ((other_amount or 0.0) >= 0.0):
            return False
        return abs((self.amount or 0.0) - (other_amount or 0.0)) <= (tolerance + 1e-9)

    def _avea_name_tokens(self, text):
        words = re.findall(r"[a-z0-9]+", (text or "").lower())
        return [word for word in words if len(word) >= 3 and word not in _NAME_STOPWORDS]

    def _avea_candidate_name_blob(self, candidate):
        cache = self.env.context.get("avea_recon_name_blob_cache")
        if cache is not None and candidate.id in cache:
            return cache[candidate.id]
        partner = candidate.partner_id
        parts = [
            candidate.payment_ref or "",
            candidate.move_id.ref or "",
            partner.display_name if partner else "",
            partner.name if partner else "",
            partner.ref if partner else "",
            partner.commercial_company_name if partner else "",
        ]
        blob = " ".join(filter(None, parts)).lower()
        if cache is not None:
            cache[candidate.id] = blob
        return blob

    def _avea_recalled_payee(self):
        self.ensure_one()
        cache = self.env.context.get("avea_recon_recall_cache")
        key = (self.id or 0, self.description or "", self.reference or "")
        if cache is not None and key in cache:
            return cache[key]
        recalled = AveaBankReconcileBookingRules.recall_payee(
            self.env,
            company=self.company_id or self.env.company,
            description=self.description,
            reference=self.reference,
        )
        if cache is not None:
            cache[key] = recalled
        return recalled

    def _avea_name_match(self, candidate):
        self.ensure_one()
        blob = self._avea_candidate_name_blob(candidate)
        bank_text = " ".join(filter(None, [self.reference or "", self.description or ""]))
        lowered = bank_text.strip().lower()
        if len(lowered) >= 4 and lowered in blob:
            return True, _("description")
        tokens = self._avea_name_tokens(bank_text)
        blob_tokens = set(self._avea_name_tokens(blob))
        if tokens and (set(tokens) & blob_tokens or any(token in blob for token in tokens)):
            return True, _("name")
        recalled = self._avea_recalled_payee()
        if recalled and candidate.partner_id and recalled == candidate.partner_id:
            return True, _("name")
        payee = AveaBankReconcileBookingRules._avea_extract_merchant_name(self.description)
        if payee and candidate.partner_id:
            partner_name = (candidate.partner_id.display_name or "").lower()
            if payee.lower() in partner_name or partner_name in payee.lower():
                return True, _("name")
        return False, ""

    def _avea_score_candidate(self, candidate):
        self.ensure_one()
        exact = self._avea_amounts_equal(candidate.amount)
        near = self._avea_amounts_near(candidate.amount, _MATCH_NEAR_TOLERANCE)
        if not exact and not near:
            return 0.0, ""
        name_ok, name_hint = self._avea_name_match(candidate)
        move_date = candidate.date or candidate.move_id.date
        if not exact:
            if not name_ok:
                return 0.0, ""
            score = _MATCH_SUGGEST
            hints = [name_hint or _("name"), _("amount close")]
            if move_date == self.bank_date:
                score += 5.0
                hints.append(_("date"))
            elif move_date and abs((move_date - self.bank_date).days) <= 3:
                score += 2.0
                hints.append(_("near date"))
            return min(score, _MATCH_AUTO - 1.0), ", ".join(hints)
        score = 50.0
        hints = [_("amount")]
        if move_date == self.bank_date:
            score += 25.0
            hints.append(_("date"))
        elif move_date and abs((move_date - self.bank_date).days) <= 3:
            score += 10.0
            hints.append(_("near date"))
        if name_ok:
            score += 20.0
            hints.append(name_hint or _("name"))
        else:
            for token in (self.reference, self.description):
                token = (token or "").strip().lower()
                blob = self._avea_candidate_name_blob(candidate)
                if len(token) >= 4 and token in blob:
                    score += 20.0
                    hints.append(_("description"))
                    break
        return score, ", ".join(hints)

    def _avea_supplier_payment_counterpart(self, pool=None, used=None):
        """Existing supplier payment that this bank debit should link to."""
        self.ensure_one()
        if self.match_state in ("matched", "imported", "skipped"):
            return self.env["account.bank.statement.line"]
        reconciliation = self.reconciliation_id
        if not reconciliation:
            return self.env["account.bank.statement.line"]
        if pool is None:
            pool = reconciliation._avea_uncleared_book_lines()
        if used is None:
            used = set(
                reconciliation.line_ids.filtered(
                    lambda line: line.id != self.id and line.statement_line_id
                ).mapped("statement_line_id").ids
            )
        available = pool.filtered(lambda candidate: candidate.id not in used)
        near = available.filtered(
            lambda candidate: self._avea_amounts_near(
                candidate.amount, _MATCH_NEAR_TOLERANCE
            )
        )
        named_near = near.filtered(lambda candidate: self._avea_name_match(candidate)[0])
        if named_near:
            return named_near[:1]
        similar = available.filtered(
            lambda candidate: self._avea_amounts_near(candidate.amount, 2.0)
        )
        named_similar = similar.filtered(
            lambda candidate: self._avea_name_match(candidate)[0]
        )
        if len(named_similar) == 1:
            return named_similar
        return self.env["account.bank.statement.line"]

    def _avea_remember_matched_payee(self, candidate=None):
        for line in self:
            st_line = candidate or line.statement_line_id
            if not st_line or not st_line.partner_id:
                continue
            AveaBankReconcileBookingRules.remember_payee(
                line.env,
                company=line.company_id or line.env.company,
                description=line.description,
                reference=line.reference,
                partner=st_line.partner_id,
            )

    def _avea_rounding_account(self, more_out):
        self.ensure_one()
        journal = self.journal_id
        if more_out and journal.loss_account_id:
            return journal.loss_account_id
        if not more_out and journal.profit_account_id:
            return journal.profit_account_id
        return self.env["avea.bank.reconcile.apply"]._avea_fee_account(
            self.company_id or self.env.company
        ) or self.env["account.account"].sudo().search(
            [
                ("company_ids", "in", (self.company_id or self.env.company).id),
                ("account_type", "in", ("expense", "expense_other")),
            ],
            limit=1,
        )

    def _avea_apply_rounding_writeoff(self, st_line):
        """Post a small bank rounding entry so the recon still balances."""
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        delta = currency.round((self.amount or 0.0) - (st_line.amount or 0.0))
        if currency.is_zero(delta):
            return self.env["account.move"]
        if abs(delta) > _MATCH_MANUAL_NEAR_TOLERANCE + 1e-9:
            raise UserError(
                _("The book amount must be the same as the statement amount.")
            )
        if self.writeoff_move_id:
            return self.writeoff_move_id
        bank_account = self.journal_id.default_account_id
        rounding_account = self._avea_rounding_account(more_out=delta < 0)
        if not bank_account or not rounding_account:
            raise UserError(
                _("Set a rounding or bank-charge account before writing off cents.")
            )
        company = self.company_id or self.env.company
        entry_journal = self.env["account.journal"].sudo().search(
            [("type", "=", "general"), ("company_id", "=", company.id)],
            limit=1,
        ) or self.journal_id
        abs_delta = abs(delta)
        if delta < 0:
            bank_debit, bank_credit = 0.0, abs_delta
            round_debit, round_credit = abs_delta, 0.0
        else:
            bank_debit, bank_credit = abs_delta, 0.0
            round_debit, round_credit = 0.0, abs_delta
        move = (
            self.env["account.move"]
            .sudo()
            .create(
                {
                    "journal_id": entry_journal.id,
                    "date": self.bank_date,
                    "ref": (_("Bank rounding: %s") % (self.description or st_line.payment_ref or ""))[:64],
                    "line_ids": [
                        Command.create(
                            {
                                "name": _("Bank rounding"),
                                "account_id": bank_account.id,
                                "debit": bank_debit,
                                "credit": bank_credit,
                            }
                        ),
                        Command.create(
                            {
                                "name": _("Bank rounding"),
                                "account_id": rounding_account.id,
                                "debit": round_debit,
                                "credit": round_credit,
                            }
                        ),
                    ],
                }
            )
        )
        move.action_post()
        self.write(
            {
                "writeoff_move_id": move.id,
                "writeoff_amount": delta,
            }
        )
        return move

    def action_accept_line_match(self):
        self.ensure_one()
        self._avea_accept_match()
        self.reconciliation_id._avea_find_orphan_book_lines()
        return self.reconciliation_id._avea_action_form()

    def _avea_accept_match(self):
        self.ensure_one()
        st_line = self.statement_line_id
        if not st_line:
            raise UserError(_("Choose the book entry before accepting this match."))
        if not self._avea_amounts_equal(st_line.amount):
            if not self._avea_amounts_near(st_line.amount, _MATCH_MANUAL_NEAR_TOLERANCE):
                raise UserError(
                    _("The book amount must be the same as the statement amount.")
                )
            name_ok, _hint = self._avea_name_match(st_line)
            if not name_ok and not self._avea_amounts_near(
                st_line.amount, _MATCH_NEAR_TOLERANCE
            ):
                raise UserError(
                    _("The book amount must be the same as the statement amount.")
                )
            self._avea_apply_rounding_writeoff(st_line)
        if st_line.avea_cleared and st_line.avea_cleared_reconciliation_id != self.reconciliation_id:
            raise UserError(_("That book entry is already cleared on another statement."))
        duplicate = self.reconciliation_id.line_ids.filtered(
            lambda line: line.id != self.id and line.statement_line_id == st_line
        )
        if duplicate:
            raise UserError(_("That book entry is already linked to another statement line."))
        self._avea_remember_matched_payee(st_line)
        self.write(
            {
                "match_state": "matched",
                "match_locked": True,
            }
        )

    def _avea_default_import_action(self):
        self.ensure_one()
        if self.currency_id.compare_amounts(self.amount, 0.0) < 0:
            return "expense"
        if self.currency_id.compare_amounts(self.amount, 0.0) > 0:
            return "income"
        return "skip"

    def action_open_allocate_wizard(self):
        self.ensure_one()
        if self.match_state in ("matched", "imported"):
            raise UserError(_("This statement line is already matched."))
        if self.currency_id.is_zero(self.amount):
            raise UserError(_("This statement line has no amount."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Match this bank line"),
            "res_model": "avea.bank.reconcile.apply",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_reconcile_line_id": self.id,
                "default_mode": "settlement" if self.is_card_settlement else "match",
            },
        }

    def action_open_booking_wizard(self):
        self.ensure_one()
        if self._avea_supplier_payment_counterpart() or (
            self.statement_line_id and self.match_state != "matched"
        ):
            raise UserError(
                _(
                    "This bank line already has a supplier payment in Avea. "
                    "Use Match to link it — recording an expense would pay it twice."
                )
            )
        action = self.import_action
        if action == "expense":
            return self._avea_open_expense_wizard()
        if action == "income":
            return self._avea_open_income_wizard()
        if action == "create":
            raise UserError(
                _(
                    "Record the expense or income so it posts to the right account. "
                    "Importing it to suspense does not reconcile the bank."
                )
            )
        if action == "skip":
            raise UserError(
                _(
                    "A statement line cannot be skipped. Match it to a book entry "
                    "or record the expense or income."
                )
            )
        raise UserError(_("Choose what to do with this bank line."))

    def _avea_open_expense_wizard(self):
        self.ensure_one()
        amount = abs(self.amount)
        if self.currency_id.compare_amounts(amount, 0.0) <= 0:
            raise UserError(_("This line is not an outgoing payment."))
        title = self.booking_suggestion or _("Record expense")
        ctx = {
                **self.env.context,
                "default_bank_reconcile_line_id": self.id,
                "default_expense_date": self.bank_date,
                "default_description": (self.description or _("Bank statement"))[:255],
                "default_document_ref": self.reference,
                "default_amount": amount,
                "default_paid_from_journal_id": self.reconciliation_id.journal_id.id,
                "default_company_id": self.reconciliation_id.company_id.id,
            }
        if self.suggested_expense_account_id:
            ctx["default_expense_account_id"] = self.suggested_expense_account_id.id
        ctx.update(self._avea_expense_wizard_payee_context())
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": "avea.operational.expense.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "avea_till.view_avea_operational_expense_wizard_form"
            ).id,
            "target": "new",
            "context": ctx,
        }

    def _avea_open_income_wizard(self):
        self.ensure_one()
        amount = abs(self.amount)
        if self.currency_id.compare_amounts(amount, 0.0) <= 0:
            raise UserError(_("This line is not money received."))
        title = self.booking_suggestion or _("Record income")
        ctx = {
                **self.env.context,
                "default_bank_reconcile_line_id": self.id,
                "default_income_date": self.bank_date,
                "default_description": (self.description or _("Bank statement"))[:255],
                "default_document_ref": self.reference,
                "default_amount": amount,
                "default_received_in_journal_id": self.reconciliation_id.journal_id.id,
                "default_company_id": self.reconciliation_id.company_id.id,
            }
        if self.suggested_income_account_id:
            ctx["default_income_account_id"] = self.suggested_income_account_id.id
        inferred = self._avea_infer_booking()
        if inferred.get("learned_partner_id"):
            ctx["default_partner_id"] = inferred["learned_partner_id"]
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": "avea.operational.income.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "avea_till.view_avea_operational_income_wizard_form"
            ).id,
            "target": "new",
            "context": ctx,
        }

    def _avea_after_booked(self, statement_line, hint=None):
        self.ensure_one()
        self.write(
            {
                "statement_line_id": statement_line.id,
                "match_state": "matched",
                "match_locked": True,
                "match_confidence": 100.0,
                "match_hint": hint or _("Recorded from Avea"),
            }
        )
        self._avea_remember_matched_payee(statement_line)
        reconciliation = self.reconciliation_id
        reconciliation._avea_find_orphan_book_lines()
        return reconciliation._avea_action_form()

    def _avea_confirm_match(self):
        self.ensure_one()
        st_line = self.statement_line_id
        if not st_line or self.match_state != "matched":
            raise UserError(_("Every statement line must be matched before completing."))
        effective = st_line.amount + (self.writeoff_amount or 0.0)
        if not self._avea_amounts_equal(effective):
            raise UserError(_("The book amount must be the same as the statement amount."))
        if st_line.avea_cleared and st_line.avea_cleared_reconciliation_id != self.reconciliation_id:
            raise UserError(_("That book entry is already cleared on another statement."))
        details = dict(st_line.transaction_details or {})
        details["avea_bank_reconcile"] = {
            "bank_date": fields.Date.to_string(self.bank_date),
            "bank_reference": self.reference,
            "bank_description": self.description,
            "import_amount": self.amount,
            "reconciliation_id": self.reconciliation_id.id,
        }
        st_line.sudo().write(
            {
                "transaction_details": details,
                "avea_cleared": True,
                "avea_cleared_reconciliation_id": self.reconciliation_id.id,
            }
        )
        self.match_locked = True

    def _avea_create_statement_line(self):
        self.ensure_one()
        reconciliation = self.reconciliation_id
        journal = reconciliation.journal_id
        suspense = journal.suspense_account_id
        if not suspense:
            raise UserError(
                _(
                    "The bank journal %(journal)s needs a suspense account for "
                    "imported statement lines. Ask your accountant to set it under "
                    "Accounting → Configuration → Journals.",
                    journal=journal.display_name,
                )
            )
        payment_ref = self.description or self.reference or _("Bank statement")
        if self.reference and self.description and self.reference not in self.description:
            payment_ref = f"{self.description} ({self.reference})"
        payment_ref = payment_ref[:255]
        st_line = (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(
                {
                    "journal_id": journal.id,
                    "amount": self.amount,
                    "date": self.bank_date,
                    "payment_ref": payment_ref,
                    "counterpart_account_id": suspense.id,
                }
            )
        )
        details = {
            "avea_bank_reconcile": {
                "source": reconciliation.source_format,
                "bank_reference": self.reference,
                "imported": True,
            }
        }
        st_line.sudo().write({"transaction_details": details})
        self.write(
            {
                "statement_line_id": st_line.id,
                "match_state": "imported",
            }
        )


class AveaBankReconcileMerchantFile(models.Model):
    _name = "avea.bank.reconcile.merchant.file"
    _description = "Card machine file on a bank reconciliation"

    reconciliation_id = fields.Many2one(
        "avea.bank.reconciliation",
        required=True,
        ondelete="cascade",
    )
    datas = fields.Binary(string="File", required=True, attachment=True)
    filename = fields.Char(string="Filename")
    provider = fields.Selection(
        selection=[("yoco", "Yoco"), ("capitec", "Capitec")],
        string="Machine",
        readonly=True,
    )
    date_from = fields.Date(readonly=True)
    date_to = fields.Date(readonly=True)
    period_warning = fields.Char(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._avea_notify_reconciliation()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "datas" in vals:
            self._avea_notify_reconciliation()
        return res

    def unlink(self):
        recons = self.mapped("reconciliation_id").filtered(
            lambda rec: rec.state == "in_progress"
        )
        res = super().unlink()
        recons.exists()._avea_refresh_after_merchant_files()
        return res

    def _avea_notify_reconciliation(self):
        if self.env.context.get("avea_skip_merchant_refresh"):
            return
        self.mapped("reconciliation_id").filtered(
            lambda rec: rec.state == "in_progress"
        )._avea_refresh_after_merchant_files()


class AveaBankReconcileMerchantPayout(models.Model):
    _name = "avea.bank.reconcile.merchant.payout"
    _description = "Card machine payout"
    _order = "payout_date, id"

    reconciliation_id = fields.Many2one(
        "avea.bank.reconciliation",
        required=True,
        ondelete="cascade",
    )
    file_id = fields.Many2one(
        "avea.bank.reconcile.merchant.file",
        ondelete="cascade",
    )
    provider = fields.Selection(
        selection=[("yoco", "Yoco"), ("capitec", "Capitec")],
        required=True,
    )
    payout_date = fields.Date(required=True)
    trading_date = fields.Date()
    net_amount = fields.Monetary(currency_field="currency_id", required=True)
    gross_amount = fields.Monetary(currency_field="currency_id")
    fee_amount = fields.Monetary(string="Fee incl. VAT", currency_field="currency_id")
    capital_amount = fields.Monetary(string="Capital repaid", currency_field="currency_id")
    reference = fields.Char()
    on_this_statement = fields.Boolean()
    currency_id = fields.Many2one(related="reconciliation_id.currency_id")
    line_ids = fields.One2many(
        "avea.bank.reconcile.line",
        "merchant_payout_id",
        string="Bank line",
    )


class AveaBankReconcileBookLine(models.Model):
    _name = "avea.bank.reconcile.book.line"
    _description = "Book entry missing from bank statement"

    reconciliation_id = fields.Many2one(
        "avea.bank.reconciliation",
        required=True,
        ondelete="cascade",
    )
    statement_line_id = fields.Many2one(
        "account.bank.statement.line",
        required=True,
        ondelete="cascade",
    )
    book_date = fields.Date()
    label = fields.Char()
    amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="reconciliation_id.currency_id")
