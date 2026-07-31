import io

import xlsxwriter
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AveaCreditActivityWizard(models.TransientModel):
    _name = "avea.credit.activity.wizard"
    _description = "Credit Activity Report Wizard"
    _inherit = ["avea.credit.report.mixin"]

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
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
    )
    reason_id = fields.Many2one(
        "avea.credit.reason",
        string="Credit Reason",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Employee",
    )

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise ValidationError(_("Date From must be on or before Date To."))

    def _get_activity_data(self):
        self.ensure_one()
        lines = self.env["avea.credit.ledger.entry"]._get_activity_lines(
            self.date_from,
            self.date_to,
            company=self.company_id,
            partner=self.partner_id,
            reason_id=self.reason_id,
            user_id=self.user_id,
        )
        return {
            "date_from": self.date_from,
            "date_to": self.date_to,
            "partner": self.partner_id,
            "reason": self.reason_id,
            "employee": self.user_id,
            "lines": lines,
            "company": self.company_id,
            "currency": self.currency_id,
        }

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref(
            "avea_till.action_report_avea_credit_activity"
        ).report_action(self)

    def action_export_xlsx(self):
        self.ensure_one()
        data = self._get_activity_data()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        worksheet = workbook.add_worksheet("Credit Activity")
        header_format = workbook.add_format({"bold": True})
        currency_format = workbook.add_format({"num_format": "#,##0.00"})
        date_format = workbook.add_format({"num_format": "yyyy-mm-dd hh:mm"})

        row = 0
        worksheet.write(row, 0, _("Credit Activity Report"), header_format)
        row += 1
        worksheet.write(row, 0, _("Period"))
        worksheet.write(row, 1, f"{data['date_from']} - {data['date_to']}")
        row += 2

        headers = [
            _("Date"),
            _("Customer"),
            _("Reason"),
            _("Reference"),
            _("Amount"),
            _("Employee"),
        ]
        self._write_xlsx_header(worksheet, headers, header_format)
        row += 1
        for line in data["lines"]:
            worksheet.write_datetime(
                row, 0, line["transaction_date"], date_format
            )
            worksheet.write(row, 1, line["partner"])
            worksheet.write(row, 2, line["reason"])
            worksheet.write(row, 3, line["name"])
            worksheet.write_number(row, 4, line["amount"], currency_format)
            worksheet.write(row, 5, line["employee"])
            row += 1
        workbook.close()
        return self._create_xlsx_download_action(
            "credit_activity_report.xlsx", output.getvalue()
        )

    @api.model
    def action_open_wizard(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Credit Activity Report"),
            "res_model": self._name,
            "view_mode": "form",
            "view_id": self.env.ref(
                "avea_till.view_avea_credit_activity_wizard_form"
            ).id,
            "target": "new",
        }
