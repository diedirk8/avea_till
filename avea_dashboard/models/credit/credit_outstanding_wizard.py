import io

import xlsxwriter
from odoo import _, api, fields, models


class AveaCreditOutstandingWizard(models.TransientModel):
    _name = "avea.credit.outstanding.wizard"
    _description = "Outstanding Customer Credit Wizard"
    _inherit = ["avea.credit.report.mixin"]

    minimum_balance = fields.Monetary(
        string="Minimum Balance",
        currency_field="currency_id",
        default=0.01,
    )
    date = fields.Date(
        string="Date",
        required=True,
        default=fields.Date.context_today,
    )

    def _get_outstanding_data(self):
        self.ensure_one()
        Ledger = self.env["avea.credit.ledger.entry"]
        Partner = self.env["res.partner"]
        as_at_end = self._date_to_datetime_end(self.date)
        today = fields.Date.context_today(self)
        use_stored_balance = self.date >= today

        use_stored_balance = self.date >= today

        if use_stored_balance:
            partners = Partner.search(
                [("avea_credit_balance", ">=", self.minimum_balance)],
                order="avea_credit_balance desc, name",
            )
        else:
            partners = Partner.search([], order="name")

        lines = []
        total_outstanding = 0.0
        for partner in partners:
            if use_stored_balance:
                balance = partner.avea_credit_balance
            else:
                balance = Ledger._get_partner_balance_at(
                    partner, as_at_end, company=self.company_id
                )

            if balance < self.minimum_balance:
                continue

            last_entry = Ledger.search(
                Ledger._credit_report_base_domain(self.company_id)
                + [("partner_id", "=", partner.id)],
                order="transaction_date desc, id desc",
                limit=1,
            )
            lines.append(
                {
                    "partner": partner,
                    "balance": balance,
                    "last_activity_date": last_entry.transaction_date
                    if last_entry
                    else False,
                }
            )
            total_outstanding += balance

        if not use_stored_balance:
            lines.sort(key=lambda line: line["balance"], reverse=True)

        return {
            "date": self.date,
            "minimum_balance": self.minimum_balance,
            "lines": lines,
            "total_outstanding": total_outstanding,
            "company": self.company_id,
            "currency": self.currency_id,
        }

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref(
            "avea_till.action_report_avea_credit_outstanding"
        ).report_action(self)

    def action_export_xlsx(self):
        self.ensure_one()
        data = self._get_outstanding_data()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        worksheet = workbook.add_worksheet("Outstanding Credit")
        header_format = workbook.add_format({"bold": True})
        currency_format = workbook.add_format({"num_format": "#,##0.00"})
        date_format = workbook.add_format({"num_format": "yyyy-mm-dd hh:mm"})

        row = 0
        worksheet.write(row, 0, _("Outstanding Customer Credit"), header_format)
        row += 1
        worksheet.write(row, 0, _("As at"))
        worksheet.write(row, 1, str(data["date"]))
        row += 2

        headers = [_("Customer"), _("Current Balance"), _("Last Activity Date")]
        self._write_xlsx_header(worksheet, headers, header_format)
        row += 1
        for line in data["lines"]:
            worksheet.write(row, 0, line["partner"].display_name)
            self._write_xlsx_amount(worksheet, row, 1, line["balance"], currency_format)
            if line["last_activity_date"]:
                worksheet.write_datetime(
                    row, 2, line["last_activity_date"], date_format
                )
            row += 1
        row += 1
        worksheet.write(row, 0, _("Total Outstanding"), header_format)
        worksheet.write_number(
            row, 1, data["total_outstanding"], currency_format
        )
        workbook.close()
        return self._create_xlsx_download_action(
            "outstanding_customer_credit.xlsx", output.getvalue()
        )

    @api.model
    def action_open_wizard(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Outstanding Customer Credit"),
            "res_model": self._name,
            "view_mode": "form",
            "view_id": self.env.ref(
                "avea_till.view_avea_credit_outstanding_wizard_form"
            ).id,
            "target": "new",
        }
