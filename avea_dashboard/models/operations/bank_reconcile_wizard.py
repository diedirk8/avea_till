# -*- coding: utf-8 -*-
import base64
from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .bank_statement_parser import AveaBankStatementParser

_MATCH_AUTO = 70.0
_MATCH_SUGGEST = 50.0


class AveaBankReconcileWizard(models.TransientModel):
    _name = "avea.bank.reconcile.wizard"
    _description = "Bank Reconciliation"

    state = fields.Selection(
        selection=[
            ("upload", "Upload"),
            ("review", "Review"),
            ("done", "Done"),
        ],
        default="upload",
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
    statement_file = fields.Binary(string="Statement file", attachment=False)
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
        "wizard_id",
        string="Bank transactions",
    )
    book_line_ids = fields.One2many(
        "avea.bank.reconcile.book.line",
        "wizard_id",
        string="On your books, not on statement",
    )
    matched_count = fields.Integer(compute="_compute_counts")
    possible_match_count = fields.Integer(compute="_compute_counts")
    unmatched_bank_count = fields.Integer(compute="_compute_counts")
    orphan_book_count = fields.Integer(compute="_compute_counts")
    import_count = fields.Integer(compute="_compute_counts")

    @api.depends("line_ids.match_state", "book_line_ids")
    def _compute_counts(self):
        for wizard in self:
            wizard.import_count = len(wizard.line_ids)
            wizard.matched_count = len(
                wizard.line_ids.filtered(lambda line: line.match_state == "matched")
            )
            wizard.possible_match_count = len(
                wizard.line_ids.filtered(lambda line: line.match_state == "possible")
            )
            wizard.unmatched_bank_count = len(
                wizard.line_ids.filtered(lambda line: line.match_state == "unmatched")
            )
            wizard.orphan_book_count = len(wizard.book_line_ids)

    @api.model
    def action_open_wizard(self):
        journal = self._avea_default_bank_journal()
        wizard = self.create({"journal_id": journal.id if journal else False})
        return wizard._avea_action_form(_("Bank reconciliation"))

    def _avea_default_bank_journal(self):
        company = self.env.company
        configured = company._avea_expense_journals().filtered(lambda j: j.type == "bank")
        return configured[:1] or self.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", company.id)],
            limit=1,
        )

    def _avea_action_form(self, title):
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref("avea_till.view_avea_bank_reconcile_wizard_form").id,
            "target": "current",
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
                "opening_balance": parsed.get("opening_balance") or 0.0,
                "closing_balance": parsed.get("closing_balance") or 0.0,
                "line_ids": line_vals,
                "state": "review",
            }
        )
        self._avea_match_lines()
        self._avea_find_orphan_book_lines()
        return self._avea_action_form(_("Bank reconciliation"))

    def action_refresh_matches(self):
        self.ensure_one()
        self._avea_match_lines()
        self._avea_find_orphan_book_lines()
        return self._avea_action_form(_("Bank reconciliation"))

    def _avea_match_lines(self):
        self.ensure_one()
        StatementLine = self.env["account.bank.statement.line"]
        for line in self.line_ids:
            if line.match_state in ("imported", "skipped"):
                continue
            line.match_state = "unmatched"
            line.statement_line_id = False
            line.match_confidence = 0.0
            line.match_hint = False
            line.candidate_statement_line_ids = [Command.clear()]
            candidates = StatementLine.search(
                line._avea_candidate_domain(self.journal_id),
                order="move_id.date desc, id desc",
                limit=120,
            )
            scored = []
            for candidate in candidates:
                score, hint = line._avea_score_candidate(candidate)
                if score >= 35.0:
                    scored.append((score, candidate, hint))
            scored.sort(key=lambda row: row[0], reverse=True)
            top = scored[:20]
            if top:
                line.candidate_statement_line_ids = [
                    Command.set([row[1].id for row in top])
                ]
            best_line = False
            best_score = 0.0
            best_hint = ""
            if top:
                best_score, best_line, best_hint = top[0]
            vals = {
                "match_confidence": best_score,
                "match_hint": best_hint or False,
            }
            if best_line and best_score >= _MATCH_AUTO:
                vals.update(
                    {
                        "statement_line_id": best_line.id,
                        "match_state": "matched",
                    }
                )
            elif best_line and best_score >= _MATCH_SUGGEST:
                vals.update(
                    {
                        "statement_line_id": best_line.id,
                        "match_state": "possible",
                    }
                )
            line.write(vals)

    def _avea_find_orphan_book_lines(self):
        self.ensure_one()
        BookLine = self.env["avea.bank.reconcile.book.line"]
        self.book_line_ids.unlink()
        if not self.date_from or not self.date_to:
            return
        date_from = self.date_from - timedelta(days=3)
        date_to = self.date_to + timedelta(days=3)
        matched_ids = set(self.line_ids.mapped("statement_line_id").ids)
        statement_lines = self.env["account.bank.statement.line"].search(
            [
                ("journal_id", "=", self.journal_id.id),
                ("company_id", "=", self.company_id.id),
                ("is_reconciled", "=", False),
                ("move_id.date", ">=", date_from),
                ("move_id.date", "<=", date_to),
                ("id", "not in", list(matched_ids) or [0]),
            ]
        )
        rows = []
        for st_line in statement_lines:
            rows.append(
                {
                    "wizard_id": self.id,
                    "statement_line_id": st_line.id,
                    "book_date": st_line.move_id.date,
                    "label": st_line.payment_ref or st_line.move_id.ref or st_line.move_id.name,
                    "amount": st_line.amount,
                }
            )
        if rows:
            BookLine.create(rows)

    def action_apply_reconciliation(self):
        self.ensure_one()
        if self.state != "review":
            raise UserError(_("Upload and review the statement before applying."))
        created = 0
        matched = 0
        for line in self.line_ids:
            if line.match_state in ("matched", "possible") and line.statement_line_id:
                line._avea_confirm_match()
                matched += 1
            elif line.match_state == "unmatched" and line.import_action == "create":
                line._avea_create_statement_line()
                created += 1
        self.state = "done"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Bank reconciliation applied"),
                "message": _(
                    "%(matched)s matched to existing entries, %(created)s new bank lines created.",
                    matched=matched,
                    created=created,
                ),
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }


class AveaBankReconcileLine(models.TransientModel):
    _name = "avea.bank.reconcile.line"
    _description = "Bank reconciliation import line"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "avea.bank.reconcile.wizard",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    bank_date = fields.Date(string="Date", required=True)
    description = fields.Char()
    reference = fields.Char()
    amount = fields.Monetary(currency_field="currency_id", required=True)
    balance_after = fields.Monetary(string="Bank balance", currency_field="currency_id")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
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
    )
    statement_line_id = fields.Many2one(
        "account.bank.statement.line",
        string="Link to book entry",
        domain="[('journal_id', '=', parent.journal_id), ('is_reconciled', '=', False)]",
        context="{'avea_bank_reconcile_labels': 1}",
    )
    book_match_summary = fields.Char(
        string="On your books",
        compute="_compute_book_match_summary",
    )
    match_confidence = fields.Float(string="Match %", readonly=True)
    match_hint = fields.Char(string="Match reason", readonly=True)
    company_id = fields.Many2one(related="wizard_id.company_id")

    @api.depends("statement_line_id", "match_confidence", "match_hint")
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

    @api.onchange("amount")
    def _onchange_amount_default_import(self):
        if self.amount and self.amount < 0:
            self.import_action = "expense"
        elif self.amount and self.amount > 0:
            self.import_action = "income"

    @api.onchange("statement_line_id")
    def _onchange_statement_line_id(self):
        if self.statement_line_id:
            score, hint = self._avea_score_candidate(self.statement_line_id)
            self.match_confidence = score
            self.match_hint = hint
            if score >= _MATCH_AUTO:
                self.match_state = "matched"
            elif score >= _MATCH_SUGGEST:
                self.match_state = "possible"

    def _avea_candidate_domain(self, journal):
        self.ensure_one()
        date_from = self.bank_date - timedelta(days=5)
        date_to = self.bank_date + timedelta(days=5)
        currency = self.wizard_id.currency_id
        domain = [
            ("journal_id", "=", journal.id),
            ("company_id", "=", journal.company_id.id),
            ("is_reconciled", "=", False),
            ("move_id.date", ">=", date_from),
            ("move_id.date", "<=", date_to),
        ]
        return domain

    def _avea_score_candidate(self, candidate):
        self.ensure_one()
        currency = self.wizard_id.currency_id
        score = 25.0
        hints = []
        bank_amt = self.amount
        cand_amt = candidate.amount
        if currency.compare_amounts(cand_amt, bank_amt) == 0:
            score += 40.0
            hints.append(_("amount"))
        elif currency.compare_amounts(abs(cand_amt), abs(bank_amt)) == 0:
            score += 28.0
            hints.append(_("amount (sign differs)"))
        else:
            diff = abs(cand_amt - bank_amt)
            if currency.compare_amounts(diff, 1.0) <= 0:
                score += 18.0
                hints.append(_("close amount"))
            elif bank_amt and abs(diff / bank_amt) <= 0.01:
                score += 12.0
                hints.append(_("near amount"))
        move_date = candidate.move_id.date
        if move_date == self.bank_date:
            score += 20.0
            hints.append(_("date"))
        elif move_date and abs((move_date - self.bank_date).days) <= 2:
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
                score += 15.0
                hints.append(_("description"))
                break
            words = [w for w in token.split() if len(w) >= 4]
            if any(word in ref_blob for word in words[:4]):
                score += 10.0
                hints.append(_("name"))
                break
        return score, ", ".join(hints)

    def _avea_default_import_action(self):
        self.ensure_one()
        if self.currency_id.compare_amounts(self.amount, 0.0) < 0:
            return "expense"
        if self.currency_id.compare_amounts(self.amount, 0.0) > 0:
            return "income"
        return "skip"

    def action_open_booking_wizard(self):
        self.ensure_one()
        action = self.import_action
        if action == "expense":
            return self._avea_open_expense_wizard()
        if action == "income":
            return self._avea_open_income_wizard()
        if action == "create":
            self._avea_create_statement_line()
            return self.wizard_id._avea_action_form(_("Bank reconciliation"))
        if action == "skip":
            self.match_state = "skipped"
            return self.wizard_id._avea_action_form(_("Bank reconciliation"))
        raise UserError(_("Choose what to do with this bank line."))

    def _avea_open_expense_wizard(self):
        self.ensure_one()
        amount = abs(self.amount)
        if self.currency_id.compare_amounts(amount, 0.0) <= 0:
            raise UserError(_("This line is not an outgoing payment."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Record expense"),
            "res_model": "avea.operational.expense.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "avea_till.view_avea_operational_expense_wizard_form"
            ).id,
            "target": "new",
            "context": {
                **self.env.context,
                "default_bank_reconcile_line_id": self.id,
                "default_expense_date": self.bank_date,
                "default_description": (self.description or _("Bank statement"))[:255],
                "default_document_ref": self.reference,
                "default_amount": amount,
                "default_paid_from_journal_id": self.wizard_id.journal_id.id,
                "default_company_id": self.wizard_id.company_id.id,
            },
        }

    def _avea_open_income_wizard(self):
        self.ensure_one()
        amount = abs(self.amount)
        if self.currency_id.compare_amounts(amount, 0.0) <= 0:
            raise UserError(_("This line is not money received."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Record income"),
            "res_model": "avea.operational.income.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "avea_till.view_avea_operational_income_wizard_form"
            ).id,
            "target": "new",
            "context": {
                **self.env.context,
                "default_bank_reconcile_line_id": self.id,
                "default_income_date": self.bank_date,
                "default_description": (self.description or _("Bank statement"))[:255],
                "default_document_ref": self.reference,
                "default_amount": amount,
                "default_received_in_journal_id": self.wizard_id.journal_id.id,
                "default_company_id": self.wizard_id.company_id.id,
            },
        }

    def _avea_after_booked(self, statement_line):
        self.ensure_one()
        self.write(
            {
                "statement_line_id": statement_line.id,
                "match_state": "matched",
                "match_confidence": 100.0,
                "match_hint": _("Recorded from Avea"),
            }
        )
        wizard = self.wizard_id
        wizard._avea_find_orphan_book_lines()
        return wizard._avea_action_form(_("Bank reconciliation"))

    def _avea_confirm_match(self):
        self.ensure_one()
        st_line = self.statement_line_id
        if not st_line:
            return
        details = dict(st_line.transaction_details or {})
        details["avea_bank_reconcile"] = {
            "bank_date": fields.Date.to_string(self.bank_date),
            "bank_reference": self.reference,
            "bank_description": self.description,
            "import_amount": self.amount,
        }
        st_line.sudo().write({"transaction_details": details})
        self.match_state = "matched"

    def _avea_create_statement_line(self):
        self.ensure_one()
        wizard = self.wizard_id
        journal = wizard.journal_id
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
                "source": wizard.source_format,
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


class AveaBankReconcileBookLine(models.TransientModel):
    _name = "avea.bank.reconcile.book.line"
    _description = "Book entry missing from bank statement"

    wizard_id = fields.Many2one(
        "avea.bank.reconcile.wizard",
        required=True,
        ondelete="cascade",
    )
    statement_line_id = fields.Many2one("account.bank.statement.line", required=True)
    book_date = fields.Date()
    label = fields.Char()
    amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
