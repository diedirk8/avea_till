# -*- coding: utf-8 -*-
import base64
import csv
import io
import re

import xlsxwriter
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .supplier_invoice_reader import document_bytes

_HEADER_ALIASES = {
    "product": {"product", "name", "description", "item", "product name"},
    "sku": {
        "sku",
        "barcode",
        "internal reference",
        "default code",
        "product sku",
        "code",
    },
    "supplier_code": {
        "supplier code",
        "supplier sku",
        "vendor code",
        "vendor sku",
        "supplier's code",
    },
    "qty": {"qty", "quantity", "qty ordered", "ordered"},
    "cost": {
        "excl tax cost",
        "ex-tax cost",
        "ex tax cost",
        "excl. tax cost",
        "cost",
        "unit cost",
        "price",
        "excl tax",
        "ex tax",
    },
    "discount": {"discount %", "discount", "disc %", "disc", "discount percent"},
}

_TEMPLATE_HEADERS = (
    "Product",
    "SKU",
    "Supplier Code",
    "Qty",
    "Excl Tax Cost",
    "Discount %",
)


class AveaStockReceiveImport(models.TransientModel):
    _name = "avea.stock.receive.import"
    _description = "Import ordered products into Receive Stock"

    receive_id = fields.Many2one(
        "avea.stock.receive",
        required=True,
        ondelete="cascade",
    )
    spreadsheet = fields.Binary(
        string="Spreadsheet",
        attachment=False,
    )
    spreadsheet_filename = fields.Char(
        string="Filename",
    )

    def action_download_template(self):
        self.ensure_one()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Products")
        notes = workbook.add_worksheet("Notes")
        header_fmt = workbook.add_format(
            {
                "bold": True,
                "bg_color": "#ccfbf1",
                "font_color": "#115e59",
                "border": 1,
            }
        )
        example_fmt = workbook.add_format({"italic": True, "font_color": "#6c757d"})
        money_fmt = workbook.add_format({"num_format": "#,##0.00"})
        for col, header in enumerate(_TEMPLATE_HEADERS):
            sheet.write(0, col, header, header_fmt)
            sheet.set_column(col, col, 22 if col == 0 else 16)
        sheet.write(1, 0, "Royal Canin Mini Adult 2kg", example_fmt)
        sheet.write(1, 1, "RC-MINI-2KG", example_fmt)
        sheet.write(1, 2, "10403310", example_fmt)
        sheet.write(1, 3, 6, example_fmt)
        sheet.write(1, 4, 185.0, money_fmt)
        sheet.write(1, 5, 5, example_fmt)
        sheet.freeze_panes(1, 0)
        notes.write(0, 0, "How to fill this spreadsheet")
        notes.write(
            1,
            0,
            "SKU is your product SKU or barcode. Supplier Code is this supplier's code.",
        )
        notes.write(2, 0, "Costs must be excluding tax.")
        notes.write(
            3,
            0,
            "If a product is not an exact SKU, barcode, or supplier-code match, "
            "Receive Stock suggests any product that is 70% similar or closer. "
            "Confirm it with Add, or press Create to add a new stock item.",
        )
        notes.write(4, 0, "Delete the example row before importing your own lines.")
        notes.set_column(0, 0, 90)
        workbook.close()
        filename = "avea_receive_products.xlsx"
        attachment = self.env["ir.attachment"].create(
            {
                "name": filename,
                "type": "binary",
                "datas": base64.b64encode(output.getvalue()),
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

    def action_import(self):
        self.ensure_one()
        receive = self.receive_id
        if not receive or receive.state != "draft" or receive.show_confirmation:
            raise UserError(_("Import products on a Receive Stock draft."))
        if not self.spreadsheet:
            raise UserError(_("Upload the filled spreadsheet first."))
        raw = document_bytes(self.spreadsheet)
        if not raw:
            raise UserError(_("The uploaded spreadsheet is empty."))
        rows = self._parse_spreadsheet(self.spreadsheet_filename, raw)
        if not rows:
            raise UserError(
                _(
                    "No product rows were found. Use the template headers: "
                    "Product, SKU, Supplier Code, Qty, Excl Tax Cost, Discount %."
                )
            )
        receive._avea_apply_product_rows(rows)
        return receive._avea_receive_action(receive)

    @api.model
    def _parse_spreadsheet(self, filename, raw):
        name = (filename or "").lower()
        if name.endswith(".csv") or name.endswith(".txt"):
            return self._parse_table(_csv_rows(raw))
        if name.endswith(".xls") and not name.endswith(".xlsx"):
            raise UserError(
                _("Save the file as Excel (.xlsx) or CSV, then upload it.")
            )
        return self._parse_table(_xlsx_rows(raw))

    @api.model
    def _parse_table(self, table):
        header_index = None
        columns = {}
        for index, row in enumerate(table):
            mapped = _map_headers(row)
            if mapped:
                header_index = index
                columns = mapped
                break
        if header_index is None:
            return []
        rows = []
        mixin = self.env["avea.stock.mixin"]
        for row in table[header_index + 1 :]:
            parsed = _row_from_cells(row, columns, mixin)
            if parsed:
                rows.append(parsed)
        return rows


def _csv_rows(raw):
    text = raw.decode("utf-8-sig", errors="replace")
    return list(csv.reader(io.StringIO(text)))


def _xlsx_rows(raw):
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


def _normalize_header(value):
    text = str(value or "").strip().lower()
    text = text.replace("%", " %")
    text = re.sub(r"[._/]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" :")


def _map_headers(row):
    columns = {}
    for index, cell in enumerate(row or []):
        header = _normalize_header(cell)
        if not header:
            continue
        for key, aliases in _HEADER_ALIASES.items():
            if header in aliases and key not in columns:
                columns[key] = index
    if "product" in columns or "sku" in columns or "supplier_code" in columns:
        return columns
    return {}


def _cell_text(value):
    if value in (None, False):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _cell_float(value, default=0.0):
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


def _row_from_cells(row, columns, mixin):
    product = _cell_text(_cell_at(row, columns.get("product")))
    sku = _cell_text(_cell_at(row, columns.get("sku")))
    supplier_code = _cell_text(_cell_at(row, columns.get("supplier_code")))
    if not product and not sku and not supplier_code:
        return False
    qty = _cell_float(_cell_at(row, columns.get("qty")), 1.0)
    if not qty:
        return False
    cost = mixin._avea_round_supplier_cost(
        _cell_float(_cell_at(row, columns.get("cost")), 0.0)
    )
    discount = _cell_float(_cell_at(row, columns.get("discount")), 0.0)
    if discount < 0:
        discount = 0.0
    if discount > 100:
        discount = 100.0
    codes = [value for value in (sku, supplier_code) if value]
    return {
        "description": product or sku or supplier_code,
        "codes": codes,
        "sku": sku or False,
        "supplier_code": supplier_code or False,
        "quantity": qty,
        "unit_price": cost,
        "discount": discount,
    }


def _cell_at(row, index):
    if index is None or index >= len(row or []):
        return False
    return row[index]
