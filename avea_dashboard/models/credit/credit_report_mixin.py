from datetime import datetime, time

from odoo import _, api, fields, models
from odoo.tools.misc import format_datetime


class AveaCreditReportMixin(models.AbstractModel):
    _name = "avea.credit.report.mixin"
    _description = "Customer Credit Report Helpers"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
    )

    @api.model
    def _date_to_datetime_start(self, date_value):
        if not date_value:
            return False
        return datetime.combine(date_value, time.min)

    @api.model
    def _date_to_datetime_end(self, date_value):
        if not date_value:
            return False
        return datetime.combine(date_value, time.max)

    @api.model
    def _format_amount(self, amount, currency=None):
        currency = currency or self.env.company.currency_id
        return currency.format(amount)

    @api.model
    def _format_statement_for_pdf(self, statement):
        """Pre-format monetary and datetime values for QWeb PDF rendering."""
        currency = statement["currency"]
        statement["opening_balance_formatted"] = self._format_amount(
            statement["opening_balance"], currency
        )
        statement["closing_balance_formatted"] = self._format_amount(
            statement["closing_balance"], currency
        )
        for line in statement["lines"]:
            line["transaction_date_formatted"] = format_datetime(
                self.env, line["transaction_date"]
            )
            line["credit_added_formatted"] = (
                self._format_amount(line["credit_added"], currency)
                if line["credit_added"]
                else ""
            )
            line["credit_used_formatted"] = (
                self._format_amount(line["credit_used"], currency)
                if line["credit_used"]
                else ""
            )
            line["running_balance_formatted"] = self._format_amount(
                line["running_balance"], currency
            )
        return statement

    def _create_xlsx_download_action(self, filename, content):
        import base64

        attachment = self.env["ir.attachment"].create(
            {
                "name": filename,
                "type": "binary",
                "datas": base64.b64encode(content),
                "mimetype": (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
                "res_model": self._name,
                "res_id": self.id,
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def _write_xlsx_header(self, worksheet, headers, header_format):
        for column, header in enumerate(headers):
            worksheet.write(0, column, header, header_format)

    def _write_xlsx_amount(self, worksheet, row, column, amount, currency_format):
        worksheet.write_number(row, column, amount or 0.0, currency_format)
