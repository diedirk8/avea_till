# -*- coding: utf-8 -*-
import base64
import io

from odoo import fields
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


@tagged("post_install", "-at_install", "avea_till")
class TestAveaSettingsReceiptEmail(TestPoSCommon):
    """Avea Settings receipt email behaviour after POS sales."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.config.write({"payment_method_ids": [(6, 0, cls.cash_pm1.ids)]})
        cls.product = cls.create_product(
            "Receipt Test Product", cls.categ_basic, 25.0, 10.0
        )
        cls.company = cls.env.company
        cls.company.write(
            {
                "avea_auto_email_receipt": True,
                "avea_receipt_sender_name": "Avea Test Business",
                "avea_receipt_sender_email": "receipts@aveatest.local",
                "email": "receipts@aveatest.local",
            }
        )
        cls.customer_with_email = cls.env["res.partner"].create(
            {
                "name": "Receipt Customer",
                "email": "customer@example.com",
            }
        )
        cls.customer_without_email = cls.env["res.partner"].create(
            {
                "name": "Walk-in Customer",
            }
        )
        cls.cashier_user = cls.env["res.users"].create(
            {
                "name": "POS Cashier Test",
                "login": "pos_cashier_receipt_test@dev.local",
                "email": "cashier@example.com",
                "group_ids": [
                    (6, 0, [cls.env.ref("point_of_sale.group_pos_user").id])
                ],
            }
        )

    @classmethod
    def _sample_receipt_jpeg_b64(cls):
        image = Image.new("RGB", (320, 480), color="white")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        return base64.b64encode(buffer.getvalue()).decode()

    def _create_paid_order(self, *, customer=False, is_invoiced=False, uuid="receipt-test"):
        session = self.open_new_session(0)
        total = self.product.lst_price
        order_data = self.create_ui_order_data(
            pos_order_lines_ui_args=[(self.product, 1)],
            payments=[(self.cash_pm1, total)],
            customer=customer,
            is_invoiced=is_invoiced,
            uuid=uuid,
        )
        order_data["user_id"] = self.cashier_user.id
        sync_result = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(sync_result["pos.order"][0]["id"])
        self.assertEqual(order.state, "paid")
        return order

    def _send_receipt_email(self, order):
        return order.avea_send_receipt_email_automatic(self._sample_receipt_jpeg_b64())

    def _latest_mail_for(self, email_to):
        return self.env["mail.mail"].search(
            [("email_to", "=", email_to)],
            order="id desc",
            limit=1,
        )

    def test_setting_on_sends_receipt_to_customer_with_email(self):
        order = self._create_paid_order(
            customer=self.customer_with_email,
            uuid="receipt-on-with-email",
        )
        self.assertTrue(self._send_receipt_email(order))
        mail = self._latest_mail_for("customer@example.com")
        self.assertTrue(mail)
        self.assertTrue(order.avea_receipt_email_sent)
        self.assertIn(self.product.display_name, mail.body_html)
        self.assertIn(order.pos_reference or order.name, mail.body_html)
        self.assertIn("Avea Test Business", mail.email_from)
        self.assertNotIn(self.cashier_user.name, mail.email_from)
        self.assertFalse(order.account_move)

    def test_setting_on_attaches_printed_receipt_as_pdf(self):
        order = self._create_paid_order(
            customer=self.customer_with_email,
            uuid="receipt-pdf-attachment",
        )
        self._send_receipt_email(order)
        mail = self._latest_mail_for("customer@example.com")
        pdf_attachments = mail.attachment_ids.filtered(
            lambda attachment: attachment.mimetype == "application/pdf"
        )
        self.assertEqual(len(pdf_attachments), 1)
        self.assertTrue(pdf_attachments.name.endswith(".pdf"))

    def test_sync_without_pos_receipt_does_not_email(self):
        order = self._create_paid_order(
            customer=self.customer_with_email,
            uuid="receipt-no-client-send",
        )
        self.assertFalse(order.avea_receipt_email_sent)
        self.assertFalse(self._latest_mail_for("customer@example.com"))

    def test_setting_off_does_not_send_receipt(self):
        self.company.avea_auto_email_receipt = False
        order = self._create_paid_order(
            customer=self.customer_with_email,
            uuid="receipt-off-with-email",
        )
        self.assertFalse(self._send_receipt_email(order))
        mail = self._latest_mail_for("customer@example.com")
        self.assertFalse(mail)
        self.assertFalse(order.avea_receipt_email_sent)

    def test_customer_without_email_does_not_send(self):
        before = self.env["mail.mail"].search_count([])
        order = self._create_paid_order(
            customer=self.customer_without_email,
            uuid="receipt-no-email",
        )
        self.assertFalse(self._send_receipt_email(order))
        after = self.env["mail.mail"].search_count([])
        self.assertEqual(before, after)
        self.assertFalse(order.avea_receipt_email_sent)

    def test_no_customer_does_not_send(self):
        order = self._create_paid_order(uuid="receipt-no-customer")
        self.assertFalse(self._send_receipt_email(order))
        self.assertFalse(order.avea_receipt_email_sent)

    def test_invoice_flag_from_pos_is_ignored(self):
        order = self._create_paid_order(
            customer=self.customer_with_email,
            is_invoiced=True,
            uuid="receipt-ignore-invoice",
        )
        self.assertFalse(order.to_invoice)
        self.assertFalse(order.account_move)

    def test_receipt_contains_payment_method_and_total(self):
        order = self._create_paid_order(
            customer=self.customer_with_email,
            uuid="receipt-contents",
        )
        self._send_receipt_email(order)
        mail = self._latest_mail_for("customer@example.com")
        self.assertIn(self.cash_pm1.name, mail.body_html)
        self.assertIn("Total", mail.body_html)

    def test_settings_workspace_opens(self):
        action = self.env["avea.business.settings"].action_open_avea_settings()
        self.assertEqual(action["res_model"], "avea.business.settings")
        self.assertTrue(action["context"].get("clear_breadcrumbs"))
        settings = self.env["avea.business.settings"].browse(action["res_id"])
        self.assertEqual(settings.company_id, self.company)
        settings.avea_receipt_sender_name = "Updated Business Name"
        self.assertEqual(self.company.avea_receipt_sender_name, "Updated Business Name")
