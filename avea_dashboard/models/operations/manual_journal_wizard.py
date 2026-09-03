from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import formatLang


class AveaManualJournalWizard(models.TransientModel):
    _name = "avea.manual.journal.wizard"
    _description = "Manual Journal Entry"

    date = fields.Date(
        string="Date",
        required=True,
        default=fields.Date.context_today,
    )
    description = fields.Char(
        string="Description / Reference",
        required=True,
    )
    debit_account_id = fields.Many2one(
        "account.account",
        string="Debit Account",
        required=True,
        check_company=True,
        domain="[('active', '=', True), ('account_type', '!=', 'off_balance')]",
    )
    credit_account_id = fields.Many2one(
        "account.account",
        string="Credit Account",
        required=True,
        check_company=True,
        domain="[('active', '=', True), ('account_type', '!=', 'off_balance')]",
    )
    amount = fields.Monetary(
        string="Amount",
        required=True,
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

    @api.constrains("amount")
    def _check_amount_positive(self):
        for wizard in self:
            if wizard.currency_id.compare_amounts(wizard.amount, 0.0) <= 0:
                raise ValidationError(_("Amount must be greater than zero."))

    @api.constrains("debit_account_id", "credit_account_id")
    def _check_different_accounts(self):
        for wizard in self:
            if (
                wizard.debit_account_id
                and wizard.credit_account_id
                and wizard.debit_account_id == wizard.credit_account_id
            ):
                raise ValidationError(
                    _("Choose two different accounts for debit and credit.")
                )

    @api.model
    def action_open_wizard(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Manual Journal Entry"),
            "res_model": self._name,
            "view_mode": "form",
            "view_id": self.env.ref(
                "avea_till.view_avea_manual_journal_wizard_form"
            ).id,
            "target": "new",
        }

    def action_post_journal(self):
        self.ensure_one()
        self._avea_check_entry()
        move = self._avea_post_entry()
        return self._avea_success_close(move)

    def _avea_check_entry(self):
        self.ensure_one()
        description = (self.description or "").strip()
        if not description:
            raise UserError(_("Enter a description / reference."))
        if not self.debit_account_id:
            raise UserError(_("Select the debit account."))
        if not self.credit_account_id:
            raise UserError(_("Select the credit account."))
        if self.debit_account_id == self.credit_account_id:
            raise UserError(
                _("Choose two different accounts for debit and credit.")
            )
        if self.currency_id.compare_amounts(self.amount, 0.0) <= 0:
            raise UserError(_("Amount must be greater than zero."))
        self._avea_miscellaneous_journal()

    def _avea_miscellaneous_journal(self):
        self.ensure_one()
        Journal = (
            self.env["account.journal"].sudo().with_company(self.company_id)
        )
        domain = [
            ("type", "=", "general"),
            ("company_id", "=", self.company_id.id),
        ]
        journal = Journal.search(domain + [("code", "=", "MISC")], limit=1)
        if not journal:
            journal = Journal.search(
                domain + [("name", "ilike", "miscellaneous")],
                limit=1,
            )
        if not journal:
            skip_codes = {"EXCH", "CABA", "STJ", "POSS"}
            journals = Journal.search(domain, order="sequence, id")
            journal = journals.filtered(
                lambda rec: rec.code not in skip_codes
            )[:1] or journals[:1]
        if not journal:
            raise UserError(
                _(
                    "No miscellaneous journal is configured. "
                    "Ask your accountant to set one up."
                )
            )
        return journal

    def _avea_post_entry(self):
        """Post a two-line miscellaneous journal entry."""
        self.ensure_one()
        journal = self._avea_miscellaneous_journal()
        description = (self.description or "").strip()
        amount = self.currency_id.round(self.amount)
        move = (
            self.env["account.move"]
            .sudo()
            .with_company(self.company_id)
            .create(
                {
                    "move_type": "entry",
                    "journal_id": journal.id,
                    "date": self.date,
                    "ref": description,
                    "company_id": self.company_id.id,
                    "currency_id": self.currency_id.id,
                    "narration": _(
                        "Recorded from Avea. %(description)s.",
                        description=description,
                    ),
                    "line_ids": [
                        Command.create(
                            {
                                "name": description,
                                "account_id": self.debit_account_id.id,
                                "debit": amount,
                                "credit": 0.0,
                            }
                        ),
                        Command.create(
                            {
                                "name": description,
                                "account_id": self.credit_account_id.id,
                                "debit": 0.0,
                                "credit": amount,
                            }
                        ),
                    ],
                }
            )
        )
        move.action_post()
        return move

    def _avea_success_close(self, move):
        entry_name = move.name if move and move.name and move.name != "/" else False
        if entry_name:
            message = _(
                "%(description)s for %(amount)s has been recorded (%(entry)s).",
                description=(self.description or "").strip(),
                amount=formatLang(
                    self.env, self.amount, currency_obj=self.currency_id
                ),
                entry=entry_name,
            )
        else:
            message = _(
                "%(description)s for %(amount)s has been recorded.",
                description=(self.description or "").strip(),
                amount=formatLang(
                    self.env, self.amount, currency_obj=self.currency_id
                ),
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Journal entry posted"),
                "message": message,
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
