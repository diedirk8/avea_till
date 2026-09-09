from odoo import api, models
from odoo.tools.mail import encapsulate_email, email_normalize


class IrMailServer(models.Model):
    _inherit = "ir.mail_server"

    @api.model
    def _prepare_email_message__(self, message, smtp_session):
        """Keep configured sender display names on outgoing mail.

        Odoo's SMTP layer replaces a formatted From header with the bare SMTP
        login address when both resolve to the same email. Preserve the human
        readable name (e.g. "Pets Empire") for receipt and other branded mail.
        """
        msg_from = message.get("From")
        session_from = getattr(smtp_session, "smtp_from", False) or msg_from
        if msg_from and session_from:
            norm_msg = email_normalize(msg_from)
            norm_session = email_normalize(session_from)
            if (
                norm_msg
                and norm_msg == norm_session
                and msg_from != session_from
            ):
                smtp_session.smtp_from = encapsulate_email(msg_from, session_from)
        return super()._prepare_email_message__(message, smtp_session)
