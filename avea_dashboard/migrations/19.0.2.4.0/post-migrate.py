def migrate(cr, version):
    """Backfill stored store credit balances from existing ledger entries."""
    cr.execute(
        """
        SELECT DISTINCT partner_id
        FROM avea_credit_ledger_entry
        WHERE partner_id IS NOT NULL
        """
    )
    partner_ids = [row[0] for row in cr.fetchall()]
    if not partner_ids:
        return

    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    env["res.partner"].browse(partner_ids)._compute_avea_credit_balance()
