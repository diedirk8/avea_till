import base64
import io
import re

from odoo import api, fields, models
from odoo.tools import email_normalize, formataddr
from odoo.tools.misc import formatLang

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is bundled with Odoo
    Image = None


_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")


class PosOrder(models.Model):
    _inherit = "pos.order"

    avea_receipt_email_sent = fields.Boolean(
        string="Avea Receipt Email Sent",
        copy=False,
        readonly=True,
    )

    @api.model
    def sync_from_ui(self, orders):
        sanitized = []
        for order in orders:
            payload = dict(order)
            payload["to_invoice"] = False
            sanitized.append(payload)
        return super().sync_from_ui(sanitized)

    def _avea_valid_customer_email(self):
        self.ensure_one()
        partner = self.partner_id
        if not partner or not partner.email:
            return False
        normalized = email_normalize(partner.email.strip())
        if not normalized or not _EMAIL_RE.match(normalized):
            return False
        return normalized

    def _avea_receipt_sender_identity(self):
        self.ensure_one()
        company = self.company_id
        name = (company.avea_receipt_sender_name or company.name or "").strip()
        email = (
            company.avea_receipt_sender_email
            or company.email
            or company.partner_id.email
            or ""
        ).strip()
        normalized = email_normalize(email) if email else False
        if not normalized:
            return False, False
        return name or company.name, normalized

    def _avea_receipt_email_from(self):
        self.ensure_one()
        name, email = self._avea_receipt_sender_identity()
        if not email:
            return False
        return formataddr((name, email))

    def _avea_receipt_payment_rows(self):
        self.ensure_one()
        rows = []
        for payment in self.payment_ids.filtered(lambda line: not line.is_change):
            rows.append(
                {
                    "name": payment.payment_method_id.name,
                    "amount": formatLang(
                        self.env,
                        payment.amount,
                        currency_obj=self.currency_id,
                    ),
                }
            )
        return rows

    def _avea_receipt_jpeg_to_pdf(self, ticket_image_b64):
        self.ensure_one()
        if not Image:
            return False
        if not ticket_image_b64:
            return False
        try:
            image_bytes = base64.b64decode(ticket_image_b64)
            image = Image.open(io.BytesIO(image_bytes))
        except (ValueError, OSError):
            return False
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
        pdf_buffer = io.BytesIO()
        image.save(pdf_buffer, format="PDF")
        return base64.b64encode(pdf_buffer.getvalue())

    def _avea_receipt_pdf_attachment(self, ticket_image_b64):
        self.ensure_one()
        pdf_b64 = self._avea_receipt_jpeg_to_pdf(ticket_image_b64)
        if not pdf_b64:
            return self.env["ir.attachment"]
        reference = self.pos_reference or self.name or str(self.id)
        return self.env["ir.attachment"].create(
            {
                "name": f"Receipt-{reference}.pdf",
                "type": "binary",
                "datas": pdf_b64,
                "res_model": "pos.order",
                "res_id": self.id,
                "mimetype": "application/pdf",
            }
        )

    def avea_send_receipt_email_automatic(self, ticket_image_b64):
        """Send the Avea receipt email with the printed POS receipt attached as PDF.

        The POS client renders the same ``OrderReceipt`` component used for
        printing, then passes the JPEG here for PDF attachment.
        """
        self.ensure_one()
        if self.avea_receipt_email_sent:
            return False
        if not self.company_id.avea_auto_email_receipt:
            return False
        recipient = self._avea_valid_customer_email()
        if not recipient:
            return False
        email_from = self._avea_receipt_email_from()
        if not email_from:
            return False
        template = self.env.ref(
            "avea_till.email_template_avea_pos_receipt",
            raise_if_not_found=False,
        )
        if not template:
            return False
        attachment = self._avea_receipt_pdf_attachment(ticket_image_b64)
        email_values = {
            "email_to": recipient,
            "email_from": email_from,
            "reply_to": email_from,
        }
        if attachment:
            email_values["attachment_ids"] = [(4, attachment.id)]
        template.send_mail(self.id, force_send=True, email_values=email_values)
        self.avea_receipt_email_sent = True
        return True
