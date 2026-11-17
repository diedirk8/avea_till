# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
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

    @api.depends("amount", "partner_id", "journal_id", "journal_id.type", "avea_cleared")
    def _compute_avea_is_supplier_payment(self):
        for line in self:
            money_out = (line.amount or 0.0) < 0.0
            cash_or_bank = line.journal_id.type in ("bank", "cash")
            line.avea_is_supplier_payment = bool(
                line.partner_id and money_out and cash_or_bank
            )
            line.avea_paid_amount = abs(line.amount or 0.0)
            line.avea_bank_match_label = (
                _("Matched") if line.avea_cleared else _("Not on a statement yet")
            )
            line.avea_can_delete_payment = bool(
                line.avea_is_supplier_payment and not line.avea_cleared
            )

    def _search_avea_is_supplier_payment(self, operator, value):
        positive = (operator == "=" and value) or (operator == "!=" and not value)
        domain = [
            ("partner_id", "!=", False),
            ("journal_id.type", "in", ("bank", "cash")),
            ("amount", "<", 0),
        ]
        if positive:
            return domain
        return ["!", "&", "&"] + domain

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

    def action_avea_delete_payment(self):
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
        env = self.env
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
        return env["account.bank.statement.line"].action_avea_open_payments()

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
