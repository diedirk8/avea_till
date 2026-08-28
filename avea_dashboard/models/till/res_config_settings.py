from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    avea_cash_safe_journal_id = fields.Many2one(
        related="company_id.avea_cash_safe_journal_id",
        readonly=False,
        string="Cash Safe / Company Cash Journal",
        domain=(
            "[('type', '=', 'cash'), "
            "('company_id', '=', company_id), "
            "('name', 'not ilike', 'store credit')]"
        ),
    )
    pos_avea_needs_dedicated_cash_journal = fields.Boolean(
        related="pos_config_id.avea_needs_dedicated_cash_journal",
    )

    def action_avea_ensure_dedicated_cash_journal(self):
        self.ensure_one()
        self.pos_config_id.action_avea_ensure_dedicated_cash_journal()
        return {"type": "ir.actions.client", "tag": "reload"}
