# -*- coding: utf-8 -*-
import base64

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import email_normalize, format_date, format_datetime, formataddr
from odoo.tools.misc import formatLang


class AveaPosQuote(models.Model):
    """A customer quote taken on the till.

    This is not a sale. It does not take payment, move stock, or appear in
    sales or cash-up.
    """

    _name = "avea.pos.quote"
    _description = "POS Quote"
    _order = "quote_date desc, id desc"

    VALID_DAYS = 14

    name = fields.Char(
        string="Quote",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        ondelete="restrict",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
    )
    config_id = fields.Many2one(
        "pos.config",
        string="Point of Sale",
        ondelete="set null",
    )
    session_id = fields.Many2one(
        "pos.session",
        string="Session",
        ondelete="set null",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Cashier user",
        default=lambda self: self.env.user,
        required=True,
    )
    cashier_name = fields.Char(string="Cashier")
    quote_date = fields.Datetime(
        string="Date",
        required=True,
        default=fields.Datetime.now,
    )
    valid_until = fields.Date(
        string="Valid until",
        required=True,
    )
    note = fields.Text(string="Note")
    line_ids = fields.One2many(
        "avea.pos.quote.line",
        "quote_id",
        string="Lines",
    )
    amount_untaxed = fields.Monetary(
        string="Ex tax",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    amount_tax = fields.Monetary(
        string="Tax",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    amount_total = fields.Monetary(
        string="Total",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    email_sent = fields.Boolean(string="Emailed", copy=False, readonly=True)

    @api.depends("line_ids.price_subtotal", "line_ids.price_tax", "line_ids.price_total")
    def _compute_amounts(self):
        for quote in self:
            quote.amount_untaxed = sum(quote.line_ids.mapped("price_subtotal"))
            quote.amount_tax = sum(quote.line_ids.mapped("price_tax"))
            quote.amount_total = sum(quote.line_ids.mapped("price_total"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("avea.pos.quote") or _("New")
            if not vals.get("valid_until"):
                vals["valid_until"] = fields.Date.add(
                    fields.Date.context_today(self),
                    days=self.VALID_DAYS,
                )
        return super().create(vals_list)

    @api.constrains("line_ids")
    def _check_lines(self):
        for quote in self:
            if not quote.line_ids:
                raise ValidationError(_("Add a product before creating a quote."))

    @api.model
    def create_from_pos(self, payload):
        """Save the current till basket as a quote. The basket itself is left alone."""
        payload = payload or {}
        partner = self.env["res.partner"].browse(payload.get("partner_id")).exists()
        if not partner:
            raise UserError(_("Select a customer before creating a quote."))
        config = self.env["pos.config"].browse(payload.get("config_id")).exists()
        company = config.company_id or self.env.company
        session = self.env["pos.session"].browse(payload.get("session_id")).exists()
        if session and config and session.config_id != config:
            session = self.env["pos.session"]
        currency = company.currency_id
        line_commands = []
        for index, row in enumerate(payload.get("lines") or []):
            quantity = float(row.get("quantity") or 0.0)
            if quantity <= 0:
                continue
            name = (row.get("name") or "").strip()
            product = self.env["product.product"].browse(row.get("product_id")).exists()
            if not name and product:
                name = product.display_name
            if not name:
                continue
            price_subtotal = currency.round(float(row.get("price_subtotal") or 0.0))
            price_total = currency.round(float(row.get("price_total") or 0.0))
            line_commands.append(
                fields.Command.create(
                    {
                        "sequence": index,
                        "product_id": product.id if product else False,
                        "name": name[:240],
                        "default_code": (row.get("default_code") or "")[:64] or False,
                        "quantity": quantity,
                        "discount": float(row.get("discount") or 0.0),
                        "price_unit": currency.round(float(row.get("price_unit") or 0.0)),
                        "pos_price_unit": currency.round(float(row.get("pos_price_unit") or 0.0)),
                        "price_subtotal": price_subtotal,
                        "price_tax": currency.round(price_total - price_subtotal),
                        "price_total": price_total,
                    }
                )
            )
        if not line_commands:
            raise UserError(_("Add a product before creating a quote."))
        quote = self.create(
            {
                "partner_id": partner.id,
                "company_id": company.id,
                "config_id": config.id if config else False,
                "session_id": session.id if session else False,
                "user_id": self.env.user.id,
                "cashier_name": (payload.get("cashier_name") or self.env.user.name or "")[:128],
                "note": (payload.get("note") or "").strip() or False,
                "line_ids": line_commands,
            }
        )
        return quote._avea_pos_payload()

    def _avea_pos_payload(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "valid_until": fields.Date.to_string(self.valid_until),
            "valid_until_display": format_date(self.env, self.valid_until),
            "amount_total": self.amount_total,
            "amount_total_display": formatLang(
                self.env,
                self.amount_total,
                currency_obj=self.currency_id,
            ),
            "partner_name": self.partner_id.display_name,
            "partner_email": (self.partner_id.email or "").strip(),
        }

    def _avea_pos_list_row(self):
        self.ensure_one()
        row = self._avea_pos_payload()
        row["quote_date_display"] = format_datetime(self.env, self.quote_date)
        return row

    @api.model
    def list_open_for_pos(self, payload):
        """Quotes the till can still add to a sale. Expired quotes are left out."""
        payload = payload or {}
        today = fields.Date.context_today(self)
        domain = [("valid_until", ">=", today)]
        company = self.env["res.company"].browse(payload.get("company_id")).exists()
        if company:
            domain.append(("company_id", "=", company.id))
        search = (payload.get("search") or "").strip()
        if search:
            domain = [
                "&",
                *([domain[0]] if len(domain) == 1 else ["&", *domain]),
                "|",
                ("name", "ilike", search),
                ("partner_id.name", "ilike", search),
            ]
        quotes = self.search(domain, limit=40, order="quote_date desc, id desc")
        return [quote._avea_pos_list_row() for quote in quotes]

    def get_for_sale(self):
        """Lines and customer for putting this quote on the current sale."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        if self.valid_until < today:
            raise UserError(_("This quote has expired."))
        currency = self.currency_id
        lines = []
        for line in self.line_ids.sorted(lambda row: (row.sequence, row.id)):
            pos_price = line.pos_price_unit
            if not pos_price:
                factor = 1 - (line.discount or 0.0) / 100.0
                if factor <= 0:
                    factor = 1
                pos_price = currency.round((line.price_unit or 0.0) / factor)
            lines.append(
                {
                    "product_id": line.product_id.id or False,
                    "name": line.name,
                    "quantity": line.quantity,
                    "discount": line.discount,
                    "pos_price_unit": pos_price,
                }
            )
        payload = self._avea_pos_payload()
        payload.update(
            {
                "partner_id": self.partner_id.id,
                "note": self.note or "",
                "lines": lines,
            }
        )
        return payload

    def _avea_format_qty(self, quantity):
        rounded = round(float(quantity or 0.0), 4)
        nearest = round(rounded)
        if abs(rounded - nearest) < 0.0001:
            return str(int(nearest))
        return f"{rounded:.4f}".rstrip("0").rstrip(".")

    def _avea_format_discount(self, discount):
        rounded = round(float(discount or 0.0), 2)
        if abs(rounded) < 0.001:
            return ""
        nearest = round(rounded)
        if abs(rounded - nearest) < 0.001:
            return str(int(nearest))
        return f"{rounded:.2f}".rstrip("0").rstrip(".")

    def _avea_partner_address(self, partner):
        city_line = " ".join(part for part in [partner.city, partner.zip] if part)
        state = partner.state_id.name if partner.state_id else ""
        parts = [partner.street, partner.street2, city_line, state]
        return ", ".join(part.strip() for part in parts if part and str(part).strip())

    def get_receipt(self):
        """Receipt-printer payload. Prices are the saved tax-inclusive till amounts."""
        self.ensure_one()
        currency = self.currency_id
        partner = self.partner_id
        lines = []
        for line in self.line_ids.sorted(lambda row: (row.sequence, row.id)):
            lines.append(
                {
                    "name": line.name,
                    "default_code": line.default_code or "",
                    "quantity": self._avea_format_qty(line.quantity),
                    "discount": self._avea_format_discount(line.discount),
                    "price_unit": formatLang(self.env, line.price_unit, currency_obj=currency),
                    "price_total": formatLang(self.env, line.price_total, currency_obj=currency),
                }
            )
        return {
            "name": self.name,
            "quote_date_display": format_datetime(self.env, self.quote_date),
            "valid_until_display": format_date(self.env, self.valid_until),
            "cashier_name": self.cashier_name or "",
            "note": self.note or "",
            "partner_name": partner.name or "",
            "partner_address": self._avea_partner_address(partner),
            "partner_vat": partner.vat or "",
            "partner_phone": partner.phone or getattr(partner, "mobile", "") or "",
            "amount_untaxed": formatLang(self.env, self.amount_untaxed, currency_obj=currency),
            "amount_tax": formatLang(self.env, self.amount_tax, currency_obj=currency),
            "amount_total": formatLang(self.env, self.amount_total, currency_obj=currency),
            "lines": lines,
        }

    def _avea_pdf_content(self):
        self.ensure_one()
        report = self.env.ref("avea_till.action_report_avea_pos_quote")
        pdf_content, _report_format = report.with_context(
            report_pdf_no_attachment=True
        )._render_qweb_pdf(
            "avea_till.report_avea_pos_quote_document",
            res_ids=self.ids,
        )
        if not pdf_content or not pdf_content.startswith(b"%PDF"):
            raise UserError(_("The quote PDF could not be created."))
        return pdf_content

    def get_pdf(self):
        """Return the quote PDF for the till to print or download."""
        self.ensure_one()
        filename = _("Quote-%s.pdf") % self.name
        return {
            "filename": filename,
            "pdf": base64.b64encode(self._avea_pdf_content()).decode(),
        }

    def _avea_email_body(self):
        self.ensure_one()
        partner = self.partner_id
        company = self.company_id
        business = company._avea_receipt_email_business_name()
        message = _(
            "Please find quote %(quote)s attached. It is valid until %(date)s. "
            "This is a quote, not a tax invoice, and stock is not reserved.",
            quote=self.name,
            date=format_date(self.env, self.valid_until),
        )
        return Markup("<p>{greeting}</p><p>{message}</p><p>{business}</p>").format(
            greeting=escape(_("Hello %s,") % (partner.name or "")),
            message=escape(message),
            business=escape(business or company.name or ""),
        )

    def action_send_email(self):
        """Email the quote PDF to the customer."""
        self.ensure_one()
        recipient = email_normalize((self.partner_id.email or "").strip())
        if not recipient:
            raise UserError(_("This customer has no email address. Download the PDF instead."))
        company = self.company_id
        sender_email = company._avea_receipt_email_sender_email()
        if not sender_email:
            raise UserError(
                _("Set the receipt sender email in Avea settings before emailing quotes.")
            )
        sender_name = company._avea_receipt_email_business_name()
        pdf_content = self._avea_pdf_content()
        attachment = self.env["ir.attachment"].sudo().create(
            {
                "name": _("Quote-%s.pdf") % self.name,
                "type": "binary",
                "datas": base64.b64encode(pdf_content),
                "mimetype": "application/pdf",
                "res_model": self._name,
                "res_id": self.id,
            }
        )
        mail = self.env["mail.mail"].sudo().create(
            {
                "subject": _("Quote %(quote)s from %(business)s")
                % {
                    "quote": self.name,
                    "business": sender_name or company.name,
                },
                "body_html": self._avea_email_body(),
                "email_from": formataddr((sender_name or company.name, sender_email)),
                "email_to": recipient,
                "reply_to": company._avea_receipt_email_reply_to() or sender_email,
                "attachment_ids": [(4, attachment.id)],
                "auto_delete": False,
            }
        )
        self.env["pos.order"]._avea_schedule_receipt_mail_delivery(mail.id)
        self.email_sent = True
        return {"email": recipient, "mail_id": mail.id}

    def action_send_email_backend(self):
        self.ensure_one()
        result = self.action_send_email()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Quote emailed"),
                "message": _("Sent to %s.", result["email"]),
                "type": "success",
                "sticky": False,
            },
        }


class AveaPosQuoteLine(models.Model):
    _name = "avea.pos.quote.line"
    _description = "POS Quote Line"
    _order = "sequence, id"

    quote_id = fields.Many2one(
        "avea.pos.quote",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related="quote_id.company_id")
    currency_id = fields.Many2one(related="quote_id.currency_id")
    product_id = fields.Many2one("product.product", string="Product", ondelete="set null")
    name = fields.Char(string="Description", required=True)
    default_code = fields.Char(string="SKU")
    quantity = fields.Float(string="Quantity", digits="Product Unit", required=True)
    discount = fields.Float(string="Discount %", digits="Discount")
    price_unit = fields.Monetary(
        string="Unit price",
        currency_field="currency_id",
        help="Unit price including tax, as shown on the till.",
    )
    pos_price_unit = fields.Monetary(
        string="Till unit price",
        currency_field="currency_id",
        help="The till price before discount, used when this quote is added to a sale.",
    )
    price_subtotal = fields.Monetary(string="Ex tax", currency_field="currency_id")
    price_tax = fields.Monetary(string="Tax", currency_field="currency_id")
    price_total = fields.Monetary(string="Total", currency_field="currency_id")
