"""Prepare ledger table for reason selection to Many2one migration."""

LEGACY_REASON_COLUMN = "reason_legacy"


def migrate(cr, version):
    cr.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'avea_credit_ledger_entry'
        """
    )
    columns = {row[0] for row in cr.fetchall()}

    if "reason_id" not in columns:
        cr.execute(
            """
            ALTER TABLE avea_credit_ledger_entry
            ADD COLUMN reason_id INTEGER
            """
        )

    if "reason" in columns and LEGACY_REASON_COLUMN not in columns:
        cr.execute(
            f"""
            ALTER TABLE avea_credit_ledger_entry
            RENAME COLUMN reason TO {LEGACY_REASON_COLUMN}
            """
        )
