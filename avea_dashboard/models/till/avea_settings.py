from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import email_normalize


class AveaBusinessSettings(models.TransientModel):
    _name = "avea.business.settings"
    _description = "Avea Settings"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    avea_auto_email_receipt = fields.Boolean(
        string="Automatically email receipt to customer",
        related="company_id.avea_auto_email_receipt",
        readonly=False,
    )
    avea_receipt_sender_name = fields.Char(
        string="Sender name",
        related="company_id.avea_receipt_sender_name",
        readonly=False,
    )
    avea_receipt_sender_email = fields.Char(
        string="Sender email",
        related="company_id.avea_receipt_sender_email",
        readonly=False,
    )

    @api.model
    def action_open_avea_settings(self):
        record = self.create({"company_id": self.env.company.id})
        return {
            "type": "ir.actions.act_window",
            "name": _("Settings"),
            "res_model": "avea.business.settings",
            "view_mode": "form",
            "res_id": record.id,
            "target": "current",
            "context": {"clear_breadcrumbs": True},
        }
