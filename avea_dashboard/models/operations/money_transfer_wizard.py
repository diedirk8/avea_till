from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import formatLang


class AveaMoneyTransferWizard(models.TransientModel):
    _name = "avea.money.transfer.wizard"
    _description = "Transfer Money"

    from_journal_id = fields.Many2one(
        "account.journal",
        string="From",
        required=True,
        domain=(
            "[('type', 'in', ('cash', 'bank')), "
            "('company_id', '=', company_id), "
            "('name', 'not ilike', 'store credit'), "
            "('id', '!=', to_journal_id)]"
        ),
        help="The company money account to take the money from.",
    )
    to_journal_id = fields.Many2one(
        "account.journal",
        string="To",
        required=True,
        domain=(
            "[('type', 'in', ('cash', 'bank')), "
            "('company_id', '=', company_id), "
            "('name', 'not ilike', 'store credit'), "
            "('id', '!=', from_journal_id)]"
        ),
        help="The company money account to put the money into.",
    )
    amount = fields.Monetary(
        string="Amount",
        required=True,
        currency_field="currency_id",
    )
    transfer_date = fields.Date(
        string="Date",
        required=True,
        default=fields.Date.context_today,
    )
    reference = fields.Char(
        string="Reference",
    )
    notes = fields.Text(
        string="Notes",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirm", "Confirm"),
        ],
        default="draft",
        required=True,
    )
    confirmation_message = fields.Char(
        compute="_compute_confirmation_message",
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

    @api.depends("from_journal_id", "to_journal_id", "amount", "currency_id")
    def _compute_confirmation_message(self):
        for wizard in self:
            if (
                wizard.from_journal_id
                and wizard.to_journal_id
                and wizard.currency_id.compare_amounts(wizard.amount, 0.0) > 0
            ):
                wizard.confirmation_message = _(
                    "Transfer %(amount)s from %(source)s to %(destination)s?",
                    amount=formatLang(
                        wizard.env, wizard.amount, currency_obj=wizard.currency_id
                    ),
                    source=wizard.from_journal_id.display_name,
                    destination=wizard.to_journal_id.display_name,
                )
            else:
                wizard.confirmation_message = False

    @api.constrains("amount")
    def _check_amount_positive(self):
        for wizard in self:
            if wizard.currency_id.compare_amounts(wizard.amount, 0.0) <= 0:
                raise ValidationError(_("Amount must be greater than zero."))

    @api.constrains("from_journal_id", "to_journal_id")
    def _check_different_accounts(self):
        for wizard in self:
            if (
                wizard.from_journal_id
                and wizard.to_journal_id
                and wizard.from_journal_id == wizard.to_journal_id
            ):
                raise ValidationError(
                    _("Choose two different company money accounts.")
                )

    @api.model
    def action_open_wizard(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Transfer Money"),
            "res_model": self._name,
            "view_mode": "form",
            "view_id": self.env.ref(
                "avea_till.view_avea_money_transfer_wizard_form"
            ).id,
            "target": "new",
        }

    def action_review_transfer(self):
        self.ensure_one()
        self._avea_check_transfer()
        self.state = "confirm"
        return self._avea_reopen()

    def action_back(self):
        self.ensure_one()
        self.state = "draft"
        return self._avea_reopen()

    def action_confirm_transfer(self):
        self.ensure_one()
        self._avea_check_transfer()
        self._avea_post_transfer()
        return self._avea_success_close()

    def _avea_reopen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Transfer Money"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref(
                "avea_till.view_avea_money_transfer_wizard_form"
            ).id,
            "target": "new",
        }

    def _avea_check_transfer(self):
        self.ensure_one()
        if not self.from_journal_id:
            raise UserError(_("Select the account to transfer from."))
        if not self.to_journal_id:
            raise UserError(_("Select the account to transfer to."))
        if self.from_journal_id == self.to_journal_id:
            raise UserError(_("Choose two different company money accounts."))
        if self.currency_id.compare_amounts(self.amount, 0.0) <= 0:
            raise UserError(_("Amount must be greater than zero."))
        allowed = self._avea_money_journals(self.company_id)
        if self.from_journal_id not in allowed or self.to_journal_id not in allowed:
            raise UserError(
                _(
                    "Choose company cash or bank accounts. "
                    "Ask your accountant to configure them if none are available."
                )
            )
        self._avea_liquidity_account(self.from_journal_id)
        self._avea_liquidity_account(self.to_journal_id)

    @api.model
    def _avea_money_journals(self, company):
        company = company or self.env.company
        return self.env["account.journal"].search(
            [
                ("type", "in", ("cash", "bank")),
                ("company_id", "=", company.id),
                ("name", "not ilike", "store credit"),
            ],
            order="sequence, id",
        )

    def _avea_liquidity_account(self, journal):
        account = journal.default_account_id
        if not account:
            raise UserError(
                _(
                    "%(journal)s has no money account set. "
                    "Ask your accountant to configure it.",
                    journal=journal.display_name,
                )
            )
        return account

    def _avea_post_transfer(self):
        """Move money between two cash/bank journals using Odoo statement lines.

        Odoo 19 no longer has the old payment internal-transfer wizard. The
        company's Liquidity Transfer account is the standard intermediary for
        moving money between liquidity accounts: one outbound statement line
        on From, one inbound statement line on To, then those transfer-account
        lines are reconciled. If that account is not configured, a single
        statement line on From posts directly to the To money account.
        """
        self.ensure_one()
        from_account = self._avea_liquidity_account(self.from_journal_id)
        to_account = self._avea_liquidity_account(self.to_journal_id)
        if from_account == to_account:
            raise UserError(_("Choose two different company money accounts."))
        transfer_account = self.company_id.transfer_account_id
        payment_ref = self.reference or _("Avea Money Transfer")
        narration = self._avea_transfer_narration()
        if transfer_account and transfer_account not in (from_account, to_account):
            from_line = self._avea_create_statement_line(
                self.from_journal_id, -self.amount, payment_ref, transfer_account
            )
            to_line = self._avea_create_statement_line(
                self.to_journal_id, self.amount, payment_ref, transfer_account
            )
            self._avea_set_move_narration(from_line.move_id | to_line.move_id, narration)
            self._avea_reconcile_transfer_account(
                from_line, to_line, transfer_account
            )
            return from_line.move_id | to_line.move_id
        statement_line = self._avea_create_statement_line(
            self.from_journal_id, -self.amount, payment_ref, to_account
        )
        self._avea_set_move_narration(statement_line.move_id, narration)
        return statement_line.move_id

    def _avea_transfer_narration(self):
        parts = [
            _(
                "Recorded from Avea. Transfer from %(source)s to %(destination)s.",
                source=self.from_journal_id.display_name,
                destination=self.to_journal_id.display_name,
            )
        ]
        if self.notes:
            parts.append(self.notes)
        return "\n".join(parts)

    def _avea_create_statement_line(self, journal, amount, payment_ref, counterpart):
        return (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(
                {
                    "journal_id": journal.id,
                    "amount": amount,
                    "date": self.transfer_date,
                    "payment_ref": payment_ref,
                    "partner_id": self.company_id.partner_id.id,
                    "counterpart_account_id": counterpart.id,
                }
            )
        )

    def _avea_set_move_narration(self, moves, narration):
        moves.sudo().write({"narration": narration})

    def _avea_reconcile_transfer_account(self, from_line, to_line, transfer_account):
        lines = (from_line.move_id.line_ids | to_line.move_id.line_ids).filtered(
            lambda line: line.account_id == transfer_account and not line.reconciled
        )
        if len(lines) >= 2:
            lines.sudo().reconcile()

    def _avea_success_close(self):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Money transferred"),
                "message": _(
                    "%(amount)s moved from %(source)s to %(destination)s.",
                    amount=formatLang(
                        self.env, self.amount, currency_obj=self.currency_id
                    ),
                    source=self.from_journal_id.display_name,
                    destination=self.to_journal_id.display_name,
                ),
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
