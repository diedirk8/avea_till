# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools.misc import formatLang


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

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
