"""Ensure printed receipt layout defaults for existing companies."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE res_company
           SET avea_print_receipt_layout = 'standard'
         WHERE avea_print_receipt_layout IS NULL
        """
    )
    if cr.rowcount:
        _logger.info(
            "Set default printed receipt layout on %s companies.",
            cr.rowcount,
        )
