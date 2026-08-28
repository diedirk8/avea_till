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
    avea_transfer_journal_ids = fields.Many2many(
        "account.journal",
        "avea_company_transfer_journal_rel",
        "company_id",
        "journal_id",
        string="Accounts available for Transfer Money",
        check_company=True,
        domain=(
            "[('type', 'in', ('cash', 'bank')), "
            "('company_id', '=', id), "
            "('name', 'not ilike', 'store credit')]"
        ),
        help="Existing cash and bank journals shown as From/To in Transfer Money. "
        "Unselected journals stay in Odoo accounting but are hidden from Avea.",
    )
    avea_expense_journal_ids = fields.Many2many(
        "account.journal",
        "avea_company_expense_journal_rel",
        "company_id",
        "journal_id",
        string="Accounts available for Operational Expenses",
        check_company=True,
        domain=(
            "[('type', 'in', ('cash', 'bank')), "
            "('company_id', '=', id), "
            "('name', 'not ilike', 'store credit')]"
        ),
        help="Existing cash and bank journals shown as Paid From in "
        "Add Operational Expense. Unselected journals stay in Odoo accounting "
        "but are hidden from Avea.",
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

    def _avea_selectable_liquidity_journals(self):
        """Existing cash/bank journals an administrator may expose in Avea."""
        self.ensure_one()
        return self.env["account.journal"].search(
            [
                ("type", "in", ("cash", "bank")),
                ("company_id", "=", self.id),
                ("name", "not ilike", "store credit"),
            ],
            order="sequence, id",
        )

    def _avea_filter_owner_journals(self, journals):
        self.ensure_one()
        selectable = self._avea_selectable_liquidity_journals()
        if not journals:
            return self.env["account.journal"]
        return selectable.filtered(lambda journal: journal in journals)

    def _avea_transfer_journals(self):
        self.ensure_one()
        return self._avea_filter_owner_journals(self.avea_transfer_journal_ids)

    def _avea_expense_journals(self):
        self.ensure_one()
        return self._avea_filter_owner_journals(self.avea_expense_journal_ids)

    def _avea_default_owner_liquidity_journals(self):
        """Owner-wizard defaults: company cash/bank, not POS till cash.

        Till journals remain selectable in Settings so an administrator can
        expose them. They are omitted by default so historical till cash
        (for example Cash My Company / 125001) stays in the books but out of
        Transfer Money and Operational Expense unless explicitly added.
        """
        self.ensure_one()
        liquidity = self._avea_selectable_liquidity_journals()
        till_ids = set(self._avea_pos_till_cash_journal_ids())
        without_tills = liquidity.filtered(lambda journal: journal.id not in till_ids)
        return without_tills or liquidity

    def _avea_ensure_owner_wizard_journal_defaults(self):
        for company in self:
            defaults = company._avea_default_owner_liquidity_journals()
            vals = {}
            if not company.avea_transfer_journal_ids:
                vals["avea_transfer_journal_ids"] = [fields.Command.set(defaults.ids)]
            if not company.avea_expense_journal_ids:
                vals["avea_expense_journal_ids"] = [fields.Command.set(defaults.ids)]
            if vals:
                company.write(vals)

    @api.constrains("avea_transfer_journal_ids", "avea_expense_journal_ids")
    def _check_avea_owner_wizard_journals(self):
        for company in self:
            selectable = company._avea_selectable_liquidity_journals()
            for journals, label in (
                (company.avea_transfer_journal_ids, _("Transfer Money")),
                (company.avea_expense_journal_ids, _("Operational Expenses")),
            ):
                invalid = journals - selectable
                if invalid:
                    raise ValidationError(
                        _(
                            "Select existing cash or bank accounts for %(label)s. "
                            "Store credit journals cannot be used.",
                            label=label,
                        )
                    )

    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        return fields_list + ["avea_cash_safe_journal_id"]
