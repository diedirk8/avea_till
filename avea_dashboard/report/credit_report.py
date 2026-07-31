from odoo import api, models


class ReportAveaCreditReportMixin(models.AbstractModel):
    _name = "report.avea_till.credit_report.mixin"
    _description = "Avea Customer Credit Report Branding"

    @api.model
    def _get_avea_credit_report_branding(self):
        module = self.env["ir.module.module"].sudo().search(
            [("name", "=", "avea_till")],
            limit=1,
        )
        return {
            "avea_report_branding": True,
            "avea_module_name": "Avea Dashboard",
            "avea_feature_name": "Customer Credit",
            "avea_module_version": module.installed_version if module else "",
        }


class ReportAveaCreditStatement(models.AbstractModel):
    _name = "report.avea_till.report_avea_credit_statement"
    _description = "Customer Credit Statement Report"
    _inherit = ["report.avea_till.credit_report.mixin"]

    @api.model
    def _get_report_values(self, docids, data=None):
        wizards = self.env["avea.credit.statement.wizard"].browse(docids)
        report_helpers = self.env["avea.credit.report.mixin"]
        values = {
            "doc_ids": docids,
            "doc_model": "avea.credit.statement.wizard",
            "docs": wizards,
            "report_data": [
                report_helpers._format_statement_for_pdf(
                    wizard._get_statement_data()
                )
                for wizard in wizards
            ],
        }
        values.update(self._get_avea_credit_report_branding())
        return values


class ReportAveaCreditOutstanding(models.AbstractModel):
    _name = "report.avea_till.report_avea_credit_outstanding"
    _description = "Outstanding Customer Credit Report"
    _inherit = ["report.avea_till.credit_report.mixin"]

    @api.model
    def _get_report_values(self, docids, data=None):
        wizards = self.env["avea.credit.outstanding.wizard"].browse(docids)
        values = {
            "doc_ids": docids,
            "doc_model": "avea.credit.outstanding.wizard",
            "docs": wizards,
            "report_data": [wizard._get_outstanding_data() for wizard in wizards],
        }
        values.update(self._get_avea_credit_report_branding())
        return values


class ReportAveaCreditActivity(models.AbstractModel):
    _name = "report.avea_till.report_avea_credit_activity"
    _description = "Credit Activity Report"
    _inherit = ["report.avea_till.credit_report.mixin"]

    @api.model
    def _get_report_values(self, docids, data=None):
        wizards = self.env["avea.credit.activity.wizard"].browse(docids)
        values = {
            "doc_ids": docids,
            "doc_model": "avea.credit.activity.wizard",
            "docs": wizards,
            "report_data": [wizard._get_activity_data() for wizard in wizards],
        }
        values.update(self._get_avea_credit_report_branding())
        return values
