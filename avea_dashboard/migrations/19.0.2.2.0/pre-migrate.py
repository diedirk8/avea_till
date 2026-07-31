"""Rename transaction_type to reason and map legacy selection values."""

_LEGACY_REASON_MAP = {
    "spend": "purchase",
    "adjust": "adjustment",
    "issue": "other",
}


def migrate(cr, version):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'avea_credit_ledger_entry'
           AND column_name = 'transaction_type'
        """
    )
    if not cr.fetchone():
        return

    for old_value, new_value in _LEGACY_REASON_MAP.items():
        cr.execute(
            """
            UPDATE avea_credit_ledger_entry
               SET transaction_type = %s
             WHERE transaction_type = %s
            """,
            (new_value, old_value),
        )

    cr.execute(
        """
        ALTER TABLE avea_credit_ledger_entry
       RENAME COLUMN transaction_type TO reason
        """
    )
