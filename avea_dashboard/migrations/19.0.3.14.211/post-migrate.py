# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Fill any FNB month that an empty in-progress recon had blocked."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env.invalidate_all()
    for company in env["res.company"].search([]):
        env["avea.bank.reconciliation"].with_company(company)._avea_ensure_brought_forward_recons()
