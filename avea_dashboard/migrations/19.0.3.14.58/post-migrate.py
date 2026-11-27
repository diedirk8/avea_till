# -*- coding: utf-8 -*-
"""Backfill history_date on completed stock takes after the field is added."""


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    takes = env["avea.stock.take"].search([("state", "in", ("applied", "cancelled"))])
    if takes:
        takes._compute_history_date()
