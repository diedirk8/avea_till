# -*- coding: utf-8 -*-
import base64
import csv
import io
import re
from datetime import timedelta

import xlsxwriter
from odoo import _, fields, models
from odoo.exceptions import UserError

from ..stock.supplier_invoice_reader import document_bytes

XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def cell_text(value):
    if value in (None, False):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def cell_float(value, default=None):
    if value in (None, False, ""):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace(",", "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def cell_bool(value, default=True):
    if value in (None, False, ""):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "y", "yes", "true", "t"}:
        return True
    if text in {"0", "n", "no", "false", "f"}:
        return False
    return default


def normalize_header(value):
    text = str(value or "").strip().lower()
    text = text.replace("%", " %")
    text = re.sub(r"[._/]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" :")


def map_headers(row, aliases):
    columns = {}
    for index, cell in enumerate(row or []):
        header = normalize_header(cell)
        if not header:
            continue
        for key, names in aliases.items():
            if header in names and key not in columns:
                columns[key] = index
    return columns


def cell_at(row, index):
    if index is None or index >= len(row or []):
        return False
    return row[index]


def csv_rows(raw):
    text = raw.decode("utf-8-sig", errors="replace")
    return list(csv.reader(io.StringIO(text)))


def xlsx_rows(raw):
    try:
        from openpyxl import load_workbook
    except ImportError as error:
        raise UserError(
            _("Excel import needs openpyxl on this server. Save the file as CSV instead.")
        ) from error
    workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        sheet = workbook.active
        return [list(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def parse_table(filename, raw):
    name = (filename or "").lower()
    if name.endswith(".csv") or name.endswith(".txt"):
        return csv_rows(raw)
    if name.endswith(".xls") and not name.endswith(".xlsx"):
        raise UserError(_("Save the file as Excel (.xlsx) or CSV, then upload it."))
    return xlsx_rows(raw)


def parse_named_rows(filename, raw, aliases, required_any):
    table = parse_table(filename, raw)
    header_index = None
    columns = {}
    for index, row in enumerate(table):
        mapped = map_headers(row, aliases)
        if any(key in mapped for key in required_any):
            header_index = index
            columns = mapped
            break
    if header_index is None:
        return []
    rows = []
    for row in table[header_index + 1 :]:
        values = {
            key: cell_at(row, columns[key])
            for key in columns
        }
        if not any(cell_text(values.get(key)) for key in required_any):
            continue
        rows.append(values)
    return rows


def yes_no(value):
    return "yes" if value else "no"


class AveaDataFileMixin(models.AbstractModel):
    _name = "avea.data.file.mixin"
    _description = "Avea spreadsheet download helpers"

    def _avea_download_bytes(self, filename, content, mimetype):
        self.ensure_one()
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

    def _avea_xlsx_workbook(self, sheet_name, headers, rows, notes=None, example=None):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet(sheet_name[:31] or "Data")
        header_fmt = workbook.add_format(
            {
                "bold": True,
                "bg_color": "#ccfbf1",
                "font_color": "#115e59",
                "border": 1,
            }
        )
        example_fmt = workbook.add_format({"italic": True, "font_color": "#6c757d"})
        for col, header in enumerate(headers):
            sheet.write(0, col, header, header_fmt)
            sheet.set_column(col, col, 22 if col == 0 else 16)
        start = 1
        if example:
            for col, value in enumerate(example):
                sheet.write(1, col, value, example_fmt)
            start = 2
        for row_index, row in enumerate(rows, start=start):
            for col, value in enumerate(row):
                if value in (None, False):
                    continue
                sheet.write(row_index, col, value)
        sheet.freeze_panes(1, 0)
        if notes:
            note_sheet = workbook.add_worksheet("Notes")
            note_sheet.write(0, 0, "How to fill this spreadsheet")
            for index, line in enumerate(notes, start=1):
                note_sheet.write(index, 0, line)
            note_sheet.set_column(0, 0, 90)
        workbook.close()
        return output.getvalue()

    def _avea_csv_bytes(self, headers, rows):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(["" if value in (None, False) else value for value in row])
        return output.getvalue().encode("utf-8-sig")

    def _avea_day_bounds(self, date_from, date_to):
        start = fields.Datetime.to_datetime(date_from) if date_from else False
        if date_to:
            end = fields.Datetime.to_datetime(date_to) + timedelta(days=1)
        else:
            end = False
        return start, end

    def _avea_spreadsheet_bytes(self, filename, binary):
        raw = document_bytes(binary)
        if not raw:
            raise UserError(_("The uploaded spreadsheet is empty."))
        return raw
