# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Show May–August FNB recons and start the next one from August’s close."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env.invalidate_all()
    for company in env["res.company"].search([]):
        env["avea.bank.reconciliation"].with_company(company)._avea_ensure_brought_forward_recons()
