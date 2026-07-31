import io

import xlsxwriter
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AveaCreditStatementWizard(models.TransientModel):
    _name = "avea.credit.statement.wizard"
    _description = "Customer Credit Statement Wizard"
    _inherit = ["avea.credit.report.mixin"]

    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
    )
    date_from = fields.Date(
        string="Date From",
        required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1),
    )
    date_to = fields.Date(
        string="Date To",
        required=True,
        default=fields.Date.context_today,
    )

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise ValidationError(_("Date From must be on or before Date To."))

    def _get_statement_data(self):
        self.ensure_one()
        Ledger = self.env["avea.credit.ledger.entry"]
        statement = Ledger._get_statement_lines(
            self.partner_id,
            self.date_from,
            self.date_to,
            company=self.company_id,
        )
        statement.update(
            {
                "partner": self.partner_id,
                "date_from": self.date_from,
                "date_to": self.date_to,
                "company": self.company_id,
                "currency": self.currency_id,
            }
        )
        return statement

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref(
            "avea_till.action_report_avea_credit_statement"
        ).report_action(self)

    def action_export_xlsx(self):
        self.ensure_one()
        data = self._get_statement_data()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        worksheet = workbook.add_worksheet("Credit Statement")
        header_format = workbook.add_format({"bold": True})
        currency_format = workbook.add_format({"num_format": "#,##0.00"})
        date_format = workbook.add_format({"num_format": "yyyy-mm-dd hh:mm"})

        row = 0
        worksheet.write(row, 0, _("Customer Credit Statement"), header_format)
        row += 1
        worksheet.write(row, 0, _("Customer"))
        worksheet.write(row, 1, data["partner"].display_name)
        row += 1
        worksheet.write(row, 0, _("Period"))
        worksheet.write(
            row,
            1,
            f"{data['date_from']} - {data['date_to']}",
        )
        row += 2
        worksheet.write(row, 0, _("Opening Balance"))
        worksheet.write_number(row, 1, data["opening_balance"], currency_format)
        row += 2

        headers = [
            _("Date"),
            _("Reference"),
            _("Reason"),
            _("Credit Added"),
            _("Credit Used"),
            _("Running Balance"),
        ]
        self._write_xlsx_header(worksheet, headers, header_format)
        row += 1
        for line in data["lines"]:
            worksheet.write_datetime(
                row, 0, line["transaction_date"], date_format
            )
            worksheet.write(row, 1, line["name"])
            worksheet.write(row, 2, line["reason"])
            self._write_xlsx_amount(
                worksheet, row, 3, line["credit_added"], currency_format
            )
            self._write_xlsx_amount(
                worksheet, row, 4, line["credit_used"], currency_format
            )
            self._write_xlsx_amount(
                worksheet, row, 5, line["running_balance"], currency_format
            )
            row += 1
        row += 1
        worksheet.write(row, 0, _("Closing Balance"), header_format)
        worksheet.write_number(row, 1, data["closing_balance"], currency_format)
        workbook.close()

        filename = f"credit_statement_{self.partner_id.display_name}.xlsx"
        return self._create_xlsx_download_action(filename, output.getvalue())

    @api.model
    def action_open_wizard(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Customer Credit Statement"),
            "res_model": self._name,
            "view_mode": "form",
            "view_id": self.env.ref(
                "avea_till.view_avea_credit_statement_wizard_form"
            ).id,
            "target": "new",
        }
