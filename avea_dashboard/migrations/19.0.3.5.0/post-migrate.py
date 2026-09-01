from collections import defaultdict

from odoo import SUPERUSER_ID, api


def _is_empty_draft(receive):
    return (
        receive.state == "draft"
        and not receive.line_ids
        and not receive.partner_id
        and not receive.invoice_number
    )


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Receive = env["avea.stock.receive"].sudo()

    Receive.search([("state", "=", "done"), ("bill_id", "=", False)]).write(
        {"state": "draft"}
    )

    cr.execute(
        """
        UPDATE avea_stock_receive
           SET user_id = create_uid
         WHERE user_id IS NULL
            OR user_id <> create_uid
        """
    )

    keep_ids = set()
    grouped = defaultdict(list)
    for receive in Receive.search([("state", "=", "draft")], order="write_date desc, id desc"):
        key = (receive.user_id.id, receive.company_id.id)
        grouped[key].append(receive)

    for drafts in grouped.values():
        keeper = next(
            (
                receive
                for receive in drafts
                if receive.line_ids or receive.partner_id or receive.invoice_number
            ),
            drafts[0] if drafts else None,
        )
        if keeper:
            keep_ids.add(keeper.id)
        for receive in drafts:
            if receive.id not in keep_ids and _is_empty_draft(receive):
                receive.unlink()
