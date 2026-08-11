def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    Session = env["pos.session"]
    Movement = env["avea.till.movement"]
    sessions = Session.search([("statement_line_ids", "!=", False)])
    for session in sessions:
        Movement.prepare_session_ledger(session)
