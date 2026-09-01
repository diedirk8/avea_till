"""Restore Product Price display precision after optional manual 4-decimal change."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE decimal_precision
           SET digits = 2
         WHERE name = 'Product Price'
           AND digits > 2
        """
    )
    if cr.rowcount:
        _logger.info(
            "Reset Product Price decimal accuracy back to 2 (was temporarily raised)."
        )
