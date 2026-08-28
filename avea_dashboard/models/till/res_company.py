from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    avea_cash_safe_journal_id = fields.Many2one(
        "account.journal",
        string="Cash Safe / Company Cash Journal",
        check_company=True,
        domain=(
            "[('type', '=', 'cash'), "
            "('company_id', '=', id), "
            "('name', 'not ilike', 'store credit')]"
        ),
        help="Existing cash journal for physical cash held outside POS tills. "
        "Cash Up posts till cash to this Safe destination. "
        "Do not select a till cash journal.",
    )

    def _avea_pos_till_cash_journal_ids(self):
        self.ensure_one()
        return (
            self.env["pos.payment.method"]
            .sudo()
            .search(
                [
                    ("company_id", "=", self.id),
                    ("journal_id.type", "=", "cash"),
                ]
            )
            .journal_id.ids
        )

    def _avea_cash_safe_journal_domain(self):
        """Allowed destination journals for this company (admin dropdown / validation)."""
        company = self[:1]
        domain = [
            ("type", "=", "cash"),
            ("name", "not ilike", "store credit"),
        ]
        if company:
            domain.append(("company_id", "=", company.id))
            till_ids = company._avea_pos_till_cash_journal_ids()
            if till_ids:
                domain.append(("id", "not in", till_ids))
        return domain

    def _avea_is_physical_cash_journal(self, journal):
        self.ensure_one()
        if not journal or journal.type != "cash":
            return False
        if journal.company_id != self:
            return False
        account = journal.default_account_id
        if not account:
            return False
        if account.account_type != "asset_cash":
            return False
        if journal.currency_id and journal.currency_id != self.currency_id:
            return False
        name = (journal.name or "").lower()
        if "store credit" in name:
            return False
        if journal.id in self._avea_pos_till_cash_journal_ids():
            return False
        return True

    @api.constrains("avea_cash_safe_journal_id")
    def _check_avea_cash_safe_journal(self):
        for company in self:
            journal = company.avea_cash_safe_journal_id
            if journal and not company._avea_is_physical_cash_journal(journal):
                raise ValidationError(
                    _(
                        "Select an existing cash journal for physical cash held "
                        "outside the tills. It must use a cash account and must "
                        "not be a POS till journal."
                    )
                )

    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        return fields_list + ["avea_cash_safe_journal_id"]
