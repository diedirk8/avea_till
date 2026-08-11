from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = "res.company"

    avea_credit_setup_complete = fields.Boolean(
        string="Customer Credit Accounting Ready",
        copy=False,
        help="Technical flag set when Store Credit accounting resources exist.",
    )
    avea_credit_issuance_expense_account_id = fields.Many2one(
        "account.account",
        string="Store Credit Issuance Expense",
        copy=False,
        help="Expense account used when store credit is issued to customers.",
    )
    avea_credit_issuance_journal_id = fields.Many2one(
        "account.journal",
        string="Store Credit Issuance Journal",
        copy=False,
        help="Miscellaneous journal used to post manual store credit issuances.",
    )

    def _avea_credit_xmlid(self, suffix):
        self.ensure_one()
        return f"avea_till.avea_credit_{suffix}_{self.id}"

    def _avea_credit_ref(self, suffix):
        self.ensure_one()
        return self.env.ref(self._avea_credit_xmlid(suffix), raise_if_not_found=False)

    def _avea_credit_register_xmlid(self, suffix, record):
        self.ensure_one()
        self.env["ir.model.data"]._update_xmlids(
            [
                {
                    "xml_id": self._avea_credit_xmlid(suffix),
                    "record": record,
                    "noupdate": True,
                }
            ]
        )

    def _avea_credit_liability_start_code(self):
        self.ensure_one()
        Account = self.env["account.account"].with_company(self)
        sample = Account.search([("account_type", "=", "liability_current")], limit=1)
        if sample and sample.code and sample.code[:1].isdigit():
            prefix = sample.code[:4] if len(sample.code) >= 4 else sample.code[:3]
            start = f"{prefix}90"
        else:
            start = "200090"
        return Account._search_new_account_code(start)

    def _avea_credit_find_liability_account(self):
        self.ensure_one()
        account = self._avea_credit_ref("liability_account")
        if account:
            return account

        payment_method = self.env["pos.payment.method"].search(
            [
                ("company_id", "=", self.id),
                ("is_avea_store_credit", "=", True),
                ("outstanding_account_id", "!=", False),
            ],
            limit=1,
        )
        if payment_method:
            return payment_method.outstanding_account_id

        Account = self.env["account.account"].with_company(self)
        return Account.search(
            [
                ("account_type", "=", "liability_current"),
                ("name", "ilike", "Customer Store Credit"),
            ],
            limit=1,
        )

    def _avea_credit_ensure_liability_account(self):
        self.ensure_one()
        account = self._avea_credit_find_liability_account()
        if account:
            self._avea_credit_register_xmlid("liability_account", account)
            return account

        code = self._avea_credit_liability_start_code()
        account = (
            self.env["account.account"]
            .with_company(self)
            .create(
                {
                    "name": _("Customer Store Credit"),
                    "code": code,
                    "account_type": "liability_current",
                    "company_ids": [Command.link(self.id)],
                    "reconcile": False,
                }
            )
        )
        self._avea_credit_register_xmlid("liability_account", account)
        return account

    def _avea_credit_expense_start_code(self):
        self.ensure_one()
        Account = self.env["account.account"].with_company(self)
        sample = Account.search([("account_type", "=", "expense")], limit=1)
        if sample and sample.code and sample.code[:1].isdigit():
            prefix = sample.code[:4] if len(sample.code) >= 4 else sample.code[:3]
            start = f"{prefix}95"
        else:
            start = "600095"
        return Account._search_new_account_code(start)

    def _avea_credit_find_issuance_expense_account(self):
        self.ensure_one()
        account = self._avea_credit_ref("issuance_expense_account")
        if account:
            return account

        if self.avea_credit_issuance_expense_account_id:
            return self.avea_credit_issuance_expense_account_id

        Account = self.env["account.account"].with_company(self)
        return Account.search(
            [
                ("account_type", "=", "expense"),
                ("name", "ilike", "Store Credit Issuance Expense"),
            ],
            limit=1,
        )

    def _avea_credit_ensure_issuance_expense_account(self):
        self.ensure_one()
        account = self._avea_credit_find_issuance_expense_account()
        if account:
            self._avea_credit_register_xmlid("issuance_expense_account", account)
            if self.avea_credit_issuance_expense_account_id != account:
                self.avea_credit_issuance_expense_account_id = account
            return account

        code = self._avea_credit_expense_start_code()
        account = (
            self.env["account.account"]
            .with_company(self)
            .create(
                {
                    "name": _("Store Credit Issuance Expense"),
                    "code": code,
                    "account_type": "expense",
                    "company_ids": [Command.link(self.id)],
                    "reconcile": False,
                }
            )
        )
        self._avea_credit_register_xmlid("issuance_expense_account", account)
        self.avea_credit_issuance_expense_account_id = account
        return account

    def _avea_credit_is_issuance_journal(self, journal):
        if not journal or journal.type != "general":
            return False
        return "store credit issuance" in (journal.name or "").lower()

    def _avea_credit_find_issuance_journal(self):
        self.ensure_one()
        Journal = self.env["account.journal"]

        journal = self._avea_credit_ref("issuance_journal")
        if journal and self._avea_credit_is_issuance_journal(journal):
            return journal

        if self.avea_credit_issuance_journal_id:
            return self.avea_credit_issuance_journal_id

        return Journal.search(
            [
                ("company_id", "=", self.id),
                ("type", "=", "general"),
                ("name", "ilike", "Store Credit Issuance"),
            ],
            limit=1,
        )

    def _avea_credit_ensure_issuance_journal(self):
        self.ensure_one()
        journal = self._avea_credit_find_issuance_journal()
        if journal:
            self._avea_credit_register_xmlid("issuance_journal", journal)
            if self.avea_credit_issuance_journal_id != journal:
                self.avea_credit_issuance_journal_id = journal
            return journal

        Journal = self.env["account.journal"].with_company(self)
        code = "AVSCI"
        existing = Journal.search(
            [
                ("company_id", "=", self.id),
                ("code", "=", code),
            ],
            limit=1,
        )
        if existing:
            code = Journal._get_next_journal_default_code("general", self)

        journal = Journal.create(
            {
                "name": _("Store Credit Issuance"),
                "code": code,
                "type": "general",
                "company_id": self.id,
            }
        )
        self._avea_credit_register_xmlid("issuance_journal", journal)
        self.avea_credit_issuance_journal_id = journal
        return journal

    def _avea_credit_is_store_credit_journal(self, journal):
        if not journal or journal.type != "bank":
            return False
        return "store credit" in (journal.name or "").lower()

    def _avea_credit_find_store_credit_journal(self):
        self.ensure_one()
        Journal = self.env["account.journal"]

        journal = self._avea_credit_ref("journal")
        if journal and self._avea_credit_is_store_credit_journal(journal):
            return journal

        payment_method = self.env["pos.payment.method"].search(
            [
                ("company_id", "=", self.id),
                ("is_avea_store_credit", "=", True),
                ("journal_id", "!=", False),
            ],
            order="active desc, id asc",
            limit=1,
        )
        if payment_method and self._avea_credit_is_store_credit_journal(
            payment_method.journal_id
        ):
            return payment_method.journal_id

        journal = Journal.search(
            [
                ("company_id", "=", self.id),
                ("type", "=", "bank"),
                "|",
                ("name", "ilike", "Store Credit"),
                ("code", "=", "AVSC"),
            ],
            order="id asc",
            limit=1,
        )
        if journal and self._avea_credit_is_store_credit_journal(journal):
            return journal
        return Journal

    def _avea_credit_ensure_store_credit_journal(self):
        self.ensure_one()
        journal = self._avea_credit_find_store_credit_journal()
        if journal:
            self._avea_credit_register_xmlid("journal", journal)
            return journal

        Journal = self.env["account.journal"].with_company(self)
        code = "AVSC"
        existing = Journal.search(
            [
                ("company_id", "=", self.id),
                ("code", "=", code),
            ],
            limit=1,
        )
        if existing:
            code = Journal._get_next_journal_default_code("bank", self)

        journal = Journal.create(
            {
                "name": _("Store Credit"),
                "code": code,
                "type": "bank",
                "company_id": self.id,
            }
        )
        self._avea_credit_register_xmlid("journal", journal)
        return journal

    def _avea_credit_get_store_credit_payment_methods(self):
        self.ensure_one()
        return self.env["pos.payment.method"].search(
            [
                ("company_id", "=", self.id),
                ("is_avea_store_credit", "=", True),
            ],
            order="active desc, sequence, id",
        )

    def _avea_credit_consolidate_store_credit_payment_methods(self):
        self.ensure_one()
        payment_methods = self._avea_credit_get_store_credit_payment_methods()
        if len(payment_methods) <= 1:
            return payment_methods[:1]

        primary = payment_methods[0]
        duplicates = payment_methods[1:]
        if not duplicates:
            return primary

        open_duplicates = duplicates.filtered("open_session_ids")
        closable = duplicates - open_duplicates
        if closable:
            closable.write({"active": False, "is_avea_store_credit": False})
        return primary

    def _avea_credit_find_store_credit_payment_method(self):
        self.ensure_one()
        payment_method = self._avea_credit_ref("payment_method")
        if payment_method and payment_method.is_avea_store_credit:
            return payment_method
        return self._avea_credit_consolidate_store_credit_payment_methods()

    def _avea_credit_can_update_payment_methods(self):
        self.ensure_one()
        if self.env.context.get("avea_credit_before_session_close"):
            return True
        return not self.env["pos.session"].search_count(
            [
                ("state", "!=", "closed"),
                ("config_id.company_id", "=", self.id),
            ]
        )

    def _avea_credit_payment_method_changes(self, payment_method, values):
        changes = {}
        for field_name, new_value in values.items():
            field = payment_method._fields[field_name]
            current = payment_method[field_name]
            if field.type == "many2one":
                current_id = current.id if current else False
                if current_id != new_value:
                    changes[field_name] = new_value
            elif current != new_value:
                changes[field_name] = new_value
        return changes

    def _avea_credit_ensure_store_credit_payment_method(self, journal, liability_account):
        self.ensure_one()
        PaymentMethod = self.env["pos.payment.method"]
        payment_method = self._avea_credit_find_store_credit_payment_method()
        values = {
            "name": _("Store Credit"),
            "journal_id": journal.id,
            "outstanding_account_id": liability_account.id,
            "company_id": self.id,
            "is_avea_store_credit": True,
            "payment_method_type": "none",
            "active": True,
        }

        if payment_method:
            if self._avea_credit_can_update_payment_methods():
                changes = self._avea_credit_payment_method_changes(
                    payment_method, values
                )
                if changes:
                    payment_method.write(changes)
            self._avea_credit_register_xmlid("payment_method", payment_method)
            return payment_method

        payment_method = PaymentMethod.create(values)
        self._avea_credit_register_xmlid("payment_method", payment_method)
        return payment_method

    def _avea_credit_hide_orphan_store_credit_bank_journals(self, canonical_journal):
        """Hide duplicate Avea bank journals on the accounting dashboard only."""
        self.ensure_one()
        orphans = self.env["account.journal"].search(
            [
                ("company_id", "=", self.id),
                ("type", "=", "bank"),
                ("name", "ilike", "Store Credit"),
                ("id", "!=", canonical_journal.id),
                ("show_on_dashboard", "=", True),
            ]
        )
        if not orphans:
            return

        xmlid_journal_ids = set(
            self.env["ir.model.data"]
            .search(
                [
                    ("module", "=", "avea_till"),
                    ("model", "=", "account.journal"),
                    ("name", "like", "avea_credit_journal_%"),
                    ("res_id", "in", orphans.ids),
                ]
            )
            .mapped("res_id")
        )
        linked_journal_ids = set(
            self.env["pos.payment.method"]
            .search(
                [
                    ("company_id", "=", self.id),
                    ("is_avea_store_credit", "=", True),
                    ("journal_id", "in", orphans.ids),
                ]
            )
            .mapped("journal_id")
            .ids
        )
        to_hide = orphans.filtered(
            lambda journal: journal.id not in xmlid_journal_ids
            and journal.id not in linked_journal_ids
        )
        if to_hide:
            to_hide.write({"show_on_dashboard": False})

    def _avea_credit_link_store_credit_to_pos_configs(self, payment_method):
        self.ensure_one()
        configs = self.env["pos.config"].search(
            [
                ("company_id", "=", self.id),
                ("avea_credit_enabled", "=", True),
            ]
        )
        for config in configs:
            if payment_method in config.payment_method_ids:
                continue
            try:
                config.write(
                    {"payment_method_ids": [Command.link(payment_method.id)]}
                )
            except UserError:
                continue

    def _avea_credit_ensure_accounting_setup(self):
        for company in self:
            liability_account = company._avea_credit_ensure_liability_account()
            journal = company._avea_credit_ensure_store_credit_journal()
            payment_method = company._avea_credit_ensure_store_credit_payment_method(
                journal,
                liability_account,
            )
            company._avea_credit_ensure_issuance_expense_account()
            company._avea_credit_ensure_issuance_journal()
            company._avea_credit_link_store_credit_to_pos_configs(payment_method)
            company._avea_credit_hide_orphan_store_credit_bank_journals(journal)
            if not company.avea_credit_setup_complete:
                company.avea_credit_setup_complete = True
        return True

    @api.model
    def _avea_credit_setup_all_companies(self):
        companies = self.search([])
        companies._avea_credit_ensure_accounting_setup()
        return True
