# -*- coding: utf-8 -*-
import base64
import csv
import io

import xlsxwriter
from odoo import _, models


class AveaAccountingReportExportMixin(models.AbstractModel):
    _name = "avea.accounting.report.export.mixin"
    _description = "Export helpers for Avea accounting reports"

    def _accounting_build_export_table(self):
        """Return title, filename_slug, period_label, summaries, headers, rows.

        summaries: list of (label, formatted_amount_or_text)
        rows: list of dicts with keys row_type (header|line|total), cells (list)
        """
        raise NotImplementedError

    def _accounting_export_pdf_xmlid(self):
        raise NotImplementedError

    def _accounting_format_amount(self, amount):
        currency = getattr(self, "currency_id", None) or self.env.company.currency_id
        if amount in (None, False):
            return ""
        return currency.format(amount)

    def _create_download_action(self, filename, content, mimetype):
        attachment = self.env["ir.attachment"].create(
            {
                "name": filename,
                "type": "binary",
                "datas": base64.b64encode(content),
                "mimetype": mimetype,
                "res_model": self._name,
                "res_id": self.id,
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def _accounting_export_bundle(self):
        self.ensure_one()
        return self._accounting_build_export_table()

    def action_export_csv(self):
        self.ensure_one()
        title, slug, period_label, summaries, headers, rows = self._accounting_export_bundle()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([title])
        if period_label:
            writer.writerow([period_label])
        for label, value in summaries:
            writer.writerow([label, value])
        writer.writerow([])
        writer.writerow(headers)
        money_headers = {_('Amount'), _('Debit'), _('Credit')}
        for row in rows:
            line = []
            for index, value in enumerate(row["cells"]):
                header = headers[index] if index < len(headers) else ""
                if isinstance(value, (int, float)) and header in money_headers:
                    line.append(self._accounting_format_amount(value))
                else:
                    line.append(value)
            writer.writerow(line)
        filename = f"{slug}.csv"
        content = output.getvalue().encode("utf-8-sig")
        return self._create_download_action(filename, content, "text/csv;charset=utf-8")

    def action_export_xlsx(self):
        self.ensure_one()
        title, slug, period_label, summaries, headers, rows = self._accounting_export_bundle()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet(title[:31] or "Report")
        title_fmt = workbook.add_format({"bold": True, "font_size": 14})
        meta_fmt = workbook.add_format({"italic": True, "font_color": "#6c757d"})
        header_fmt = workbook.add_format(
            {"bold": True, "bg_color": "#ccfbf1", "font_color": "#115e59", "border": 1}
        )
        col_header_fmt = workbook.add_format(
            {"bold": True, "bg_color": "#f3f4f6", "border": 1}
        )
        total_fmt = workbook.add_format(
            {"bold": True, "bg_color": "#f8f9fa", "top": 2, "top_color": "#0f766e"}
        )
        money_fmt = workbook.add_format({"num_format": "#,##0.00", "align": "right"})
        total_money_fmt = workbook.add_format(
            {
                "bold": True,
                "num_format": "#,##0.00",
                "align": "right",
                "bg_color": "#f8f9fa",
                "top": 2,
                "top_color": "#0f766e",
            }
        )
        line_fmt = workbook.add_format({"bg_color": "#ffffff"})
        line_money_fmt = workbook.add_format(
            {"num_format": "#,##0.00", "align": "right", "bg_color": "#ffffff"}
        )
        alt_line_fmt = workbook.add_format({"bg_color": "#f9fafb"})
        alt_line_money_fmt = workbook.add_format(
            {"num_format": "#,##0.00", "align": "right", "bg_color": "#f9fafb"}
        )

        row_idx = 0
        sheet.write(row_idx, 0, title, title_fmt)
        row_idx += 1
        if period_label:
            sheet.write(row_idx, 0, period_label, meta_fmt)
            row_idx += 1
        for label, value in summaries:
            sheet.write(row_idx, 0, label, workbook.add_format({"bold": True}))
            sheet.write(row_idx, 1, value)
            row_idx += 1
        row_idx += 1
        for col, header in enumerate(headers):
            sheet.write(row_idx, col, header, col_header_fmt)
        row_idx += 1

        amount_cols = set()
        for index, header in enumerate(headers):
            if header in (_("Amount"), _("Debit"), _("Credit")):
                amount_cols.add(index)

        line_index = 0
        for row in rows:
            row_type = row["row_type"]
            cells = row["cells"]
            if row_type == "header":
                for col, value in enumerate(cells):
                    fmt = header_fmt if col == 1 or (col == 0 and not cells[1]) else header_fmt
                    sheet.write(row_idx, col, value or "", fmt)
            elif row_type == "total":
                for col, value in enumerate(cells):
                    if col in amount_cols and isinstance(value, (int, float)):
                        sheet.write_number(row_idx, col, value, total_money_fmt)
                    else:
                        sheet.write(row_idx, col, value or "", total_fmt)
            else:
                stripe = line_index % 2 == 1
                line_index += 1
                for col, value in enumerate(cells):
                    if col in amount_cols and isinstance(value, (int, float)):
                        sheet.write_number(
                            row_idx,
                            col,
                            value,
                            alt_line_money_fmt if stripe else line_money_fmt,
                        )
                    else:
                        sheet.write(
                            row_idx,
                            col,
                            value or "",
                            alt_line_fmt if stripe else line_fmt,
                        )
            row_idx += 1

        sheet.set_column(0, 0, 14)
        sheet.set_column(1, 1, 36)
        if len(headers) > 2:
            sheet.set_column(2, len(headers) - 1, 16)
        workbook.close()
        filename = f"{slug}.xlsx"
        return self._create_download_action(
            filename,
            output.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def action_export_pdf(self):
        self.ensure_one()
        return self.env.ref(self._accounting_export_pdf_xmlid()).report_action(self)

    def _accounting_pdf_payload(self):
        self.ensure_one()
        title, _slug, period_label, summaries, headers, rows = self._accounting_export_bundle()
        currency = getattr(self, "currency_id", None) or self.env.company.currency_id
        pdf_rows = []
        money_headers = {_('Amount'), _('Debit'), _('Credit')}
        for row in rows:
            cells = []
            for index, value in enumerate(row["cells"]):
                header = headers[index] if index < len(headers) else ""
                if isinstance(value, (int, float)) and header in money_headers:
                    cells.append(currency.format(value))
                else:
                    cells.append(value or "")
            pdf_rows.append({"row_type": row["row_type"], "cells": cells})
        return {
            "title": title,
            "period_label": period_label,
            "summaries": summaries,
            "headers": headers,
            "rows": pdf_rows,
            "company": self.env.company,
        }
