from odoo import _, api, fields, models

_PRINTED_RECEIPT_PREVIEW_FIELDS = (
    "avea_customize_printed_receipt",
    "avea_print_receipt_show_logo",
    "avea_print_receipt_logo_size",
    "avea_print_receipt_logo_max_height",
    "avea_print_receipt_show_order_number",
    "avea_print_receipt_show_datetime",
    "avea_print_receipt_show_customer",
    "avea_print_receipt_show_cashier",
    "avea_print_receipt_show_products",
    "avea_print_receipt_show_sku",
    "avea_print_receipt_show_quantity",
    "avea_print_receipt_show_unit_price",
    "avea_print_receipt_show_discounts",
    "avea_print_receipt_show_tax",
    "avea_print_receipt_show_subtotal",
    "avea_print_receipt_show_total",
    "avea_print_receipt_show_payment_method",
    "avea_print_receipt_show_amount_paid",
    "avea_print_receipt_show_change",
    "avea_print_receipt_show_loyalty_balance",
    "avea_print_receipt_show_store_credit_balance",
    "avea_print_receipt_show_customer_account_balance",
    "avea_print_receipt_footer_message",
    "avea_print_receipt_layout",
)


class AveaPrintedReceiptSettings(models.TransientModel):
    _name = "avea.printed.receipt.settings"
    _description = "Avea Printed Receipt Settings"

    @api.depends("company_id")
    def _compute_display_name(self):
        title = _("Printed Receipt")
        for settings in self:
            settings.display_name = title

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    avea_customize_printed_receipt = fields.Boolean(
        string="Customize printed POS receipt",
        related="company_id.avea_customize_printed_receipt",
        readonly=False,
    )
    avea_print_receipt_show_logo = fields.Boolean(
        related="company_id.avea_print_receipt_show_logo",
        readonly=False,
    )
    avea_print_receipt_logo_size = fields.Selection(
        related="company_id.avea_print_receipt_logo_size",
        readonly=False,
    )
    avea_print_receipt_logo_max_height = fields.Integer(
        string="Custom logo height (px)",
        related="company_id.avea_print_receipt_logo_max_height",
        readonly=False,
    )
    avea_print_receipt_show_order_number = fields.Boolean(
        related="company_id.avea_print_receipt_show_order_number",
        readonly=False,
    )
    avea_print_receipt_show_datetime = fields.Boolean(
        related="company_id.avea_print_receipt_show_datetime",
        readonly=False,
    )
    avea_print_receipt_show_customer = fields.Boolean(
        related="company_id.avea_print_receipt_show_customer",
        readonly=False,
    )
    avea_print_receipt_show_cashier = fields.Boolean(
        related="company_id.avea_print_receipt_show_cashier",
        readonly=False,
    )
    avea_print_receipt_show_products = fields.Boolean(
        related="company_id.avea_print_receipt_show_products",
        readonly=False,
    )
    avea_print_receipt_show_sku = fields.Boolean(
        related="company_id.avea_print_receipt_show_sku",
        readonly=False,
    )
    avea_print_receipt_show_quantity = fields.Boolean(
        related="company_id.avea_print_receipt_show_quantity",
        readonly=False,
    )
    avea_print_receipt_show_unit_price = fields.Boolean(
        related="company_id.avea_print_receipt_show_unit_price",
        readonly=False,
    )
    avea_print_receipt_show_discounts = fields.Boolean(
        related="company_id.avea_print_receipt_show_discounts",
        readonly=False,
    )
    avea_print_receipt_show_tax = fields.Boolean(
        related="company_id.avea_print_receipt_show_tax",
        readonly=False,
    )
    avea_print_receipt_show_subtotal = fields.Boolean(
        related="company_id.avea_print_receipt_show_subtotal",
        readonly=False,
    )
    avea_print_receipt_show_total = fields.Boolean(
        related="company_id.avea_print_receipt_show_total",
        readonly=False,
    )
    avea_print_receipt_show_payment_method = fields.Boolean(
        related="company_id.avea_print_receipt_show_payment_method",
        readonly=False,
    )
    avea_print_receipt_show_amount_paid = fields.Boolean(
        related="company_id.avea_print_receipt_show_amount_paid",
        readonly=False,
    )
    avea_print_receipt_show_change = fields.Boolean(
        related="company_id.avea_print_receipt_show_change",
        readonly=False,
    )
    avea_print_receipt_show_loyalty_balance = fields.Boolean(
        related="company_id.avea_print_receipt_show_loyalty_balance",
        readonly=False,
    )
    avea_print_receipt_show_store_credit_balance = fields.Boolean(
        related="company_id.avea_print_receipt_show_store_credit_balance",
        readonly=False,
    )
    avea_print_receipt_show_customer_account_balance = fields.Boolean(
        related="company_id.avea_print_receipt_show_customer_account_balance",
        readonly=False,
    )
    avea_print_receipt_footer_message = fields.Text(
        related="company_id.avea_print_receipt_footer_message",
        readonly=False,
    )
    avea_print_receipt_layout = fields.Selection(
        related="company_id.avea_print_receipt_layout",
        readonly=False,
    )
    printed_receipt_preview_html = fields.Html(
        string="Printed Receipt Preview",
        compute="_compute_printed_receipt_preview_html",
        sanitize=False,
    )

    def _render_printed_receipt_preview_html(self):
        self.ensure_one()
        company = self.company_id
        if not company:
            return False
        return company._avea_print_receipt_body_html(settings=self)

    @api.depends("company_id", "company_id.logo", *_PRINTED_RECEIPT_PREVIEW_FIELDS)
    def _compute_printed_receipt_preview_html(self):
        for settings in self:
            settings.printed_receipt_preview_html = (
                settings._render_printed_receipt_preview_html()
            )

    @api.onchange(*_PRINTED_RECEIPT_PREVIEW_FIELDS)
    def _onchange_printed_receipt_preview_fields(self):
        self.printed_receipt_preview_html = self._render_printed_receipt_preview_html()

    def _avea_printed_receipt_company_values(self):
        self.ensure_one()
        return {name: self[name] for name in _PRINTED_RECEIPT_PREVIEW_FIELDS}

    def action_save_settings(self):
        self.ensure_one()
        self.company_id.write(self._avea_printed_receipt_company_values())
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Settings saved"),
                "message": _(
                    "Printed receipt settings have been saved. "
                    "Close and reopen the POS session for tills to pick up changes."
                ),
                "type": "success",
                "sticky": False,
            },
        }

    @api.model
    def action_open_avea_printed_receipt_settings(self):
        record = self.create({"company_id": self.env.company.id})
        return {
            "type": "ir.actions.act_window",
            "name": _("Printed Receipt"),
            "res_model": "avea.printed.receipt.settings",
            "view_mode": "form",
            "res_id": record.id,
            "target": "current",
            "context": {"clear_breadcrumbs": True},
        }
