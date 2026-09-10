from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class ResPartner(models.Model):
    _inherit = "res.partner"

    avea_credit_ledger_entry_ids = fields.One2many(
        "avea.credit.ledger.entry",
        "partner_id",
        string="Store Credit Ledger Entries",
    )
    avea_credit_currency_id = fields.Many2one(
        "res.currency",
        string="Store Credit Currency",
        compute="_compute_avea_credit_balance",
        store=True,
    )
    avea_credit_balance = fields.Monetary(
        string="Store Credit Balance",
        compute="_compute_avea_credit_balance",
        store=True,
        currency_field="avea_credit_currency_id",
        help="Current store credit balance derived from confirmed ledger entries.",
    )
    avea_customer_account_balance = fields.Monetary(
        string="Customer Account Balance",
        compute="_compute_avea_customer_account_balance",
        currency_field="currency_id",
        help="Outstanding receivable balance for POS receipts without accounting access.",
    )

    @api.depends(
        "avea_credit_ledger_entry_ids.amount",
        "avea_credit_ledger_entry_ids.reason_id",
        "avea_credit_ledger_entry_ids.state",
        "avea_credit_ledger_entry_ids.currency_id",
        "company_id",
    )
    def _compute_avea_credit_balance(self):
        for partner in self:
            balance = 0.0
            currency = partner.company_id.currency_id or self.env.company.currency_id
            for entry in partner.avea_credit_ledger_entry_ids:
                if entry.state != "posted":
                    continue
                balance += entry._signed_amount()
                if entry.currency_id:
                    currency = entry.currency_id
            partner.avea_credit_balance = balance
            partner.avea_credit_currency_id = currency

    def _compute_avea_customer_account_balance(self):
        credit_by_id = {partner.id: partner.credit for partner in self.sudo()}
        for partner in self:
            partner.avea_customer_account_balance = credit_by_id.get(partner.id, 0.0)

    def _avea_credit_ensure_customer(self):
        partners = self.filtered(lambda partner: not partner.customer_rank)
        if partners:
            partners.write({"customer_rank": 1})
        return self

    def action_open_store_credit(self):
        self.ensure_one()
        return self.env["avea.credit.ledger.entry"].action_open_ledger(
            partner_id=self.id,
        )

    def action_issue_store_credit(self):
        self.ensure_one()
        return self.env["avea.credit.issue.wizard"].action_open_wizard(
            partner_id=self.id,
        )

    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        extra_fields = ["avea_customer_account_balance"]
        if config.avea_credit_enabled:
            extra_fields.extend(
                [
                    "avea_credit_balance",
                    "avea_credit_currency_id",
                ]
            )
        return fields_list + extra_fields

    @api.model
    def pos_get_store_credit_balance(self, partner_id):
        """Return the live posted Store Credit balance for the POS payment screen.

        POS IndexedDB can keep a stale 0 after another cashier refunds or issues
        credit, which greys out Store Credit for this cashier.
        """
        if not self.env.su and not self.env.user.has_group(
            "point_of_sale.group_pos_user"
        ):
            raise AccessError(
                _("You do not have permission to read store credit balances in POS.")
            )
        partner = self.browse(partner_id).exists()
        if not partner:
            return {"balance": 0.0, "currency_id": False}
        partner.invalidate_recordset(["avea_credit_balance", "avea_credit_currency_id"])
        currency = partner.avea_credit_currency_id
        return {
            "balance": partner.avea_credit_balance,
            "currency_id": currency.id if currency else False,
        }
