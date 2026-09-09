from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.misc import formatLang, format_datetime

from .receipt_logo_styles import LOGO_SIZE_SELECTION, PRINT_LOGO_PRESETS, avea_build_logo_style


class ResCompany(models.Model):
    _inherit = "res.company"

    avea_customize_printed_receipt = fields.Boolean(
        string="Customize Printed POS Receipt",
        default=False,
        help="When enabled, Avea applies the printed receipt options below. "
        "When disabled, the standard Odoo POS receipt is used unchanged.",
    )
    avea_print_receipt_show_logo = fields.Boolean(
        string="Show Logo",
        default=True,
    )
    avea_print_receipt_logo_size = fields.Selection(
        LOGO_SIZE_SELECTION,
        string="Logo Size",
        default="medium",
        required=True,
    )
    avea_print_receipt_logo_max_height = fields.Integer(
        string="Printed Logo Max Height (px)",
        default=0,
        help="Optional custom maximum logo height in pixels. "
        "Leave at 0 to use the size preset above.",
    )
    avea_print_receipt_show_order_number = fields.Boolean(
        string="Show Order Number",
        default=True,
    )
    avea_print_receipt_show_datetime = fields.Boolean(
        string="Show Date/Time",
        default=True,
    )
    avea_print_receipt_show_customer = fields.Boolean(
        string="Show Customer",
        default=True,
    )
    avea_print_receipt_show_cashier = fields.Boolean(
        string="Show Cashier",
        default=True,
    )
    avea_print_receipt_show_products = fields.Boolean(
        string="Show Products",
        default=True,
    )
    avea_print_receipt_show_sku = fields.Boolean(
        string="Show SKU/Barcode",
        default=False,
    )
    avea_print_receipt_show_quantity = fields.Boolean(
        string="Show Quantity",
        default=True,
    )
    avea_print_receipt_show_unit_price = fields.Boolean(
        string="Show Unit Price",
        default=True,
    )
    avea_print_receipt_show_discounts = fields.Boolean(
        string="Show Discounts",
        default=True,
    )
    avea_print_receipt_show_tax = fields.Boolean(
        string="Show Tax",
        default=True,
    )
    avea_print_receipt_show_subtotal = fields.Boolean(
        string="Show Subtotal",
        default=True,
    )
    avea_print_receipt_show_total = fields.Boolean(
        string="Show Total",
        default=True,
    )
    avea_print_receipt_show_payment_method = fields.Boolean(
        string="Show Payment Method",
        default=True,
    )
    avea_print_receipt_show_amount_paid = fields.Boolean(
        string="Show Amount Paid",
        default=True,
    )
    avea_print_receipt_show_change = fields.Boolean(
        string="Show Change",
        default=True,
    )
    avea_print_receipt_show_loyalty_balance = fields.Boolean(
        string="Show Loyalty Balance",
        default=True,
    )
    avea_print_receipt_show_store_credit_balance = fields.Boolean(
        string="Show Store Credit Balance",
        default=True,
    )
    avea_print_receipt_show_customer_account_balance = fields.Boolean(
        string="Show Customer Account Balance",
        default=True,
    )
    avea_print_receipt_footer_message = fields.Text(
        string="Custom Footer Message",
        help="Optional message printed at the bottom of the receipt.",
    )
    avea_print_receipt_layout = fields.Selection(
        [
            ("compact", "Compact"),
            ("standard", "Standard"),
            ("detailed", "Detailed"),
        ],
        string="Printed Receipt Layout",
        default="standard",
        required=True,
    )

    @api.constrains("avea_print_receipt_logo_max_height")
    def _check_avea_print_receipt_logo_max_height(self):
        for company in self:
            height = company.avea_print_receipt_logo_max_height or 0
            if height and not 24 <= height <= 300:
                raise ValidationError(
                    _("Printed logo height must be between 24 and 300 pixels.")
                )

    def _avea_print_receipt_config_values(self, settings=None):
        self.ensure_one()
        if settings:
            settings.ensure_one()
            return {
                "customize": settings.avea_customize_printed_receipt,
                "show_logo": settings.avea_print_receipt_show_logo,
                "logo_size": settings.avea_print_receipt_logo_size,
                "logo_max_height": settings.avea_print_receipt_logo_max_height,
                "show_order_number": settings.avea_print_receipt_show_order_number,
                "show_datetime": settings.avea_print_receipt_show_datetime,
                "show_customer": settings.avea_print_receipt_show_customer,
                "show_cashier": settings.avea_print_receipt_show_cashier,
                "show_products": settings.avea_print_receipt_show_products,
                "show_sku": settings.avea_print_receipt_show_sku,
                "show_quantity": settings.avea_print_receipt_show_quantity,
                "show_unit_price": settings.avea_print_receipt_show_unit_price,
                "show_discounts": settings.avea_print_receipt_show_discounts,
                "show_tax": settings.avea_print_receipt_show_tax,
                "show_subtotal": settings.avea_print_receipt_show_subtotal,
                "show_total": settings.avea_print_receipt_show_total,
                "show_payment_method": settings.avea_print_receipt_show_payment_method,
                "show_amount_paid": settings.avea_print_receipt_show_amount_paid,
                "show_change": settings.avea_print_receipt_show_change,
                "show_loyalty_balance": settings.avea_print_receipt_show_loyalty_balance,
                "show_store_credit_balance": settings.avea_print_receipt_show_store_credit_balance,
                "show_customer_account_balance": settings.avea_print_receipt_show_customer_account_balance,
                "footer_message": settings.avea_print_receipt_footer_message,
                "layout": settings.avea_print_receipt_layout,
            }
        return {
            "customize": self.avea_customize_printed_receipt,
            "show_logo": self.avea_print_receipt_show_logo,
            "logo_size": self.avea_print_receipt_logo_size,
            "logo_max_height": self.avea_print_receipt_logo_max_height,
            "show_order_number": self.avea_print_receipt_show_order_number,
            "show_datetime": self.avea_print_receipt_show_datetime,
            "show_customer": self.avea_print_receipt_show_customer,
            "show_cashier": self.avea_print_receipt_show_cashier,
            "show_products": self.avea_print_receipt_show_products,
            "show_sku": self.avea_print_receipt_show_sku,
            "show_quantity": self.avea_print_receipt_show_quantity,
            "show_unit_price": self.avea_print_receipt_show_unit_price,
            "show_discounts": self.avea_print_receipt_show_discounts,
            "show_tax": self.avea_print_receipt_show_tax,
            "show_subtotal": self.avea_print_receipt_show_subtotal,
            "show_total": self.avea_print_receipt_show_total,
            "show_payment_method": self.avea_print_receipt_show_payment_method,
            "show_amount_paid": self.avea_print_receipt_show_amount_paid,
            "show_change": self.avea_print_receipt_show_change,
            "show_loyalty_balance": self.avea_print_receipt_show_loyalty_balance,
            "show_store_credit_balance": self.avea_print_receipt_show_store_credit_balance,
            "show_customer_account_balance": self.avea_print_receipt_show_customer_account_balance,
            "footer_message": self.avea_print_receipt_footer_message,
            "layout": self.avea_print_receipt_layout,
        }

    def _avea_print_receipt_layout_styles(self, layout=None):
        self.ensure_one()
        layout = layout or self.avea_print_receipt_layout
        if layout == "compact":
            return {
                "root": (
                    "font-family: Arial, Helvetica, sans-serif; color: #000; "
                    "font-size: 13px; font-weight: 500; line-height: 1.35; "
                    "max-width: 280px; margin: 0 auto;"
                ),
                "section_gap": "0.35rem",
                "line_padding": "0.15rem 0",
                "emphasis": "font-weight: 700;",
            }
        if layout == "detailed":
            return {
                "root": (
                    "font-family: Arial, Helvetica, sans-serif; color: #000; "
                    "font-size: 15px; font-weight: 500; line-height: 1.45; "
                    "max-width: 320px; margin: 0 auto;"
                ),
                "section_gap": "0.65rem",
                "line_padding": "0.3rem 0",
                "emphasis": "font-weight: 700;",
            }
        return {
            "root": (
                "font-family: Arial, Helvetica, sans-serif; color: #000; "
                "font-size: 14px; font-weight: 500; line-height: 1.4; "
                "max-width: 300px; margin: 0 auto;"
            ),
            "section_gap": "0.5rem",
            "line_padding": "0.2rem 0",
            "emphasis": "font-weight: 700;",
        }

    def _avea_print_receipt_logo_style(self, logo_size=None, max_height=None):
        self.ensure_one()
        return avea_build_logo_style(
            PRINT_LOGO_PRESETS,
            size=logo_size or self.avea_print_receipt_logo_size,
            max_height=max_height
            if max_height is not None
            else self.avea_print_receipt_logo_max_height,
        )

    def _avea_print_receipt_sample_context(self, settings=None):
        self.ensure_one()
        config = self._avea_print_receipt_config_values(settings)
        currency = self.currency_id
        layout_styles = self._avea_print_receipt_layout_styles(config["layout"])
        lines = []
        if config["show_products"]:
            lines = [
                {
                    "name": "Premium Dog Food 2kg",
                    "sku": "PDF-2KG",
                    "qty": "1",
                    "unit_price": formatLang(self.env, 18.50, currency_obj=currency),
                    "subtotal": formatLang(self.env, 18.50, currency_obj=currency),
                    "discount": "10%",
                },
                {
                    "name": "Chew Toy",
                    "sku": "CT-001",
                    "qty": "2",
                    "unit_price": formatLang(self.env, 3.25, currency_obj=currency),
                    "subtotal": formatLang(self.env, 6.50, currency_obj=currency),
                    "discount": False,
                },
            ]
        return {
            "company": self,
            "is_preview": True,
            "customize": config["customize"],
            "business_name": self.name,
            "logo_src": self._avea_receipt_email_logo_src(config["show_logo"]),
            "logo_style": self._avea_print_receipt_logo_style(
                config["logo_size"],
                config["logo_max_height"],
            ),
            "layout_class": f"avea-print-receipt--{config['layout']}",
            "layout_styles": layout_styles,
            "order_reference": "SAMPLE-0001",
            "order_datetime": format_datetime(
                self.env,
                fields.Datetime.now(),
                dt_format="medium",
            ),
            "cashier_name": "Alex Cashier",
            "customer_name": "Alex Customer",
            "customer_address": "12 Sample Street, Bethlehem",
            "lines": lines,
            "subtotal": formatLang(self.env, 21.74, currency_obj=currency),
            "tax": formatLang(self.env, 3.26, currency_obj=currency),
            "discount_total": formatLang(self.env, 2.0, currency_obj=currency),
            "total": formatLang(self.env, 25.0, currency_obj=currency),
            "payments": [
                {
                    "name": "Card",
                    "amount": formatLang(self.env, 30.0, currency_obj=currency),
                }
            ],
            "amount_paid": formatLang(self.env, 30.0, currency_obj=currency),
            "change": formatLang(self.env, 5.0, currency_obj=currency),
            "loyalty_balance": "120 points",
            "store_credit_balance": formatLang(self.env, 15.0, currency_obj=currency),
            "customer_account_balance": formatLang(self.env, 42.50, currency_obj=currency),
            "footer_message": (config["footer_message"] or "").strip(),
            **config,
        }

    def _avea_print_receipt_body_html(self, settings=None):
        self.ensure_one()
        context = self._avea_print_receipt_sample_context(settings=settings)
        return Markup(
            self.env["ir.qweb"]._render(
                "avea_till.avea_print_receipt_preview",
                context,
            )
        )

    def get_avea_print_receipt_pos_settings(self):
        """Return live printed-receipt settings for the POS receipt renderer."""
        self.ensure_one()
        return self._avea_print_receipt_config_values()
