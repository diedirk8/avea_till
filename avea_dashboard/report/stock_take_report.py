# -*- coding: utf-8 -*-
from odoo import models


class ReportAveaStockTake(models.AbstractModel):
    _name = "report.avea_till.report_avea_stock_take"
    _description = "Avea Stock Take Report"

    def _get_report_values(self, docids, data=None):
        docs = self.env["avea.stock.take"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "avea.stock.take",
            "docs": docs,
            "data": data,
        }
