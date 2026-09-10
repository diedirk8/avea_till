import logging
import re

from odoo import api, fields, models
from odoo.tools import email_normalize, formataddr

_logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")


class PosOrder(models.Model):
    _inherit = "pos.order"

    avea_receipt_email_sent = fields.Boolean(
        string="Avea Receipt Email Sent",
        copy=False,
        readonly=True,
        default=False,
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
        name = company._avea_receipt_email_business_name()
        email = company._avea_receipt_email_sender_email()
        if not email:
            return False, False
        return name or company.name, email

    def _avea_receipt_email_from(self):
        self.ensure_one()
        name, email = self._avea_receipt_sender_identity()
        if not email:
            return False
        return formataddr((name, email))

    def _avea_claim_receipt_email_send(self):
        """Atomically claim this order so concurrent POS calls cannot double-send."""
        self.ensure_one()
        self.env.cr.execute(
            """
            UPDATE pos_order
               SET avea_receipt_email_sent = TRUE
             WHERE id = %s
               AND COALESCE(avea_receipt_email_sent, FALSE) = FALSE
         RETURNING id
            """,
            [self.id],
        )
        if not self.env.cr.fetchone():
            return False
        self.invalidate_recordset(["avea_receipt_email_sent"])
        return True

    def _avea_release_receipt_email_send_claim(self):
        self.ensure_one()
        self.write({"avea_receipt_email_sent": False})

    @api.model
    def _avea_deliver_receipt_mail(self, mail_id):
        """Send a queued receipt mail in a dedicated transaction."""
        if not mail_id:
            return False
        registry = self.env.registry
        dbname = self.env.cr.dbname
        with registry.cursor() as cr:
            env = api.Environment(cr, api.SUPERUSER_ID, {})
            mail = env["mail.mail"].browse(mail_id).exists()
            if not mail or mail.state != "outgoing":
                return False
            mail.send()
            cr.commit()
        _logger.info(
            "Avea receipt email dispatched (mail.mail #%s, db=%s)",
            mail_id,
            dbname,
        )
        return True

    @api.model
    def _avea_schedule_receipt_mail_delivery(self, mail_id):
        """Deliver queued receipt mail after the POS RPC transaction commits."""
        if not mail_id:
            return

        registry = self.env.registry

        def _send_after_commit():
            try:
                with registry.cursor() as cr:
                    env = api.Environment(cr, api.SUPERUSER_ID, {})
                    env["pos.order"]._avea_deliver_receipt_mail(mail_id)
            except Exception:
                _logger.exception(
                    "Failed to deliver Avea receipt email (mail.mail #%s)",
                    mail_id,
                )
                try:
                    with registry.cursor() as cr:
                        env = api.Environment(cr, api.SUPERUSER_ID, {})
                        cron = env.ref(
                            "mail.ir_cron_mail_scheduler_action",
                            raise_if_not_found=False,
                        )
                        if cron:
                            cron._trigger()
                        cr.commit()
                except Exception:
                    _logger.exception(
                        "Failed to trigger mail cron after receipt email error"
                    )

        self.env.cr.postcommit.add(_send_after_commit)

    def avea_send_receipt_email_automatic(self):
        """Queue the Avea receipt email as lightweight HTML.

        Called from POS after payment in the background. Must return quickly and
        must never block order validation on the client.
        """
        self.ensure_one()
        reference = self.pos_reference or self.name or self.id
        company = self.company_id
        if not company.avea_auto_email_receipt:
            _logger.info(
                "Skipping Avea receipt email for order %s: setting disabled.",
                reference,
            )
            return False
        recipient = self._avea_valid_customer_email()
        if not recipient:
            _logger.info(
                "Skipping Avea receipt email for order %s: customer has no valid email.",
                reference,
            )
            return False
        email_from = self._avea_receipt_email_from()
        if not email_from:
            _logger.warning(
                "Skipping Avea receipt email for order %s: business sender email is not configured.",
                reference,
            )
            return False
        template = self.env.ref(
            "avea_till.email_template_avea_pos_receipt",
            raise_if_not_found=False,
        )
        if not template:
            _logger.error(
                "Skipping Avea receipt email for order %s: template missing.",
                reference,
            )
            return False
        if not self._avea_claim_receipt_email_send():
            _logger.info(
                "Skipping Avea receipt email for order %s: already sent or claimed.",
                reference,
            )
            return False
        try:
            reply_to = company._avea_receipt_email_reply_to() or email_from
            email_values = {
                "email_to": recipient,
                "email_from": email_from,
                "reply_to": reply_to,
                "subject": company._avea_receipt_email_subject_render(self),
                "body_html": company._avea_receipt_email_body_html(self),
                "attachment_ids": [(5, 0, 0)],
            }
            mail_id = template.send_mail(
                self.id,
                force_send=False,
                email_values=email_values,
            )
            if not mail_id:
                self._avea_release_receipt_email_send_claim()
                _logger.error(
                    "Failed to queue Avea receipt email for order %s: send_mail returned no id.",
                    reference,
                )
                return False
            self._avea_schedule_receipt_mail_delivery(mail_id)
            _logger.info(
                "Queued Avea receipt email for order %s to %s (mail.mail #%s).",
                reference,
                recipient,
                mail_id,
            )
        except Exception:
            self._avea_release_receipt_email_send_claim()
            _logger.exception(
                "Failed to queue Avea receipt email for POS order %s",
                reference,
            )
            return False
        return True
