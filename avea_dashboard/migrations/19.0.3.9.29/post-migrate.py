"""Apply receipt email redesign defaults for existing companies."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE res_company
           SET avea_receipt_email_layout = 'comfortable'
         WHERE avea_receipt_email_layout IS NULL
        """
    )
    if cr.rowcount:
        _logger.info(
            "Set default receipt email layout on %s companies.",
            cr.rowcount,
        )
