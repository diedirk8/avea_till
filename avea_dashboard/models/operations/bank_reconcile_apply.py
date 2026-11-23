# -*- coding: utf-8 -*-
import re
from datetime import datetime, timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AveaBankReconcileApply(models.TransientModel):
    """Match a statement line to invoices, split it, or transfer it.

    Same three actions as the Xero and QuickBooks bank screens, on top of
    Avea's existing match-to-book-entry and Book expense/income flows.
    """

    _name = "avea.bank.reconcile.apply"
    _description = "Allocate a bank statement line"

    reconcile_line_id = fields.Many2one(
        "avea.bank.reconcile.line",
        required=True,
        ondelete="cascade",
    )
    mode = fields.Selection(
        selection=[
            ("match", "Match invoice or bill"),
            ("settlement", "Card settlement"),
            ("split", "Split across accounts"),
            ("transfer", "Transfer to another account"),
        ],
        default="match",
        required=True,
    )
    company_id = fields.Many2one(related="reconcile_line_id.company_id")
    currency_id = fields.Many2one(related="reconcile_line_id.currency_id")
    journal_id = fields.Many2one(related="reconcile_line_id.journal_id")
    amount = fields.Monetary(related="reconcile_line_id.amount")
    description = fields.Char(related="reconcile_line_id.description")
    available_move_ids = fields.Many2many(
        "account.move",
        compute="_compute_available_move_ids",
    )
    move_ids = fields.Many2many(
        "account.move",
        string="Invoices and bills",
        domain="[('id', 'in', available_move_ids)]",
    )
    open_amount = fields.Monetary(
        string="Open on the documents",
        compute="_compute_open_amount",
        currency_field="currency_id",
    )
    split_line_ids = fields.One2many(
        "avea.bank.reconcile.split.line",
        "apply_id",
        string="Accounts",
    )
    split_total = fields.Monetary(
        compute="_compute_split_total",
        currency_field="currency_id",
    )
    transfer_journal_id = fields.Many2one(
        "account.journal",
        string="Other account",
        domain="[('id', 'in', available_transfer_journal_ids)]",
    )
    available_transfer_journal_ids = fields.Many2many(
        "account.journal",
        compute="_compute_available_transfer_journal_ids",
    )
    settlement_gross = fields.Monetary(
        string="Card sales before the fee",
        currency_field="currency_id",
        help="The machine total for this Capitec or Yoco batch, before their fee and any capital repayment.",
    )
    settlement_capital = fields.Monetary(
        string="Yoco capital repaid",
        currency_field="currency_id",
        help="Taken off the Yoco payout. This is a loan repayment, not a card fee and not a sale.",
    )
    settlement_fee = fields.Monetary(
        string="Card fee incl. VAT",
        compute="_compute_settlement_fee",
        currency_field="currency_id",
    )
    settlement_hint = fields.Char(compute="_compute_settlement_fee")
    fee_account_id = fields.Many2one(
        "account.account",
        string="Fee account",
        domain=(
            "[('company_ids', 'in', company_id), "
            "('account_type', 'in', ('expense', 'expense_other', 'expense_direct_cost'))]"
        ),
    )
    capital_account_id = fields.Many2one(
        "account.account",
        string="Capital / loan account",
        domain=(
            "[('company_ids', 'in', company_id), "
            "('account_type', 'in', ('liability_current', 'liability_non_current'))]"
        ),
    )
    paid_document_hint = fields.Char(compute="_compute_open_amount")

    @api.depends(
        "reconcile_line_id",
        "reconcile_line_id.amount",
        "reconcile_line_id.description",
        "reconcile_line_id.reference",
        "company_id",
    )
    def _compute_available_move_ids(self):
        for wizard in self:
            line = wizard.reconcile_line_id
            if not line or not wizard.company_id:
                wizard.available_move_ids = False
                continue
            if wizard.currency_id.compare_amounts(line.amount, 0.0) > 0:
                move_types = ("out_invoice", "in_refund")
            elif wizard.currency_id.compare_amounts(line.amount, 0.0) < 0:
                move_types = ("in_invoice", "out_refund")
            else:
                wizard.available_move_ids = False
                continue
            open_moves = self.env["account.move"].search(
                [
                    ("company_id", "=", wizard.company_id.id),
                    ("state", "=", "posted"),
                    ("move_type", "in", move_types),
                    ("payment_state", "in", ("not_paid", "partial")),
                    ("amount_residual", "!=", 0),
                ]
            )
            wizard.available_move_ids = open_moves | wizard._avea_paid_moves_with_payment(
                line, move_types
            )

    def _avea_paid_moves_with_payment(self, line, move_types):
        """Already-paid bills/invoices whose existing bank payment can be linked."""
        if not line.reconciliation_id:
            return self.env["account.move"]
        bills = self.env["account.move"]
        for st_line in line.reconciliation_id._avea_uncleared_book_lines():
            if st_line.journal_id != line.journal_id:
                continue
            close = line._avea_amounts_near(
                st_line.amount, 1.00
            ) or line._avea_amounts_equal(st_line.amount)
            if not close and not line._avea_name_match(st_line)[0]:
                continue
            paid = st_line._avea_paid_vendor_bills().filtered(
                lambda move: move.move_type in move_types
            )
            if paid:
                bills |= paid
        return bills

    @api.depends(
        "move_ids.amount_residual",
        "move_ids.amount_total",
        "move_ids.payment_state",
        "currency_id",
    )
    def _compute_open_amount(self):
        for wizard in self:
            moves = wizard.move_ids
            paid = moves.filtered(
                lambda move: move.payment_state in ("paid", "in_payment")
                and move.currency_id.is_zero(move.amount_residual)
            )
            wizard.open_amount = sum(moves.mapped("amount_residual"))
            if paid and paid == moves:
                wizard.paid_document_hint = _(
                    "This document is already paid. Apply links the existing "
                    "supplier payment — it will not pay it again."
                )
                wizard.open_amount = sum(paid.mapped("amount_total"))
            elif paid:
                wizard.paid_document_hint = _(
                    "Choose either open documents or already-paid ones, not both."
                )
            else:
                wizard.paid_document_hint = False

    @api.depends("split_line_ids.amount", "currency_id")
    def _compute_split_total(self):
        for wizard in self:
            wizard.split_total = sum(wizard.split_line_ids.mapped("amount"))

    @api.depends("company_id", "journal_id")
    def _compute_available_transfer_journal_ids(self):
        for wizard in self:
            company = wizard.company_id
            journals = company._avea_transfer_journals() if company else self.env["account.journal"]
            wizard.available_transfer_journal_ids = journals - wizard.journal_id

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        line_id = values.get("reconcile_line_id") or self.env.context.get(
            "default_reconcile_line_id"
        )
        line = self.env["avea.bank.reconcile.line"].browse(line_id)
        if not line:
            return values
        description = (line.description or "").lower()
        if "card settlement" in description and "mode" in (fields_list or ["mode"]):
            values["mode"] = "settlement"
        payout = line.merchant_payout_id
        if payout:
            if "settlement_gross" in (fields_list or ["settlement_gross"]):
                values["settlement_gross"] = payout.gross_amount
            if "settlement_capital" in (fields_list or ["settlement_capital"]):
                values["settlement_capital"] = payout.capital_amount
        else:
            gross, _hint = self._avea_suggest_settlement_gross(line)
            if gross and "settlement_gross" in (fields_list or ["settlement_gross"]):
                values["settlement_gross"] = gross
        fee_account = self._avea_fee_account(line.company_id)
        if fee_account and "fee_account_id" in (fields_list or ["fee_account_id"]):
            values["fee_account_id"] = fee_account.id
        capital_account = self._avea_capital_account(line.company_id)
        if capital_account and "capital_account_id" in (fields_list or ["capital_account_id"]):
            values["capital_account_id"] = capital_account.id
        if "move_ids" not in (fields_list or ["move_ids"]):
            return values
        currency = line.currency_id or self.env.company.currency_id
        target = abs(line.amount)
        wizard = self.new({"reconcile_line_id": line.id, "company_id": line.company_id.id})

        def _move_match_amount(move):
            if move.currency_id.is_zero(move.amount_residual):
                return move.amount_total
            return abs(move.amount_residual)

        exact = wizard.available_move_ids.filtered(
            lambda move: currency.compare_amounts(_move_match_amount(move), target) == 0
        )
        blob = " ".join(filter(None, [line.description or "", line.reference or ""])).lower()
        named = exact.filtered(
            lambda move: move.partner_id.name and move.partner_id.name.lower() in blob
        )
        if len(named) == 1:
            exact = named
        if len(exact) == 1:
            values["move_ids"] = [Command.set(exact.ids)]
        return values

    @api.depends(
        "settlement_gross",
        "settlement_capital",
        "amount",
        "currency_id",
        "reconcile_line_id.description",
        "reconcile_line_id.merchant_payout_id",
    )
    def _compute_settlement_fee(self):
        for wizard in self:
            currency = wizard.currency_id or wizard.env.company.currency_id
            net = wizard.amount or 0.0
            gross = wizard.settlement_gross or 0.0
            capital = wizard.settlement_capital or 0.0
            fee = (
                currency.round(gross - net - capital)
                if currency.compare_amounts(gross, 0.0) > 0
                else 0.0
            )
            wizard.settlement_fee = fee
            payout = wizard.reconcile_line_id.merchant_payout_id
            if payout:
                parts = [
                    _(
                        "The machine file shows card sales of %(gross)s. "
                        "The bank received %(net)s.",
                        gross=currency.format(payout.gross_amount),
                        net=currency.format(net),
                    )
                ]
                if currency.compare_amounts(payout.fee_amount, 0.0) > 0:
                    parts.append(
                        _("Fee incl. VAT is %(fee)s.", fee=currency.format(payout.fee_amount))
                    )
                if currency.compare_amounts(payout.capital_amount, 0.0) > 0:
                    parts.append(
                        _(
                            "Yoco also took %(capital)s as a capital repayment — "
                            "that is a loan, not a fee and not a sale.",
                            capital=currency.format(payout.capital_amount),
                        )
                    )
                wizard.settlement_hint = " ".join(parts)
                continue
            _gross, hint = wizard._avea_suggest_settlement_gross(wizard.reconcile_line_id)
            if currency.compare_amounts(fee, 0.0) > 0 and currency.compare_amounts(gross, 0.0) > 0:
                rate = fee / gross * 100.0
                hint = _(
                    "%(hint)s Fee on this batch is %(rate).2f%%.",
                    hint=hint or "",
                    rate=rate,
                ).strip()
            wizard.settlement_hint = hint or False

    def action_apply(self):
        self.ensure_one()
        line = self.reconcile_line_id
        if line.match_state in ("matched", "imported"):
            raise UserError(_("This statement line is already matched."))
        if self.mode == "match":
            statement_line = self._avea_apply_match()
            hint = (
                _("Linked to the existing supplier payment")
                if statement_line
                and self.move_ids.filtered(
                    lambda move: move.payment_state in ("paid", "in_payment")
                    and move.currency_id.is_zero(move.amount_residual)
                )
                else None
            )
            return line._avea_after_booked(statement_line, hint=hint)
        elif self.mode == "settlement":
            statement_line = self._avea_apply_settlement()
        elif self.mode == "split":
            statement_line = self._avea_apply_split()
        elif self.mode == "transfer":
            statement_line = self._avea_apply_transfer()
        else:
            raise UserError(_("Choose how to allocate this bank line."))
        return line._avea_after_booked(statement_line)

    def _avea_apply_match(self):
        self.ensure_one()
        line = self.reconcile_line_id
        moves = self.move_ids
        if not moves:
            raise UserError(_("Choose the invoice or bill this bank line pays."))
        if any(move not in self.available_move_ids for move in moves):
            raise UserError(_("Choose an invoice or bill for this company."))
        paid = moves.filtered(
            lambda move: move.payment_state in ("paid", "in_payment")
            and move.currency_id.is_zero(move.amount_residual)
        )
        open_moves = moves - paid
        if paid and open_moves:
            raise UserError(
                _("Choose either open documents or already-paid ones, not both.")
            )
        if paid:
            return self._avea_link_existing_payment(paid)
        currency = self.currency_id
        bank_amount = abs(line.amount)
        residuals = [(move, abs(move.amount_residual)) for move in moves]
        open_total = sum(residual for _move, residual in residuals)
        if len(moves) > 1 and currency.compare_amounts(open_total, bank_amount) != 0:
            raise UserError(
                _(
                    "The open amounts must add up to this bank line, "
                    "or match a single invoice and leave the rest open."
                )
            )
        if len(moves) == 1 and currency.compare_amounts(open_total, bank_amount) < 0:
            raise UserError(
                _("This document is smaller than the bank line. Split the difference or pick more documents.")
            )
        accounts = self.env["account.account"]
        for move in moves:
            accounts |= self._avea_document_account(move)
        if len(accounts) != 1:
            raise UserError(
                _("These documents do not share one receivable or payable account.")
            )
        account = accounts
        partner = moves.mapped("partner_id")[:1]
        payment_ref = line.description or line.reference or moves[0].name
        statement_line = self._avea_create_statement_line(
            amount=line.amount,
            payment_ref=payment_ref[:255],
            counterpart=account,
            partner=partner,
        )
        document_lines = self.env["account.move.line"]
        for move in moves:
            document_lines |= move.line_ids.filtered(
                lambda aml, account=account: aml.account_id == account and not aml.reconciled
            )
        statement_lines = statement_line.move_id.line_ids.filtered(
            lambda aml, account=account: aml.account_id == account and not aml.reconciled
        )
        to_reconcile = document_lines | statement_lines
        if len(to_reconcile) < 2:
            raise UserError(_("Could not match this bank line to the document."))
        to_reconcile.sudo().reconcile()
        return statement_line

    def _avea_link_existing_payment(self, moves):
        """Tick the bank line off against the payment that already paid these bills."""
        self.ensure_one()
        line = self.reconcile_line_id
        mixin = self.env["avea.stock.mixin"]
        payments = self.env["account.bank.statement.line"]
        for move in moves:
            payments |= mixin._avea_statement_lines_for_bill(move).filtered(
                lambda st_line: not st_line.avea_cleared
                and st_line.journal_id == line.journal_id
            )
        if not payments:
            raise UserError(
                _(
                    "This document is already paid, but Avea cannot find the "
                    "bank payment to link. Do not record it as an expense."
                )
            )
        st_line = payments.sorted(lambda payment: abs(payment.amount - line.amount))[:1]
        if st_line.avea_cleared and (
            st_line.avea_cleared_reconciliation_id != line.reconciliation_id
        ):
            raise UserError(_("That book entry is already cleared on another statement."))
        duplicate = line.reconciliation_id.line_ids.filtered(
            lambda other: other.id != line.id and other.statement_line_id == st_line
        )
        if duplicate:
            raise UserError(_("That book entry is already linked to another statement line."))
        line.statement_line_id = st_line.id
        if not line._avea_amounts_equal(st_line.amount):
            if not line._avea_amounts_near(st_line.amount, 1.00):
                raise UserError(
                    _("The existing payment amount is too different from this bank line.")
                )
            line._avea_apply_rounding_writeoff(st_line)
        return st_line

    def _avea_document_account(self, move):
        if move.move_type in ("out_invoice", "out_refund"):
            account = move.partner_id.with_company(self.company_id).property_account_receivable_id
        else:
            account = move.partner_id.with_company(self.company_id).property_account_payable_id
        if not account:
            raise UserError(_("This contact has no receivable or payable account."))
        return account

    def _avea_trading_date(self):
        self.ensure_one()
        text = self.reconcile_line_id.description or ""
        match = re.search(r"sales\s+(\d{1,2}\s+\w{3}\s+\d{4})", text, re.IGNORECASE)
        if not match:
            return False
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(match.group(1), fmt).date()
            except ValueError:
                continue
        return False

    def _avea_card_methods(self, provider):
        methods = self.env["pos.payment.method"].sudo().search([])
        cards = methods.filtered(
            lambda method: "card" in (method.name or "").lower()
            or (
                hasattr(method, "_avea_tender_kind")
                and method._avea_tender_kind() == "card"
            )
        )
        if provider:
            named = cards.filtered(lambda method: provider in (method.name or "").lower())
            if named:
                return named
        return cards

    @api.model
    def _avea_fee_account(self, company):
        return self.env["account.account"].sudo().search(
            [
                ("company_ids", "in", company.id),
                ("account_type", "in", ("expense", "expense_other", "expense_direct_cost")),
                "|",
                "|",
                ("name", "ilike", "bank charge"),
                ("name", "ilike", "service fee"),
                ("name", "ilike", "card fee"),
            ],
            limit=1,
        )

    @api.model
    def _avea_capital_account(self, company):
        Account = self.env["account.account"].sudo()
        named = Account.search(
            [
                ("company_ids", "in", company.id),
                ("account_type", "in", ("liability_current", "liability_non_current")),
                ("name", "ilike", "loan"),
            ],
            limit=1,
        )
        if named:
            return named
        return Account.search(
            [
                ("company_ids", "in", company.id),
                ("code", "=", "200080"),
            ],
            limit=1,
        )

    @api.model
    def _avea_suggest_settlement_gross(self, line):
        if not line or "card settlement" not in (line.description or "").lower():
            return 0.0, False
        if line.merchant_payout_id:
            return line.merchant_payout_id.gross_amount, False
        description = line.description or ""
        lowered = description.lower()
        provider = "capitec" if "capitec" in lowered else "yoco" if "yoco" in lowered else ""
        trading = False
        match = re.search(r"sales\s+(\d{1,2}\s+\w{3}\s+\d{4})", description, re.IGNORECASE)
        if match:
            for fmt in ("%d %b %Y", "%d %B %Y"):
                try:
                    trading = datetime.strptime(match.group(1), fmt).date()
                    break
                except ValueError:
                    continue
        if not trading:
            return 0.0, _("Type the card-machine total for this batch, before the fee.")
        return self._avea_settlement_gross_for(line, provider, trading)

    @api.model
    def _avea_settlement_gross_for(self, line, provider, trading):
        methods = self._avea_card_methods(provider)
        if not methods:
            return 0.0, _(
                "No card payment method was found on the till. Type the batch total from Capitec or Yoco."
            )
        start = datetime.combine(trading, datetime.min.time())
        payments = self.env["pos.payment"].sudo().search(
            [
                ("payment_method_id", "in", methods.ids),
                ("payment_date", ">=", start),
                ("payment_date", "<", start + timedelta(days=1)),
            ]
        )
        gross = sum(payments.mapped("amount"))
        currency = line.currency_id or self.env.company.currency_id
        net = line.amount or 0.0
        hint = _(
            "Till card sales on %(day)s were %(gross)s. This deposit is only the %(provider)s batch, "
            "and their fee is already taken off. Type that batch total if it is not the whole day's cards.",
            day=trading.strftime("%d %b %Y").lstrip("0"),
            gross=gross,
            provider=provider.title() or _("card"),
        )
        if currency.compare_amounts(gross, net) > 0 and gross:
            rate = (gross - net) / gross
            if 0.005 <= rate <= 0.03:
                return gross, _(
                    "This deposit matches the till card sales on %(day)s after a %(rate).2f%% fee.",
                    day=trading.strftime("%d %b %Y").lstrip("0"),
                    rate=rate * 100.0,
                )
        return 0.0, hint

    def _avea_apply_settlement(self):
        self.ensure_one()
        line = self.reconcile_line_id
        currency = self.currency_id
        net = line.amount
        if currency.compare_amounts(net, 0.0) <= 0:
            raise UserError(_("A card settlement on the statement is money in."))
        gross = self.settlement_gross
        capital = self.settlement_capital or 0.0
        if currency.compare_amounts(capital, 0.0) < 0:
            raise UserError(_("Yoco capital repaid cannot be negative."))
        if currency.compare_amounts(gross, net + capital) < 0:
            raise UserError(
                _(
                    "Card sales must cover the amount the bank received plus any "
                    "Yoco capital repayment."
                )
            )
        fee = currency.round(gross - net - capital)
        if currency.compare_amounts(fee, 0.0) > 0 and not self.fee_account_id:
            raise UserError(_("Choose the expense account for the card fee."))
        if currency.compare_amounts(capital, 0.0) > 0 and not self.capital_account_id:
            raise UserError(
                _(
                    "Yoco took a capital repayment off this payout. Choose the loan "
                    "account so it is not booked as a card fee."
                )
            )
        provider = "capitec" if "capitec" in (line.description or "").lower() else "yoco" if "yoco" in (line.description or "").lower() else ""
        methods = self._avea_card_methods(provider)
        outstanding = methods.mapped("outstanding_account_id")[:1]
        if not outstanding:
            raise UserError(
                _(
                    "The card payment method needs an outstanding receipts account. "
                    "Ask your accountant to set it on the card payment method."
                )
            )
        suspense = line.journal_id.suspense_account_id
        if not suspense:
            raise UserError(_("This bank journal needs a suspense account."))
        statement_line = self._avea_create_statement_line(
            amount=net,
            payment_ref=(line.description or _("Card settlement"))[:255],
            counterpart=suspense,
            partner=self.env["res.partner"],
        )
        move = statement_line.move_id
        move.button_draft()
        liquidity, _suspense_lines, _others = statement_line._seek_for_lines()
        commands = [Command.clear()]
        for liq in liquidity:
            commands.append(
                Command.create(
                    {
                        "name": liq.name,
                        "account_id": liq.account_id.id,
                        "partner_id": liq.partner_id.id,
                        "currency_id": liq.currency_id.id,
                        "amount_currency": liq.amount_currency,
                        "debit": liq.debit,
                        "credit": liq.credit,
                    }
                )
            )
        if currency.compare_amounts(fee, 0.0) > 0:
            commands.append(
                Command.create(
                    {
                        "name": _("Card fee"),
                        "account_id": self.fee_account_id.id,
                        "debit": fee,
                        "credit": 0.0,
                        "amount_currency": fee,
                        "currency_id": currency.id,
                    }
                )
            )
        if currency.compare_amounts(capital, 0.0) > 0:
            commands.append(
                Command.create(
                    {
                        "name": _("Yoco capital repayment"),
                        "account_id": self.capital_account_id.id,
                        "debit": capital,
                        "credit": 0.0,
                        "amount_currency": capital,
                        "currency_id": currency.id,
                    }
                )
            )
        commands.append(
            Command.create(
                {
                    "name": line.description or _("Card sales"),
                    "account_id": outstanding.id,
                    "debit": 0.0,
                    "credit": gross,
                    "amount_currency": -gross,
                    "currency_id": currency.id,
                }
            )
        )
        move.with_context(skip_account_move_synchronization=True).write({"line_ids": commands})
        move.action_post()
        return statement_line

    def _avea_apply_split(self):
        self.ensure_one()
        line = self.reconcile_line_id
        parts = self.split_line_ids
        if len(parts) < 2:
            raise UserError(_("Add at least two accounts to split this bank line."))
        currency = self.currency_id
        total = currency.round(sum(parts.mapped("amount")))
        if currency.compare_amounts(total, abs(line.amount)) != 0:
            raise UserError(
                _("The split amounts must add up to the bank line (%(amount)s).", amount=abs(line.amount))
            )
        suspense = line.journal_id.suspense_account_id
        if not suspense:
            raise UserError(_("This bank journal needs a suspense account before a split can be posted."))
        statement_line = self._avea_create_statement_line(
            amount=line.amount,
            payment_ref=(line.description or line.reference or _("Bank statement"))[:255],
            counterpart=suspense,
            partner=self.env["res.partner"],
        )
        self._avea_replace_suspense_with_split(statement_line, parts)
        return statement_line

    def _avea_replace_suspense_with_split(self, statement_line, parts):
        move = statement_line.move_id
        move.button_draft()
        liquidity, suspense_lines, others = statement_line._seek_for_lines()
        if not liquidity:
            raise UserError(_("The bank line has no bank account entry to split."))
        commands = [Command.clear()]
        for liq in liquidity:
            commands.append(
                Command.create(
                    {
                        "name": liq.name,
                        "account_id": liq.account_id.id,
                        "partner_id": liq.partner_id.id,
                        "currency_id": liq.currency_id.id,
                        "amount_currency": liq.amount_currency,
                        "debit": liq.debit,
                        "credit": liq.credit,
                    }
                )
            )
        bank_out = self.currency_id.compare_amounts(statement_line.amount, 0.0) < 0
        currency = self.currency_id
        for part in parts:
            portion = currency.round(part.amount)
            if bank_out:
                debit, credit = portion, 0.0
                amount_currency = portion
            else:
                debit, credit = 0.0, portion
                amount_currency = -portion
            commands.append(
                Command.create(
                    {
                        "name": part.name or part.account_id.display_name,
                        "account_id": part.account_id.id,
                        "debit": debit,
                        "credit": credit,
                        "amount_currency": amount_currency,
                        "currency_id": currency.id,
                    }
                )
            )
        move.with_context(skip_account_move_synchronization=True).write({"line_ids": commands})
        move.action_post()

    def _avea_apply_transfer(self):
        self.ensure_one()
        line = self.reconcile_line_id
        other = self.transfer_journal_id
        if not other:
            raise UserError(_("Choose the other bank or cash account."))
        if other == line.journal_id:
            raise UserError(_("Choose a different account from this bank line."))
        amount = abs(line.amount)
        if self.currency_id.compare_amounts(line.amount, 0.0) < 0:
            from_journal, to_journal = line.journal_id, other
        else:
            from_journal, to_journal = other, line.journal_id
        transfer = self.env["avea.money.transfer.wizard"].create(
            {
                "company_id": self.company_id.id,
                "currency_id": self.currency_id.id,
                "from_journal_id": from_journal.id,
                "to_journal_id": to_journal.id,
                "amount": amount,
                "transfer_date": line.bank_date,
                "reference": (line.description or line.reference or _("Bank transfer"))[:255],
            }
        )
        transfer._avea_check_transfer()
        moves = transfer._avea_post_transfer()
        statement_lines = moves.mapped("statement_line_id").filtered(
            lambda st_line: st_line.journal_id == line.journal_id
            and self.currency_id.compare_amounts(st_line.amount, line.amount) == 0
        )
        if not statement_lines:
            raise UserError(_("The transfer did not create a line on this bank account."))
        return statement_lines[:1]

    def _avea_create_statement_line(self, amount, payment_ref, counterpart, partner):
        self.ensure_one()
        line = self.reconcile_line_id
        return (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(
                {
                    "journal_id": line.journal_id.id,
                    "amount": amount,
                    "date": line.bank_date,
                    "payment_ref": payment_ref,
                    "partner_id": partner.id if partner else False,
                    "counterpart_account_id": counterpart.id,
                }
            )
        )


class AveaBankReconcileSplitLine(models.TransientModel):
    _name = "avea.bank.reconcile.split.line"
    _description = "Bank statement split line"

    apply_id = fields.Many2one(
        "avea.bank.reconcile.apply",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(related="apply_id.company_id")
    currency_id = fields.Many2one(related="apply_id.currency_id")
    account_id = fields.Many2one(
        "account.account",
        string="Account",
        required=True,
        domain=(
            "[('company_ids', 'in', company_id), "
            "('account_type', 'not in', "
            "('asset_receivable', 'liability_payable', 'asset_cash', 'liability_credit_card'))]"
        ),
    )
    name = fields.Char(string="Description")
    amount = fields.Monetary(required=True, currency_field="currency_id")

    @api.constrains("amount")
    def _check_amount(self):
        for line in self:
            if line.currency_id.compare_amounts(line.amount, 0.0) <= 0:
                raise ValidationError(_("Each split amount must be greater than zero."))
