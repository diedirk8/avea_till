from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import email_normalize

_RECEIPT_EMAIL_PREVIEW_FIELDS = (
    "avea_auto_email_receipt",
    "avea_receipt_sender_name",
    "avea_receipt_sender_email",
    "avea_receipt_email_reply_to",
    "avea_receipt_email_subject",
    "avea_receipt_email_greeting",
    "avea_receipt_email_closing",
    "avea_receipt_email_show_business_details",
    "avea_receipt_email_show_logo",
    "avea_receipt_email_logo_size",
    "avea_receipt_email_logo_max_height",
    "avea_receipt_email_show_order_info",
    "avea_receipt_email_show_customer_info",
    "avea_receipt_email_show_products",
    "avea_receipt_email_show_line_discounts",
    "avea_receipt_email_show_totals",
    "avea_receipt_email_show_payments",
    "avea_receipt_email_show_loyalty_balance",
    "avea_receipt_email_show_store_credit_balance",
    "avea_receipt_email_show_customer_account_balance",
    "avea_receipt_email_accent_color",
    "avea_receipt_email_layout",
)


class AveaBusinessSettings(models.TransientModel):
    _name = "avea.business.settings"
    _description = "Avea Settings"

    @api.depends("company_id")
    def _compute_display_name(self):
        title = _("Email Receipt")
        for settings in self:
            settings.display_name = title

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
    avea_receipt_email_reply_to = fields.Char(
        string="Reply-to email",
        related="company_id.avea_receipt_email_reply_to",
        readonly=False,
    )
    avea_receipt_email_subject = fields.Char(
        string="Email subject",
        related="company_id.avea_receipt_email_subject",
        readonly=False,
    )
    avea_receipt_email_greeting = fields.Text(
        string="Greeting",
        related="company_id.avea_receipt_email_greeting",
        readonly=False,
    )
    avea_receipt_email_closing = fields.Text(
        string="Closing message",
        related="company_id.avea_receipt_email_closing",
        readonly=False,
    )
    avea_receipt_email_show_business_details = fields.Boolean(
        string="Business details",
        related="company_id.avea_receipt_email_show_business_details",
        readonly=False,
    )
    avea_receipt_email_show_logo = fields.Boolean(
        string="Logo",
        related="company_id.avea_receipt_email_show_logo",
        readonly=False,
    )
    avea_receipt_email_logo_size = fields.Selection(
        related="company_id.avea_receipt_email_logo_size",
        readonly=False,
    )
    avea_receipt_email_logo_max_height = fields.Integer(
        string="Custom logo height (px)",
        related="company_id.avea_receipt_email_logo_max_height",
        readonly=False,
    )
    avea_receipt_email_show_order_info = fields.Boolean(
        string="Order information",
        related="company_id.avea_receipt_email_show_order_info",
        readonly=False,
    )
    avea_receipt_email_show_customer_info = fields.Boolean(
        string="Customer information",
        related="company_id.avea_receipt_email_show_customer_info",
        readonly=False,
    )
    avea_receipt_email_show_products = fields.Boolean(
        string="Products",
        related="company_id.avea_receipt_email_show_products",
        readonly=False,
    )
    avea_receipt_email_show_line_discounts = fields.Boolean(
        string="Line discounts",
        related="company_id.avea_receipt_email_show_line_discounts",
        readonly=False,
    )
    avea_receipt_email_show_totals = fields.Boolean(
        string="Totals",
        related="company_id.avea_receipt_email_show_totals",
        readonly=False,
    )
    avea_receipt_email_show_payments = fields.Boolean(
        string="Payments",
        related="company_id.avea_receipt_email_show_payments",
        readonly=False,
    )
    avea_receipt_email_show_loyalty_balance = fields.Boolean(
        string="Loyalty balance",
        related="company_id.avea_receipt_email_show_loyalty_balance",
        readonly=False,
    )
    avea_receipt_email_show_store_credit_balance = fields.Boolean(
        string="Store Credit balance",
        related="company_id.avea_receipt_email_show_store_credit_balance",
        readonly=False,
    )
    avea_receipt_email_show_customer_account_balance = fields.Boolean(
        string="Customer Account balance",
        related="company_id.avea_receipt_email_show_customer_account_balance",
        readonly=False,
    )
    avea_receipt_email_accent_color = fields.Char(
        string="Accent colour",
        related="company_id.avea_receipt_email_accent_color",
        readonly=False,
    )
    avea_receipt_email_layout = fields.Selection(
        related="company_id.avea_receipt_email_layout",
        readonly=False,
    )
    receipt_email_preview_html = fields.Html(
        string="Receipt Email Preview",
        compute="_compute_receipt_email_preview_html",
        sanitize=False,
    )

    def _render_receipt_email_preview_html(self):
        self.ensure_one()
        company = self.company_id
        if not company:
            return False
        return company._avea_receipt_email_body_html(settings=self)

    @api.depends("company_id", *_RECEIPT_EMAIL_PREVIEW_FIELDS)
    def _compute_receipt_email_preview_html(self):
        for settings in self:
            settings.receipt_email_preview_html = (
                settings._render_receipt_email_preview_html()
            )

    @api.onchange(*_RECEIPT_EMAIL_PREVIEW_FIELDS)
    def _onchange_receipt_email_preview_fields(self):
        self.receipt_email_preview_html = self._render_receipt_email_preview_html()

    def _avea_receipt_email_company_values(self):
        self.ensure_one()
        return {name: self[name] for name in _RECEIPT_EMAIL_PREVIEW_FIELDS}

    def action_save_settings(self):
        self.ensure_one()
        self.company_id.write(self._avea_receipt_email_company_values())
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Settings saved"),
                "message": _("Email receipt settings have been saved."),
                "type": "success",
                "sticky": False,
            },
        }

    @api.constrains(
        "avea_receipt_sender_email",
        "avea_receipt_email_reply_to",
    )
    def _check_receipt_email_addresses(self):
        for settings in self:
            sender = (settings.avea_receipt_sender_email or "").strip()
            if sender and not email_normalize(sender):
                raise ValidationError(
                    _("Enter a valid sender email address for Avea receipts.")
                )
            reply_to = (settings.avea_receipt_email_reply_to or "").strip()
            if reply_to and not email_normalize(reply_to):
                raise ValidationError(
                    _("Enter a valid reply-to email address for Avea receipts.")
                )

    @api.model
    def action_open_avea_settings(self):
        record = self.create({"company_id": self.env.company.id})
        return {
            "type": "ir.actions.act_window",
            "name": _("Email Receipt"),
            "res_model": "avea.business.settings",
            "view_mode": "form",
            "res_id": record.id,
            "target": "current",
            "context": {"clear_breadcrumbs": True},
        }
