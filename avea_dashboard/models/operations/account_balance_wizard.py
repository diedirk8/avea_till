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
        journal = self.journal_id
        if not journal:
            raise UserError(_("This account is no longer available."))
        account = journal.default_account_id
        if not account:
            raise UserError(
                _(
                    "%(account)s has no money account set. "
                    "Ask your accountant to configure it.",
                    account=self.account_name or journal.display_name,
                )
            )
        # Journal items on the money account match the balance shown.
        # Bank Statement windows require Accounting groups that POS users
        # do not have.
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
                    account=self.account_name or journal.display_name,
                )
            )
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "account.action_account_moves_all_a"
        )
        action["name"] = self.account_name or journal.display_name
        action["domain"] = [
            ("account_id", "=", account.id),
            ("parent_state", "=", "posted"),
            (
                "display_type",
                "not in",
                ("line_section", "line_subsection", "line_note"),
            ),
        ]
        context = action.get("context") or {}
        if isinstance(context, str):
            context = dict(self.env.context)
        else:
            context = dict(context)
        context.update(
            {
                "search_default_account_id": account.id,
                "search_default_posted": 1,
                "create": 0,
                "default_account_id": account.id,
            }
        )
        action["context"] = context
        return action

    def get_formview_action(self, access_uid=None):
        self.ensure_one()
        return self.action_open_transactions()
