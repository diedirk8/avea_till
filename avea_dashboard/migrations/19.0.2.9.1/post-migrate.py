"""Ensure protected is set on all existing credit reasons."""

def migrate(cr, version):
    cr.execute(
        """
        UPDATE avea_credit_reason
        SET protected = TRUE
        WHERE system_generated = TRUE
        """
    )
    cr.execute(
        """
        UPDATE avea_credit_reason
        SET protected = FALSE
        WHERE protected IS NULL
        """
    )
