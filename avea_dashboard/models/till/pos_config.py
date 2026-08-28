from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class PosConfig(models.Model):
    _inherit = "pos.config"

    avea_needs_dedicated_cash_journal = fields.Boolean(
        compute="_compute_avea_needs_dedicated_cash_journal",
        help="Technical flag: this POS shares its cash payment method, "
        "journal, or cash account with another till.",
    )

    def _avea_cash_payment_methods(self):
        self.ensure_one()
        return self.payment_method_ids.filtered(
            lambda method: method.journal_id and method.journal_id.type == "cash"
        )

    def _avea_other_pos_configs(self):
        self.ensure_one()
        return self.search(
            [
                ("id", "!=", self.id),
                ("company_id", "=", self.company_id.id),
            ]
        )

    def _compute_avea_needs_dedicated_cash_journal(self):
        for config in self:
            config.avea_needs_dedicated_cash_journal = bool(
                config._avea_pos_needs_dedicated_cash_journal()
            )

    def _avea_pos_needs_dedicated_cash_journal(self):
        self.ensure_one()
        cash_methods = self._avea_cash_payment_methods()
        if not cash_methods:
            return False
        others = self._avea_other_pos_configs()
        if others.filtered(
            lambda other: cash_methods & other.payment_method_ids
        ):
            return True
        journals = cash_methods.journal_id
        if others.mapped("payment_method_ids").filtered(
            lambda method: method.journal_id in journals
        ):
            return True
        accounts = journals.mapped("default_account_id")
        if not accounts:
            return True
        other_till_accounts = others.mapped(
            "payment_method_ids.journal_id.default_account_id"
        )
        if accounts & other_till_accounts:
            return True
        return False

    def _avea_cash_journal_template(self):
        self.ensure_one()
        existing = self._avea_cash_payment_methods().journal_id[:1]
        if existing:
            return existing
        return self.env["account.journal"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("type", "=", "cash"),
                (
                    "id",
                    "in",
                    self.company_id._avea_pos_till_cash_journal_ids(),
                ),
            ],
            limit=1,
        )

    def action_avea_ensure_dedicated_cash_journal(self):
        self.ensure_one()
        if self.current_session_id:
            raise UserError(
                _(
                    "Close this POS session before creating a dedicated "
                    "cash journal for the till."
                )
            )
        self._avea_ensure_dedicated_cash_journal()
        return True

    def _avea_ensure_dedicated_cash_journal(self):
        """Give this POS its own cash payment method, journal, and cash account.

        Non-cash payment methods are left unchanged. Other POS configs are not
        modified. Historical sessions keep their original journals.
        """
        for config in self:
            if not config._avea_pos_needs_dedicated_cash_journal():
                continue
            old_cash_methods = config._avea_cash_payment_methods()
            template = config._avea_cash_journal_template()
            journal_vals = {
                "name": _("Cash (%s)", config.name),
                "type": "cash",
                "company_id": config.company_id.id,
                "show_on_dashboard": False,
            }
            code = self.env["account.journal"]._get_next_journal_default_code(
                "cash", config.company_id
            )
            if code:
                journal_vals["code"] = code
            if template:
                if template.profit_account_id:
                    journal_vals["profit_account_id"] = template.profit_account_id.id
                if template.loss_account_id:
                    journal_vals["loss_account_id"] = template.loss_account_id.id
            journal = self.env["account.journal"].create(journal_vals)
            payment_method = self.env["pos.payment.method"].create(
                {
                    "name": _("Cash"),
                    "journal_id": journal.id,
                    "company_id": config.company_id.id,
                    "sequence": (old_cash_methods[:1].sequence or 0),
                }
            )
            commands = [Command.unlink(method.id) for method in old_cash_methods]
            commands.append(Command.link(payment_method.id))
            config.with_context(
                bypass_payment_method_ids_forbidden_change=True
            ).write({"payment_method_ids": commands})
            config._avea_restore_closed_session_cash_journals(
                template, journal
            )

    def _avea_restore_closed_session_cash_journals(self, old_journal, new_journal):
        """Keep closed sessions on the journal they actually posted with."""
        self.ensure_one()
        if not old_journal or old_journal == new_journal:
            return
        closed = self.env["pos.session"].search(
            [
                ("config_id", "=", self.id),
                ("state", "=", "closed"),
                ("cash_journal_id", "=", new_journal.id),
                ("stop_at", "<", new_journal.create_date),
            ]
        )
        if closed:
            closed.with_context(avea_restore_closed_cash_journal=True).write(
                {"cash_journal_id": old_journal.id}
            )

    @api.model_create_multi
    def create(self, vals_list):
        configs = super().create(vals_list)
        configs.filtered(
            lambda config: config._avea_pos_needs_dedicated_cash_journal()
        )._avea_ensure_dedicated_cash_journal()
        return configs
