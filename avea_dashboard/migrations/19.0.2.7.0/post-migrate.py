"""Migrate legacy ledger reason codes to configurable credit reasons."""

LEGACY_REASON_COLUMN = "reason_legacy"

LEGACY_REASON_MAP = {
    "refund": {
        "name": "Refund",
        "manual_issue": False,
        "system_generated": True,
        "is_outflow": False,
        "xmlid": "avea_till.credit_reason_refund",
    },
    "purchase": {
        "name": "POS Purchase",
        "manual_issue": False,
        "system_generated": True,
        "is_outflow": True,
        "xmlid": "avea_till.credit_reason_pos_purchase",
    },
    "goodwill": {
        "name": "Goodwill",
        "manual_issue": True,
        "system_generated": False,
        "is_outflow": False,
        "xmlid": "avea_till.credit_reason_goodwill",
    },
    "promotion": {
        "name": "Promotion",
        "manual_issue": True,
        "system_generated": False,
        "is_outflow": False,
        "xmlid": "avea_till.credit_reason_promotion",
    },
    "adjustment": {
        "name": "Adjustment",
        "manual_issue": False,
        "system_generated": False,
        "is_outflow": False,
    },
    "birthday": {
        "name": "Birthday",
        "manual_issue": True,
        "system_generated": False,
        "is_outflow": False,
    },
    "other": {
        "name": "Other",
        "manual_issue": False,
        "system_generated": False,
        "is_outflow": False,
    },
}


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    Reason = env["avea.credit.reason"].with_context(active_test=False)

    cr.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'avea_credit_ledger_entry'
        """
    )
    columns = {row[0] for row in cr.fetchall()}
    if LEGACY_REASON_COLUMN not in columns:
        return

    def _resolve_reason(old_code):
        mapping = LEGACY_REASON_MAP.get(old_code)
        if not mapping:
            mapping = {
                "name": old_code.replace("_", " ").title(),
                "manual_issue": False,
                "system_generated": False,
                "is_outflow": False,
            }

        reason = False
        xmlid = mapping.get("xmlid")
        if xmlid:
            reason = env.ref(xmlid, raise_if_not_found=False)

        if not reason:
            reason = Reason.search([("name", "=", mapping["name"])], limit=1)

        if not reason:
            reason = Reason.create(
                {
                    "name": mapping["name"],
                    "manual_issue": mapping["manual_issue"],
                    "system_generated": mapping["system_generated"],
                    "is_outflow": mapping["is_outflow"],
                }
            )
        return reason

    cr.execute(
        f"""
        SELECT id, {LEGACY_REASON_COLUMN}
        FROM avea_credit_ledger_entry
        WHERE {LEGACY_REASON_COLUMN} IS NOT NULL
          AND reason_id IS NULL
        """
    )
    for entry_id, old_code in cr.fetchall():
        reason = _resolve_reason(old_code)
        cr.execute(
            """
            UPDATE avea_credit_ledger_entry
            SET reason_id = %s
            WHERE id = %s
            """,
            (reason.id, entry_id),
        )

    cr.execute(
        f"""
        ALTER TABLE avea_credit_ledger_entry
        DROP COLUMN IF EXISTS {LEGACY_REASON_COLUMN}
        """
    )

    cr.execute(
        """
        SELECT DISTINCT partner_id
        FROM avea_credit_ledger_entry
        WHERE partner_id IS NOT NULL
        """
    )
    partner_ids = [row[0] for row in cr.fetchall()]
    if partner_ids:
        env["res.partner"].browse(partner_ids)._compute_avea_credit_balance()
