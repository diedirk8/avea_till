# -*- coding: utf-8 -*-
from collections.abc import Collection

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import formatLang


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    avea_cleared = fields.Boolean(
        string="Cleared on a bank statement",
        default=False,
        index=True,
        copy=False,
        help="Set when an Avea bank reconciliation has ticked this book entry off "
        "against a statement. Cleared lines are not offered again.",
    )
    avea_cleared_reconciliation_id = fields.Many2one(
        "avea.bank.reconciliation",
        string="Cleared on",
        copy=False,
        ondelete="set null",
    )
    avea_is_supplier_payment = fields.Boolean(
        string="Supplier payment",
        compute="_compute_avea_is_supplier_payment",
        search="_search_avea_is_supplier_payment",
    )
    avea_is_bill_payment = fields.Boolean(
        string="Bill payment",
        compute="_compute_avea_is_supplier_payment",
        search="_search_avea_is_bill_payment",
    )
    avea_payment_kind = fields.Selection(
        selection=[
            ("bill", "Bill payment"),
            ("other", "Other"),
        ],
        string="Type",
        compute="_compute_avea_is_supplier_payment",
    )
    avea_paid_amount = fields.Monetary(
        string="Paid",
        currency_field="currency_id",
        compute="_compute_avea_is_supplier_payment",
    )
    avea_bank_match_label = fields.Char(
        string="Bank match",
        compute="_compute_avea_is_supplier_payment",
    )
    avea_can_delete_payment = fields.Boolean(
        compute="_compute_avea_is_supplier_payment",
    )

    @api.depends(
        "amount",
        "partner_id",
        "journal_id",
        "journal_id.type",
        "avea_cleared",
        "move_id.line_ids.matched_debit_ids",
        "move_id.line_ids.matched_credit_ids",
    )
    def _compute_avea_is_supplier_payment(self):
        for line in self:
            money_out = (line.amount or 0.0) < 0.0
            cash_or_bank = line.journal_id.type in ("bank", "cash")
            line.avea_is_supplier_payment = bool(
                line.partner_id and money_out and cash_or_bank
            )
            line.avea_is_bill_payment = bool(line._avea_paid_vendor_bills())
            line.avea_payment_kind = "bill" if line.avea_is_bill_payment else "other"
            line.avea_paid_amount = abs(line.amount or 0.0)
            line.avea_bank_match_label = (
                _("Matched") if line.avea_cleared else _("Not on a statement yet")
            )
            line.avea_can_delete_payment = bool(
                line.avea_is_supplier_payment and not line.avea_cleared
            )

    def _search_avea_is_supplier_payment(self, operator, value):
        if operator in ("in", "not in"):
            values = (
                list(value)
                if isinstance(value, Collection) and not isinstance(value, (str, bytes))
                else [value]
            )
            truthy = any(values)
            positive = (operator == "in" and truthy) or (
                operator == "not in" and not truthy
            )
        elif operator in ("=", "!="):
            positive = (operator == "=" and value) or (operator == "!=" and not value)
        else:
            return NotImplemented
        domain = [
            ("partner_id", "!=", False),
            ("journal_id.type", "in", ("bank", "cash")),
            ("amount", "<", 0),
        ]
        if positive:
            return domain
        return ["!", "&", "&"] + domain

    def _search_avea_is_bill_payment(self, operator, value):
        if operator in ("in", "not in"):
            values = (
                list(value)
                if isinstance(value, Collection) and not isinstance(value, (str, bytes))
                else [value]
            )
            truthy = any(values)
            positive = (operator == "in" and truthy) or (
                operator == "not in" and not truthy
            )
        elif operator in ("=", "!="):
            positive = (operator == "=" and value) or (operator == "!=" and not value)
        else:
            return NotImplemented
        ids = self._avea_bill_payment_ids()
        if positive:
            return [("id", "in", ids)]
        return [("id", "not in", ids)]

    @api.model
    def _avea_bill_payment_ids(self):
        bill_amls = self.env["account.move.line"].sudo().search(
            [
                ("move_id.move_type", "in", ("in_invoice", "in_refund")),
                ("parent_state", "=", "posted"),
            ]
        )
        counterparts = (
            bill_amls.mapped("matched_debit_ids.debit_move_id")
            | bill_amls.mapped("matched_debit_ids.credit_move_id")
            | bill_amls.mapped("matched_credit_ids.debit_move_id")
            | bill_amls.mapped("matched_credit_ids.credit_move_id")
        ) - bill_amls
        from_aml = counterparts.mapped("statement_line_id")
        from_move = self.sudo().search([("move_id", "in", counterparts.move_id.ids)])
        return list(set(from_aml.ids) | set(from_move.ids))

    def get_formview_id(self, access_uid=None):
        if self.env.context.get("avea_supplier_workspace"):
            return self.env.ref("avea_till.view_avea_supplier_payment_form").id
        return super().get_formview_id(access_uid=access_uid)

    def get_formview_action(self, access_uid=None):
        action = super().get_formview_action(access_uid=access_uid)
        if self.env.context.get("avea_supplier_workspace"):
            view_id = self.env.ref("avea_till.view_avea_supplier_payment_form").id
            action["views"] = [(view_id, "form")]
            ctx = dict(action.get("context") or {})
            ctx["avea_supplier_workspace"] = True
            action["context"] = ctx
        return action

    def action_avea_new_payment(self):
        return self.env["ir.actions.act_window"]._for_xml_id(
            "avea_till.action_avea_pay_bills_wizard"
        )

    def action_avea_open_payments(self):
        return self.env["ir.actions.act_window"]._for_xml_id(
            "avea_till.action_avea_supplier_payments"
        )

    def _avea_paid_vendor_bills(self):
        self.ensure_one()
        amls = self.move_id.line_ids
        counterparts = (
            amls.matched_debit_ids.debit_move_id
            | amls.matched_debit_ids.credit_move_id
            | amls.matched_credit_ids.debit_move_id
            | amls.matched_credit_ids.credit_move_id
        ) - amls
        return counterparts.move_id.filtered(
            lambda move: move.move_type in ("in_invoice", "in_refund")
        )

    def _avea_detach_from_bank_recon(self):
        """Drop in-progress bank-recon links so this book payment can be deleted."""
        self.ensure_one()
        self.env["avea.bank.reconcile.book.line"].sudo().search(
            [("statement_line_id", "=", self.id)]
        ).unlink()
        ReconLine = self.env["avea.bank.reconcile.line"].sudo()
        pointed = ReconLine.search([("statement_line_id", "=", self.id)])
        if pointed:
            pointed.write(
                {
                    "statement_line_id": False,
                    "match_locked": False,
                    "match_confidence": 0.0,
                    "match_hint": False,
                    "match_state": "unmatched",
                }
            )
        candidates = ReconLine.search(
            [("candidate_statement_line_ids", "in", [self.id])]
        )
        for rec in candidates:
            rec.write(
                {"candidate_statement_line_ids": [Command.unlink(self.id)]}
            )

    def _avea_unlink_supplier_payment(self):
        """Unreconcile and delete this book payment. Leaves the linked bills unpaid."""
        self.ensure_one()
        if self.avea_cleared:
            raise UserError(
                _(
                    "This payment is already matched on a bank statement. "
                    "Unmatch it in bank recon first, then delete it."
                )
            )
        if not self.avea_is_supplier_payment:
            raise UserError(_("This is not a supplier payment."))
        bills = self._avea_paid_vendor_bills()
        partner = self.partner_id
        self._avea_detach_from_bank_recon()
        self.sudo().line_ids.remove_move_reconcile()
        move = self.move_id
        if move.state == "posted":
            move.sudo().button_draft()
        self.sudo().with_context(force_delete=True).unlink()
        for bill in bills:
            bill.invalidate_recordset(["amount_residual", "payment_state"])
            receive = bill.avea_linked_receive_id
            if (
                receive
                and receive.mark_as_paid
                and bill.currency_id
                and not bill.currency_id.is_zero(bill.amount_residual)
            ):
                receive.sudo().write({"mark_as_paid": False})
        if partner:
            partner.invalidate_recordset()

    def action_avea_delete_payment(self):
        self.ensure_one()
        self._avea_unlink_supplier_payment()
        return self.env["account.bank.statement.line"].action_avea_open_payments()

    def action_avea_open_payment_supplier(self):
        self.ensure_one()
        if not self.partner_id:
            return False
        return self.partner_id.action_avea_open_supplier()

    def avea_reconcile_display_name(self):
        """Human-readable label for bank reconciliation (date, partner, reference, amount)."""
        self.ensure_one()
        date = self.date or (self.move_id.date if self.move_id else False)
        date_s = fields.Date.to_string(date) if date else "?"
        partner = self.partner_id.display_name if self.partner_id else ""
        ref = (self.payment_ref or self.move_id.ref or self.move_id.name or "").strip()
        currency = self.currency_id or self.company_id.currency_id
        amount_s = formatLang(self.env, self.amount, currency_obj=currency)
        parts = [date_s]
        if partner:
            parts.append(partner)
        if ref:
            parts.append(ref)
        parts.append(amount_s)
        return " · ".join(parts)

    def name_get(self):
        if self.env.context.get("avea_bank_reconcile_labels"):
            return [(line.id, line.avea_reconcile_display_name()) for line in self]
        return super().name_get()
