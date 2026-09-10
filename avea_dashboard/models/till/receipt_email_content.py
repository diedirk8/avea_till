import re

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import email_normalize, formataddr
from odoo.tools.misc import formatLang, format_datetime

from .receipt_logo_styles import (
    EMAIL_LOGO_PRESETS,
    LOGO_SIZE_SELECTION,
    avea_build_logo_style,
)


class ResCompany(models.Model):
    _inherit = "res.company"

    avea_receipt_email_subject = fields.Char(
        string="Receipt Email Subject",
        default="Your receipt from {business}",
        help="Subject line for automatic receipt emails. "
        "You can use {business}, {order} and {customer}.",
    )
    avea_receipt_email_greeting = fields.Text(
        string="Receipt Email Greeting",
        default="Hi {customer},\n\nThank you for shopping with us.",
    )
    avea_receipt_email_closing = fields.Text(
        string="Receipt Email Closing",
        default="We look forward to seeing you again.\n\n{business}",
    )
    avea_receipt_email_reply_to = fields.Char(
        string="Receipt Email Reply-To",
        help="Optional reply-to address for receipt emails. "
        "Leave blank to use the sender email.",
    )
    avea_receipt_email_show_business_details = fields.Boolean(
        string="Show Business Details",
        default=True,
    )
    avea_receipt_email_show_logo = fields.Boolean(
        string="Show Logo",
        default=True,
    )
    avea_receipt_email_logo_size = fields.Selection(
        LOGO_SIZE_SELECTION,
        string="Email Logo Size",
        default="medium",
        required=True,
    )
    avea_receipt_email_logo_max_height = fields.Integer(
        string="Email Logo Max Height (px)",
        default=0,
        help="Optional custom maximum logo height in pixels. "
        "Leave at 0 to use the size preset above.",
    )
    avea_receipt_email_show_order_info = fields.Boolean(
        string="Show Order Information",
        default=True,
    )
    avea_receipt_email_show_customer_info = fields.Boolean(
        string="Show Customer Information",
        default=True,
    )
    avea_receipt_email_show_products = fields.Boolean(
        string="Show Products",
        default=True,
    )
    avea_receipt_email_show_line_discounts = fields.Boolean(
        string="Show Line Discounts",
        default=True,
    )
    avea_receipt_email_show_totals = fields.Boolean(
        string="Show Totals",
        default=True,
    )
    avea_receipt_email_show_payments = fields.Boolean(
        string="Show Payments",
        default=True,
    )
    avea_receipt_email_show_loyalty_balance = fields.Boolean(
        string="Show Loyalty Balance",
        default=True,
    )
    avea_receipt_email_show_store_credit_balance = fields.Boolean(
        string="Show Store Credit Balance",
        default=True,
    )
    avea_receipt_email_show_customer_account_balance = fields.Boolean(
        string="Show Customer Account Balance",
        default=True,
    )
    avea_receipt_email_accent_color = fields.Char(
        string="Receipt Email Accent Colour",
        default="#2563eb",
    )
    avea_receipt_email_layout = fields.Selection(
        [
            ("comfortable", "Comfortable"),
            ("compact", "Compact"),
        ],
        string="Receipt Email Layout",
        default="comfortable",
        required=True,
    )

    @api.constrains("avea_receipt_email_reply_to")
    def _check_avea_receipt_email_reply_to(self):
        for company in self:
            email = (company.avea_receipt_email_reply_to or "").strip()
            if not email:
                continue
            if not email_normalize(email):
                raise ValidationError(
                    _("Enter a valid reply-to email address for Avea receipts.")
                )

    @api.constrains("avea_receipt_email_logo_max_height")
    def _check_avea_receipt_email_logo_max_height(self):
        for company in self:
            height = company.avea_receipt_email_logo_max_height or 0
            if height and not 24 <= height <= 300:
                raise ValidationError(
                    _("Email logo height must be between 24 and 300 pixels.")
                )

    @api.constrains("avea_receipt_email_accent_color")
    def _check_avea_receipt_email_accent_color(self):
        pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")
        for company in self:
            color = (company.avea_receipt_email_accent_color or "").strip()
            if not color:
                continue
            if not pattern.match(color):
                raise ValidationError(
                    _("Use a hex accent colour such as #2563eb.")
                )

    def _avea_receipt_email_business_name(self):
        self.ensure_one()
        return (self.avea_receipt_sender_name or self.name or "").strip()

    def _avea_receipt_email_placeholder_values(self, order=None, order_date=None):
        self.ensure_one()
        business = self._avea_receipt_email_business_name()
        customer = ""
        order_ref = ""
        if order:
            order.ensure_one()
            customer = (order.partner_id.name or "").strip()
            order_ref = (order.pos_reference or order.name or "").strip()
            order_date = order.date_order
        if order_date:
            date_label = format_datetime(
                self.env,
                order_date,
                dt_format="medium",
            )
        else:
            date_label = format_datetime(
                self.env,
                fields.Datetime.now(),
                dt_format="medium",
            )
        return {
            "business": business,
            "customer": customer or _("Customer"),
            "order": order_ref or _("Receipt"),
            "date": date_label,
        }

    def _avea_receipt_email_render_placeholders(self, template, values):
        self.ensure_one()
        rendered = (template or "").strip()
        for key, label in (
            ("{business}", "business"),
            ("{order}", "order"),
            ("{customer}", "customer"),
            ("{date}", "date"),
        ):
            rendered = rendered.replace(key, values.get(label, ""))
        return rendered

    def _avea_receipt_email_subject_render(self, order):
        self.ensure_one()
        values = self._avea_receipt_email_placeholder_values(order)
        subject = self._avea_receipt_email_render_placeholders(
            self.avea_receipt_email_subject,
            values,
        )
        return subject or _("Your receipt from %s") % values["business"]

    def _avea_receipt_email_greeting_render(self, order=None):
        self.ensure_one()
        values = self._avea_receipt_email_placeholder_values(order)
        return self._avea_receipt_email_render_placeholders(
            self.avea_receipt_email_greeting,
            values,
        )

    def _avea_receipt_email_closing_render(self, order=None):
        self.ensure_one()
        values = self._avea_receipt_email_placeholder_values(order)
        return self._avea_receipt_email_render_placeholders(
            self.avea_receipt_email_closing,
            values,
        )

    def _avea_receipt_email_sender_email(self):
        self.ensure_one()
        email = (
            self.avea_receipt_sender_email
            or self.email
            or self.partner_id.email
            or ""
        ).strip()
        return email_normalize(email) if email else False

    def _avea_receipt_email_reply_to(self):
        self.ensure_one()
        override = (self.avea_receipt_email_reply_to or "").strip()
        email = email_normalize(override) if override else self._avea_receipt_email_sender_email()
        if not email:
            return False
        name = self._avea_receipt_email_business_name()
        return formataddr((name, email))

    def _avea_receipt_email_logo_src(self, show_logo=True):
        self.ensure_one()
        if not self.logo or not show_logo:
            return False
        return f"{self.get_base_url().rstrip('/')}/web/image/res.company/{self.id}/logo"

    def _avea_receipt_email_layout_class(self, layout=None):
        self.ensure_one()
        layout = layout or self.avea_receipt_email_layout
        if layout == "compact":
            return "avea-receipt-email--compact"
        return "avea-receipt-email--comfortable"

    def _avea_receipt_email_logo_style(self, logo_size=None, max_height=None):
        self.ensure_one()
        return avea_build_logo_style(
            EMAIL_LOGO_PRESETS,
            size=logo_size or self.avea_receipt_email_logo_size,
            max_height=max_height
            if max_height is not None
            else self.avea_receipt_email_logo_max_height,
        )

    def _avea_receipt_email_layout_styles(self, layout=None):
        self.ensure_one()
        layout = layout or self.avea_receipt_email_layout
        if layout == "compact":
            return {
                "root": (
                    "font-family: Arial, Helvetica, sans-serif; color: #212529; "
                    "font-size: 12px; line-height: 1.35; max-width: 480px;"
                ),
                "section_gap": "0.65rem",
                "card_padding": "0.55rem 0.65rem",
            }
        return {
            "root": (
                "font-family: Arial, Helvetica, sans-serif; color: #212529; "
                "font-size: 14px; line-height: 1.45; max-width: 520px;"
            ),
            "section_gap": "1rem",
            "card_padding": "0.75rem 0.85rem",
        }

    def _avea_receipt_email_accent(self):
        self.ensure_one()
        color = (self.avea_receipt_email_accent_color or "#2563eb").strip()
        return color or "#2563eb"

    def _avea_receipt_email_sample_placeholder_values(self):
        self.ensure_one()
        return self._avea_receipt_email_placeholder_values()

    def _avea_receipt_email_config_values(self, settings=None):
        """Return receipt-email field values from settings or this company."""
        self.ensure_one()
        if settings:
            settings.ensure_one()
            return {
                "sender_name": (
                    settings.avea_receipt_sender_name
                    or self._avea_receipt_email_business_name()
                ),
                "subject_template": settings.avea_receipt_email_subject,
                "greeting_template": settings.avea_receipt_email_greeting,
                "closing_template": settings.avea_receipt_email_closing,
                "show_business_details": settings.avea_receipt_email_show_business_details,
                "show_logo": settings.avea_receipt_email_show_logo,
                "logo_size": settings.avea_receipt_email_logo_size,
                "logo_max_height": settings.avea_receipt_email_logo_max_height,
                "show_order_info": settings.avea_receipt_email_show_order_info,
                "show_customer_info": settings.avea_receipt_email_show_customer_info,
                "show_products": settings.avea_receipt_email_show_products,
                "show_line_discounts": settings.avea_receipt_email_show_line_discounts,
                "show_totals": settings.avea_receipt_email_show_totals,
                "show_payments": settings.avea_receipt_email_show_payments,
                "show_loyalty_balance": settings.avea_receipt_email_show_loyalty_balance,
                "show_store_credit_balance": settings.avea_receipt_email_show_store_credit_balance,
                "show_customer_account_balance": settings.avea_receipt_email_show_customer_account_balance,
                "accent_color": (
                    (settings.avea_receipt_email_accent_color or "#2563eb").strip()
                    or "#2563eb"
                ),
                "layout": settings.avea_receipt_email_layout,
            }
        return {
            "sender_name": self._avea_receipt_email_business_name(),
            "subject_template": self.avea_receipt_email_subject,
            "greeting_template": self.avea_receipt_email_greeting,
            "closing_template": self.avea_receipt_email_closing,
            "show_business_details": self.avea_receipt_email_show_business_details,
            "show_logo": self.avea_receipt_email_show_logo,
            "logo_size": self.avea_receipt_email_logo_size,
            "logo_max_height": self.avea_receipt_email_logo_max_height,
            "show_order_info": self.avea_receipt_email_show_order_info,
            "show_customer_info": self.avea_receipt_email_show_customer_info,
            "show_products": self.avea_receipt_email_show_products,
            "show_line_discounts": self.avea_receipt_email_show_line_discounts,
            "show_totals": self.avea_receipt_email_show_totals,
            "show_payments": self.avea_receipt_email_show_payments,
            "show_loyalty_balance": self.avea_receipt_email_show_loyalty_balance,
            "show_store_credit_balance": self.avea_receipt_email_show_store_credit_balance,
            "show_customer_account_balance": self.avea_receipt_email_show_customer_account_balance,
            "accent_color": self._avea_receipt_email_accent(),
            "layout": self.avea_receipt_email_layout,
        }

    def _avea_receipt_email_sample_context(self, settings=None):
        self.ensure_one()
        config = self._avea_receipt_email_config_values(settings)
        currency = self.currency_id
        sample_values = self._avea_receipt_email_placeholder_values()
        lines = []
        if config["show_products"]:
            lines = [
                {
                    "name": "Premium Dog Food 2kg",
                    "qty": "1",
                    "price_unit": formatLang(self.env, 18.50, currency_obj=currency),
                    "subtotal": formatLang(self.env, 18.50, currency_obj=currency),
                    "discount": 10.0,
                    "discount_label": "10%",
                },
                {
                    "name": "Chew Toy",
                    "qty": "2",
                    "price_unit": formatLang(self.env, 3.25, currency_obj=currency),
                    "subtotal": formatLang(self.env, 6.50, currency_obj=currency),
                    "discount": False,
                    "discount_label": False,
                },
            ]
        payments = []
        if config["show_payments"]:
            payments = [
                {
                    "name": "Card",
                    "amount": formatLang(self.env, 30.0, currency_obj=currency),
                },
            ]
        totals = {
            "subtotal": formatLang(self.env, 21.74, currency_obj=currency),
            "discount": formatLang(self.env, 2.0, currency_obj=currency),
            "tax": formatLang(self.env, 3.26, currency_obj=currency),
            "total": formatLang(self.env, 25.0, currency_obj=currency),
        }
        balances = {}
        if config["show_loyalty_balance"]:
            balances["loyalty"] = [
                {
                    "label": _("Loyalty points"),
                    "value": "120",
                }
            ]
        if config["show_store_credit_balance"]:
            balances["store_credit"] = formatLang(self.env, 15.0, currency_obj=currency)
        if config["show_customer_account_balance"]:
            balances["customer_account"] = formatLang(
                self.env, 42.50, currency_obj=currency
            )
        layout_styles = self._avea_receipt_email_layout_styles(config["layout"])
        logo_style = self._avea_receipt_email_logo_style(
            config["logo_size"],
            config["logo_max_height"],
        )
        return {
            "company": self,
            "is_preview": True,
            "sender_name": config["sender_name"],
            "greeting": self._avea_receipt_email_render_placeholders(
                config["greeting_template"],
                sample_values,
            ),
            "closing": self._avea_receipt_email_render_placeholders(
                config["closing_template"],
                sample_values,
            ),
            "show_business_details": config["show_business_details"],
            "show_logo": config["show_logo"],
            "show_order_info": config["show_order_info"],
            "show_customer_info": config["show_customer_info"],
            "show_products": config["show_products"],
            "show_line_discounts": config["show_line_discounts"],
            "show_totals": config["show_totals"],
            "show_payments": config["show_payments"],
            "accent_color": config["accent_color"],
            "layout_class": self._avea_receipt_email_layout_class(config["layout"]),
            "layout_styles": layout_styles,
            "logo_style": logo_style,
            "logo_src": self._avea_receipt_email_logo_src(config["show_logo"]),
            "business_street": self.street,
            "business_city": self.city,
            "business_zip": self.zip,
            "business_phone": self.phone,
            "business_vat": self.vat,
            "order_reference": "SAMPLE-0001",
            "order_date": format_datetime(
                self.env,
                fields.Datetime.now(),
                dt_format="medium",
            ),
            "customer_name": "Alex Customer" if config["show_customer_info"] else False,
            "customer_email": "alex@example.com" if config["show_customer_info"] else False,
            "lines": lines,
            "payments": payments,
            "change": formatLang(self.env, 5.0, currency_obj=currency)
            if config["show_payments"]
            else False,
            "totals": totals if config["show_totals"] else False,
            "balances": balances,
        }

    def _avea_receipt_email_body_html(self, order=None, settings=None):
        self.ensure_one()
        if order:
            context = order._avea_receipt_email_build_context()
        else:
            context = self._avea_receipt_email_sample_context(settings=settings)
        return Markup(
            self.env["ir.qweb"]._render(
                "avea_till.avea_receipt_email_body",
                context,
            )
        )


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _avea_receipt_email_format_qty(self, qty):
        qty_value = float(qty or 0.0)
        if qty_value == int(qty_value):
            return str(int(qty_value))
        return f"{qty_value:g}"

    def _avea_receipt_email_format_amount(self, amount):
        self.ensure_one()
        return formatLang(self.env, amount, currency_obj=self.currency_id)

    def _avea_receipt_email_build_context(self):
        self.ensure_one()
        company = self.company_id
        partner = self.partner_id
        currency = self.currency_id

        lines = []
        if company.avea_receipt_email_show_products:
            for line in self.lines:
                discount = line.discount if line.discount else False
                lines.append(
                    {
                        "name": line.avea_product_display
                        or line.product_id._avea_plain_name(),
                        "qty": self._avea_receipt_email_format_qty(line.qty),
                        "price_unit": self._avea_receipt_email_format_amount(
                            line.price_unit
                        ),
                        "subtotal": self._avea_receipt_email_format_amount(
                            line.price_subtotal_incl
                        ),
                        "discount": discount,
                        "discount_label": f"{discount:g}%" if discount else False,
                    }
                )

        payments = []
        change_amount = 0.0
        if company.avea_receipt_email_show_payments:
            for payment in self.payment_ids:
                if payment.is_change:
                    change_amount += abs(payment.amount)
                    continue
                payments.append(
                    {
                        "name": payment.payment_method_id.name,
                        "amount": self._avea_receipt_email_format_amount(
                            payment.amount
                        ),
                    }
                )

        amount_discount = sum(
            line.price_unit * line.qty * (line.discount / 100.0)
            for line in self.lines
            if line.discount
        )
        totals = {
            "subtotal": self._avea_receipt_email_format_amount(
                self.amount_total - self.amount_tax
            ),
            "discount": (
                self._avea_receipt_email_format_amount(amount_discount)
                if amount_discount
                else False
            ),
            "tax": self._avea_receipt_email_format_amount(self.amount_tax),
            "total": self._avea_receipt_email_format_amount(self.amount_total),
        }

        balances = {}
        if partner:
            if company.avea_receipt_email_show_loyalty_balance:
                loyalty_cards = self.env["loyalty.card"].sudo().search(
                    [
                        ("partner_id", "=", partner.id),
                        ("points", "!=", 0),
                    ]
                )
                loyalty_items = []
                for card in loyalty_cards:
                    if not card.points:
                        continue
                    loyalty_items.append(
                        {
                            "label": card.program_id.name or _("Loyalty points"),
                            "value": card._format_points(card.points),
                        }
                    )
                if loyalty_items:
                    balances["loyalty"] = loyalty_items

            if company.avea_receipt_email_show_store_credit_balance:
                partner.invalidate_recordset(["avea_credit_balance"])
                if partner.avea_credit_balance:
                    balances["store_credit"] = self._avea_receipt_email_format_amount(
                        partner.avea_credit_balance
                    )

            if company.avea_receipt_email_show_customer_account_balance:
                partner.invalidate_recordset(["avea_customer_account_balance"])
                if partner.avea_customer_account_balance:
                    balances["customer_account"] = (
                        self._avea_receipt_email_format_amount(
                            partner.avea_customer_account_balance
                        )
                    )

        return {
            "company": company,
            "is_preview": False,
            "sender_name": company._avea_receipt_email_business_name(),
            "greeting": company._avea_receipt_email_greeting_render(self),
            "closing": company._avea_receipt_email_closing_render(self),
            "show_business_details": company.avea_receipt_email_show_business_details,
            "show_logo": company.avea_receipt_email_show_logo,
            "show_order_info": company.avea_receipt_email_show_order_info,
            "show_customer_info": company.avea_receipt_email_show_customer_info,
            "show_products": company.avea_receipt_email_show_products,
            "show_line_discounts": company.avea_receipt_email_show_line_discounts,
            "show_totals": company.avea_receipt_email_show_totals,
            "show_payments": company.avea_receipt_email_show_payments,
            "accent_color": company._avea_receipt_email_accent(),
            "layout_class": company._avea_receipt_email_layout_class(),
            "layout_styles": company._avea_receipt_email_layout_styles(),
            "logo_style": company._avea_receipt_email_logo_style(),
            "logo_src": company._avea_receipt_email_logo_src(
                company.avea_receipt_email_show_logo
            ),
            "business_street": company.street,
            "business_city": company.city,
            "business_zip": company.zip,
            "business_phone": company.phone,
            "business_vat": company.vat,
            "order_reference": self.pos_reference or self.name,
            "order_date": format_datetime(
                self.env,
                self.date_order,
                dt_format="medium",
            ),
            "customer_name": partner.name if partner else False,
            "customer_email": partner.email if partner else False,
            "lines": lines,
            "payments": payments,
            "change": (
                self._avea_receipt_email_format_amount(change_amount)
                if change_amount
                else False
            ),
            "totals": totals,
            "balances": balances,
        }
