# -*- coding: utf-8 -*-
import base64
import re

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .bank_reconcile_booking_rules import AveaBankReconcileBookingRules
from .bank_statement_parser import AveaBankStatementParser

# Exact amount is 50. Exact date adds 25 (auto). A shared description adds 20
# and is enough to auto-match. A nearby date alone stays a suggestion.
_MATCH_AUTO = 70.0
_MATCH_SUGGEST = 60.0


class AveaBankReconciliation(models.Model):
    _name = "avea.bank.reconciliation"
    _description = "Bank Reconciliation"
    _order = "write_date desc, id desc"

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
    date_from = fields.Date(string="From", readonly=True)
    date_to = fields.Date(string="To", readonly=True)
    opening_balance = fields.Monetary(
        string="Opening balance (bank)",
        currency_field="currency_id",
        readonly=True,
    )
    closing_balance = fields.Monetary(
        string="Closing balance (bank)",
        currency_field="currency_id",
        readonly=True,
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
    matched_count = fields.Integer(compute="_compute_counts")
    possible_match_count = fields.Integer(compute="_compute_counts")
    unmatched_bank_count = fields.Integer(compute="_compute_counts")
    orphan_book_count = fields.Integer(compute="_compute_counts")
    import_count = fields.Integer(compute="_compute_counts")
    balances_from_file = fields.Boolean(
        string="Balances read from the statement",
        readonly=True,
    )
    prior_items_outstanding = fields.Boolean(
        string="Older book entries are still missing from the bank",
        help="Leave this off when you are starting bank reconciliation and the "
        "opening balances already agree. Book entries from before this statement "
        "then stay in the opening balance. Turn it on when a payment from before "
        "this statement has still not appeared on the bank.",
    )
    gl_balance = fields.Monetary(
        string="Balance on your books",
        currency_field="currency_id",
        compute="_compute_reconciliation_balance",
    )
    outstanding_amount = fields.Monetary(
        string="Outstanding on books",
        currency_field="currency_id",
        compute="_compute_reconciliation_balance",
        help="Book entries up to the statement end that are not on this statement.",
    )
    adjusted_book_balance = fields.Monetary(
        string="Books after outstanding items",
        currency_field="currency_id",
        compute="_compute_reconciliation_balance",
    )
    has_previous_statement = fields.Boolean(compute="_compute_reconciliation_balance")
    previous_closing_balance = fields.Monetary(
        string="Previous statement balance",
        currency_field="currency_id",
        compute="_compute_reconciliation_balance",
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

    @api.depends(
        "journal_id",
        "company_id",
        "currency_id",
        "date_to",
        "opening_balance",
        "closing_balance",
        "balances_from_file",
        "prior_items_outstanding",
        "account_number",
        "state",
        "line_ids.amount",
        "line_ids.match_state",
        "line_ids.statement_line_id",
        "book_line_ids.amount",
    )
    def _compute_reconciliation_balance(self):
        for reconciliation in self:
            currency = reconciliation.currency_id or self.env.company.currency_id
            gl_balance = reconciliation._avea_gl_bank_balance()
            outstanding_lines = reconciliation._avea_outstanding_statement_lines()
            outstanding_amount = sum(outstanding_lines.mapped("amount"))
            adjusted = gl_balance - outstanding_amount
            closing = reconciliation.closing_balance or 0.0
            reconciliation.gl_balance = gl_balance
            reconciliation.outstanding_amount = outstanding_amount
            reconciliation.adjusted_book_balance = adjusted
            reconciliation.statement_difference = closing - adjusted
            prior = reconciliation._avea_previous_reconciliation()
            reconciliation.has_previous_statement = bool(prior)
            reconciliation.previous_closing_balance = prior.closing_balance if prior else 0.0
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
            if (
                prior
                and not currency.is_zero(
                    (reconciliation.opening_balance or 0.0) - prior.closing_balance
                )
            ):
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
        if not self.journal_id or not self.date_from:
            return self.browse()
        return self.search(
            [
                ("id", "!=", self.id),
                ("journal_id", "=", self.journal_id.id),
                ("state", "=", "done"),
                ("date_to", "<", self.date_from),
            ],
            order="date_to desc, id desc",
            limit=1,
        )

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
                ("date_from", "<=", self.date_to),
                ("date_to", ">=", self.date_from),
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
            if not currency.is_zero(line.statement_line_id.amount - line.amount):
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
        """Public RPC entry: create an empty draft reconciliation and return its id."""
        journal = self._avea_default_bank_journal()
        reconciliation = self.create(
            {
                "journal_id": journal.id if journal else False,
                "state": "draft",
            }
        )
        return reconciliation.id

    def _avea_default_bank_journal(self):
        company = self.env.company
        configured = company._avea_expense_journals().filtered(lambda j: j.type == "bank")
        return configured[:1] or self.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", company.id)],
            limit=1,
        )

    def _avea_action_form(self, title=None):
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
        parsed = AveaBankStatementParser.parse(self.statement_filename or "statement.csv", raw)
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
        self._avea_apply_booking_suggestions()
        self._avea_find_orphan_book_lines()
        return self._avea_action_form()

    def action_refresh_matches(self):
        self.ensure_one()
        self._avea_match_lines()
        self._avea_apply_booking_suggestions()
        self._avea_find_orphan_book_lines()
        return self._avea_action_form()

    def _avea_apply_booking_suggestions(self):
        self.ensure_one()
        for line in self.line_ids:
            line._avea_apply_booking_suggestion()

    def _avea_uncleared_book_lines(self):
        """Book entries still available to tick off, including older outstanding items."""
        self.ensure_one()
        domain = [
            ("journal_id", "=", self.journal_id.id),
            ("company_id", "=", self.company_id.id),
            ("avea_cleared", "=", False),
        ]
        if self.date_to:
            domain.append(("date", "<=", self.date_to))
        return self.env["account.bank.statement.line"].search(
            domain, order="date desc, id desc"
        )

    def _avea_match_lines(self):
        self.ensure_one()
        pool = self._avea_uncleared_book_lines()
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
    _order = "sequence, id"

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
    import_action = fields.Selection(
        selection=[
            ("expense", "Record expense"),
            ("income", "Record income"),
            ("create", "Quick import (suspense)"),
            ("skip", "Skip"),
        ],
        string="If unmatched",
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
        string="Link to book entry",
        domain="[('journal_id', '=', journal_id), ('avea_cleared', '=', False)]",
        context={"avea_bank_reconcile_labels": True},
    )
    book_match_summary = fields.Char(
        string="On your books",
        compute="_compute_book_match_summary",
    )
    match_confidence = fields.Float(string="Match %", readonly=True)
    match_hint = fields.Char(string="Match reason", readonly=True)
    match_locked = fields.Boolean(
        string="Match kept",
        default=False,
        help="Set when you choose the book entry yourself, so a refresh does not replace it.",
    )
    booking_suggestion = fields.Char(
        string="Suggested booking",
        compute="_compute_booking_suggestion",
        help="Based on the bank description — like bank rules in Xero or QuickBooks. "
        "Click Book… to confirm; nothing is posted until you do.",
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
            elif line.match_state == "unmatched" and line.booking_suggestion:
                line.book_match_summary = line.booking_suggestion
            else:
                line.book_match_summary = False

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
        hint = AveaBankReconcileBookingRules.partner_hint_for_role(role)
        ctx = {
            "avea_booking_partner_role": role,
            "default_partner_hint": hint,
        }
        if role == "employee":
            ctx["avea_expense_payee_person"] = True
            ctx["default_is_company"] = False
        if partner:
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

    def _avea_score_candidate(self, candidate):
        self.ensure_one()
        if not self._avea_amounts_equal(candidate.amount):
            return 0.0, ""
        score = 50.0
        hints = [_("amount")]
        move_date = candidate.date or candidate.move_id.date
        if move_date == self.bank_date:
            score += 25.0
            hints.append(_("date"))
        elif move_date and abs((move_date - self.bank_date).days) <= 3:
            score += 10.0
            hints.append(_("near date"))
        ref_blob = " ".join(
            filter(
                None,
                [
                    candidate.payment_ref or "",
                    candidate.move_id.ref or "",
                    candidate.move_id.narration or "",
                    candidate.partner_id.display_name if candidate.partner_id else "",
                ],
            )
        ).lower()
        for token in (self.reference, self.description):
            token = (token or "").strip().lower()
            if len(token) >= 4 and token in ref_blob:
                score += 20.0
                hints.append(_("description"))
                break
            words = [w for w in token.split() if len(w) >= 4]
            if any(word in ref_blob for word in words[:4]):
                score += 20.0
                hints.append(_("name"))
                break
        return score, ", ".join(hints)

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
            raise UserError(
                _("The book amount must be the same as the statement amount.")
            )
        if st_line.avea_cleared and st_line.avea_cleared_reconciliation_id != self.reconciliation_id:
            raise UserError(_("That book entry is already cleared on another statement."))
        duplicate = self.reconciliation_id.line_ids.filtered(
            lambda line: line.id != self.id and line.statement_line_id == st_line
        )
        if duplicate:
            raise UserError(_("That book entry is already linked to another statement line."))
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
            "name": _("Match, split, or transfer"),
            "res_model": "avea.bank.reconcile.apply",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_reconcile_line_id": self.id,
                "default_mode": "match",
            },
        }

    def action_open_booking_wizard(self):
        self.ensure_one()
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

    def _avea_after_booked(self, statement_line):
        self.ensure_one()
        self.write(
            {
                "statement_line_id": statement_line.id,
                "match_state": "matched",
                "match_locked": True,
                "match_confidence": 100.0,
                "match_hint": _("Recorded from Avea"),
            }
        )
        reconciliation = self.reconciliation_id
        reconciliation._avea_find_orphan_book_lines()
        return reconciliation._avea_action_form()

    def _avea_confirm_match(self):
        self.ensure_one()
        st_line = self.statement_line_id
        if not st_line or self.match_state != "matched":
            raise UserError(_("Every statement line must be matched before completing."))
        if not self._avea_amounts_equal(st_line.amount):
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


class AveaBankReconcileBookLine(models.Model):
    _name = "avea.bank.reconcile.book.line"
    _description = "Book entry missing from bank statement"

    reconciliation_id = fields.Many2one(
        "avea.bank.reconciliation",
        required=True,
        ondelete="cascade",
    )
    statement_line_id = fields.Many2one("account.bank.statement.line", required=True)
    book_date = fields.Date()
    label = fields.Char()
    amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="reconciliation_id.currency_id")
