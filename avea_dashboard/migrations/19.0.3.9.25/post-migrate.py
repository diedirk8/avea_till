"""Normalize receipt-email sent flag for legacy POS orders."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE pos_order
           SET avea_receipt_email_sent = FALSE
         WHERE avea_receipt_email_sent IS NULL
        """
    )
    if cr.rowcount:
        _logger.info(
            "Normalized avea_receipt_email_sent on %s legacy POS orders.",
            cr.rowcount,
        )
