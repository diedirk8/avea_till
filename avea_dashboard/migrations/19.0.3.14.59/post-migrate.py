# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    stock_takes = env["avea.stock.take"].search([("state", "=", "applied")])
    stock_takes._avea_backfill_line_report_data()
