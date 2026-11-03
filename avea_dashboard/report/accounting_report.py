from odoo import api, models


class ReportAveaAccountingProfitLoss(models.AbstractModel):
    _name = "report.avea_till.report_avea_accounting_profit_loss"
    _description = "Profit and loss PDF"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["avea.accounting.profit.loss"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "avea.accounting.profit.loss",
            "docs": docs,
            "payloads": [doc._accounting_pdf_payload() for doc in docs],
        }


class ReportAveaAccountingBalanceSheet(models.AbstractModel):
    _name = "report.avea_till.report_avea_accounting_balance_sheet"
    _description = "Balance sheet PDF"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["avea.accounting.balance.sheet"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "avea.accounting.balance.sheet",
            "docs": docs,
            "payloads": [doc._accounting_pdf_payload() for doc in docs],
        }


class ReportAveaAccountingTrialBalance(models.AbstractModel):
    _name = "report.avea_till.report_avea_accounting_trial_balance"
    _description = "Trial balance PDF"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["avea.accounting.trial.balance"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "avea.accounting.trial.balance",
            "docs": docs,
            "payloads": [doc._accounting_pdf_payload() for doc in docs],
        }


class ReportAveaAccountingGeneralLedger(models.AbstractModel):
    _name = "report.avea_till.report_avea_accounting_general_ledger"
    _description = "General ledger PDF"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["avea.accounting.general.ledger"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "avea.accounting.general.ledger",
            "docs": docs,
            "payloads": [doc._accounting_pdf_payload() for doc in docs],
        }
