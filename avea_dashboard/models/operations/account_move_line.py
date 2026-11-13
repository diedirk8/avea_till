# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .account_account import AVEA_INCOME_TYPES


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    avea_signed_amount = fields.Monetary(
        string="Amount",
        compute="_compute_avea_signed_amount",
        currency_field="company_currency_id",
        help="Income earned or expense recorded on this line.",
    )

    @api.depends("balance", "account_id.account_type", "company_currency_id")
    def _compute_avea_signed_amount(self):
        for line in self:
            if line.account_id.account_type in AVEA_INCOME_TYPES:
                line.avea_signed_amount = -line.balance
            else:
                line.avea_signed_amount = line.balance
