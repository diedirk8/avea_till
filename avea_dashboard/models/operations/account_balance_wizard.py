from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AveaAccountBalanceWizard(models.TransientModel):
    _name = "avea.account.balance.wizard"
    _description = "Account Balances"

    line_ids = fields.One2many(
        "avea.account.balance.line",
        "wizard_id",
        string="Accounts",
    )
    total_balance = fields.Monetary(
        string="Total",
        compute="_compute_total_balance",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    has_lines = fields.Boolean(compute="_compute_has_lines")

    @api.depends("line_ids.balance")
    def _compute_total_balance(self):
        for wizard in self:
            wizard.total_balance = sum(wizard.line_ids.mapped("balance"))

    @api.depends("line_ids")
    def _compute_has_lines(self):
        for wizard in self:
            wizard.has_lines = bool(wizard.line_ids)

    @api.model
    def action_open_wizard(self):
        wizard = self.create({})
        wizard._avea_populate_lines()
        return {
            "type": "ir.actions.act_window",
            "name": _("Money & Account Balances"),
            "res_model": self._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "view_id": self.env.ref(
                "avea_till.view_avea_account_balance_wizard_form"
            ).id,
            "target": "new",
        }

    def _avea_populate_lines(self):
        self.ensure_one()
        Line = self.env["avea.account.balance.line"]
        self.line_ids.unlink()
        rows = []
        for sequence, journal in enumerate(
            self.company_id._avea_account_balance_journals(), start=1
        ):
            rows.append(
                {
                    "wizard_id": self.id,
                    "journal_id": journal.id,
                    "account_name": self.company_id._avea_account_balance_label(
                        journal
                    ),
                    "sequence": sequence,
                    "balance": self._avea_journal_balance(journal),
                    "currency_id": self.currency_id.id,
                }
            )
        if rows:
            Line.create(rows)

    def _avea_journal_balance(self, journal):
        """Posted Odoo accounting balance of the journal's money account."""
        account = journal.default_account_id
        if not account:
            return 0.0
        account.invalidate_recordset(["current_balance"])
        return account.sudo().current_balance

    @api.model
    def _avea_money_transactions_action(
        self, journal, account_name=None, check_visibility=False
    ):
        """Posted lines on a money account, without Odoo's journal-items filters.

        Odoo's Journal Items action carries journal_type=general. Creating or
        transferring from that screen posts through the miscellaneous journal
        and the new petty-cash / cash-safe lines never appear on this list.
        """
        if not journal:
            raise UserError(_("This account is no longer available."))
        account = journal.default_account_id
        label = account_name or self.env.company._avea_account_balance_label(journal)
        if not account:
            raise UserError(
                _(
                    "%(account)s has no money account set. "
                    "Ask your accountant to configure it.",
                    account=label or journal.display_name,
                )
            )
        if check_visibility:
            visible = self.env["account.move.line"].search(
                [
                    ("account_id", "=", account.id),
                    ("parent_state", "=", "posted"),
                ],
                limit=1,
            )
            existing = self.env["account.move.line"].sudo().search(
                [
                    ("account_id", "=", account.id),
                    ("parent_state", "=", "posted"),
                ],
                limit=1,
            )
            if existing and not visible:
                raise UserError(
                    _(
                        "The transactions for %(account)s are kept in Accounting. "
                        "The balance shown here is still the current amount.",
                        account=label or journal.display_name,
                    )
                )
        return {
            "type": "ir.actions.act_window",
            "name": label or journal.display_name,
            "res_model": "account.move.line",
            "view_mode": "list",
            "views": [
                (
                    self.env.ref("avea_till.view_avea_account_activity_list").id,
                    "list",
                )
            ],
            "search_view_id": self.env.ref(
                "avea_till.view_avea_account_activity_search"
            ).id,
            "domain": [
                ("account_id", "=", account.id),
                ("parent_state", "=", "posted"),
                (
                    "display_type",
                    "not in",
                    ("line_section", "line_subsection", "line_note"),
                ),
            ],
            "context": {
                "avea_account_workspace": True,
                "avea_from_account_balances": True,
                "avea_money_journal_id": journal.id,
                "avea_account_id": account.id,
                "avea_account_name": label or journal.display_name,
                "create": 0,
            },
            "target": "current",
        }


class AveaAccountBalanceLine(models.TransientModel):
    _name = "avea.account.balance.line"
    _description = "Account Balance Line"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "avea.account.balance.wizard",
        required=True,
        ondelete="cascade",
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Account",
        required=True,
    )
    account_name = fields.Char(
        string="Account",
        required=True,
    )
    sequence = fields.Integer(
        default=10,
    )
    balance = fields.Monetary(
        string="Balance",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
    )

    def action_open_transactions(self):
        self.ensure_one()
        return self.env["avea.account.balance.wizard"]._avea_money_transactions_action(
            self.journal_id, self.account_name, check_visibility=True
        )

    def action_open_transfer(self):
        """Transfer money out of this account, then show the destination."""
        self.ensure_one()
        if not self.journal_id:
            raise UserError(_("This account is no longer available."))
        return (
            self.env["avea.money.transfer.wizard"]
            .with_context(default_from_journal_id=self.journal_id.id)
            .action_open_wizard()
        )

    def get_formview_action(self, access_uid=None):
        self.ensure_one()
        return self.action_open_transactions()
