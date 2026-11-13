"""Default POS product list to 50 items per page for easier staff browsing."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE pos_config
           SET avea_products_per_page = '50'
         WHERE avea_products_per_page IS NULL
            OR avea_products_per_page = '10'
        """
    )
    if cr.rowcount:
        _logger.info(
            "Set POS products per page to 50 on %s point(s) of sale.",
            cr.rowcount,
        )
