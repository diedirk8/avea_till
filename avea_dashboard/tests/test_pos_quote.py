# -*- coding: utf-8 -*-
import base64
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_pos_quote")
class TestAveaPosQuote(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Zzqx Quote Customer",
                "email": "zzqx.quote@example.com",
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Zzqx Quote Kibble 2kg",
                "type": "consu",
                "is_storable": True,
                "list_price": 100.0,
                "available_in_pos": True,
                "sale_ok": True,
                "default_code": "ZZQX-Q-2",
            }
        )
        cls.env.company.write(
            {
                "avea_receipt_sender_email": "quotes@example.com",
                "avea_receipt_sender_name": "Pets Empire Test",
            }
        )

    def _payload(self, **extra):
        values = {
            "partner_id": self.partner.id,
            "cashier_name": "Till One",
            "note": "Call before you come in",
            "lines": [
                {
                    "product_id": self.product.id,
                    "name": self.product.display_name,
                    "default_code": "ZZQX-Q-2",
                    "quantity": 2,
                    "discount": 0,
                    "price_unit": 115.0,
                    "price_subtotal": 200.0,
                    "price_total": 230.0,
                }
            ],
        }
        values.update(extra)
        return values

    def test_quote_saves_totals_and_does_not_sell(self):
        moves_before = self.env["stock.move"].search_count([])
        orders_before = self.env["pos.order"].search_count([])
        result = self.env["avea.pos.quote"].create_from_pos(self._payload())
        quote = self.env["avea.pos.quote"].browse(result["id"])
        self.assertTrue(quote.name.startswith("Q"))
        self.assertEqual(quote.partner_id, self.partner)
        self.assertEqual(quote.amount_untaxed, 200.0)
        self.assertEqual(quote.amount_tax, 30.0)
        self.assertEqual(quote.amount_total, 230.0)
        self.assertEqual(quote.line_ids.default_code, "ZZQX-Q-2")
        self.assertEqual(
            quote.valid_until,
            fields.Date.add(fields.Date.context_today(quote), days=14),
        )
        self.assertEqual(self.env["stock.move"].search_count([]), moves_before)
        self.assertEqual(self.env["pos.order"].search_count([]), orders_before)
        self.assertIn(quote.name, result["name"])

    def test_quote_requires_a_customer_and_a_product(self):
        with self.assertRaises(UserError):
            self.env["avea.pos.quote"].create_from_pos(self._payload(partner_id=False))
        with self.assertRaises(UserError):
            self.env["avea.pos.quote"].create_from_pos(self._payload(lines=[]))

    def test_quote_pdf_and_email(self):
        result = self.env["avea.pos.quote"].create_from_pos(self._payload())
        # Odoo skips wkhtmltopdf during tests unless this context is set.
        quote = self.env["avea.pos.quote"].browse(result["id"]).with_context(
            force_report_rendering=True
        )
        pdf = quote.get_pdf()
        self.assertTrue(pdf["filename"].endswith(".pdf"))
        content = base64.b64decode(pdf["pdf"])
        self.assertTrue(content.startswith(b"%PDF"))
        with patch.object(
            type(self.env["pos.order"]),
            "_avea_schedule_receipt_mail_delivery",
            lambda self, mail_id: None,
        ):
            sent = quote.action_send_email()
        self.assertEqual(sent["email"], "zzqx.quote@example.com")
        self.assertTrue(quote.email_sent)
        mail = self.env["mail.mail"].browse(sent["mail_id"])
        self.assertEqual(mail.email_to, "zzqx.quote@example.com")
        self.assertTrue(mail.attachment_ids)
        attachment = base64.b64decode(mail.attachment_ids.datas)
        self.assertTrue(attachment.startswith(b"%PDF"))
        self.assertIn(quote.name, mail.subject)
        quote_without_email = self.env["avea.pos.quote"].create_from_pos(
            self._payload(
                partner_id=self.env["res.partner"].create({"name": "Zzqx No Email"}).id
            )
        )
        with self.assertRaises(UserError):
            self.env["avea.pos.quote"].browse(quote_without_email["id"]).action_send_email()
