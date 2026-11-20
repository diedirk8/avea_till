# -*- coding: utf-8 -*-
from calendar import monthrange

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date, format_datetime

from .data_file import XLSX_MIME, yes_no


def _month_start(day):
    return day.replace(day=1)


def _month_end(day):
    return day.replace(day=monthrange(day.year, day.month)[1])


class AveaDataHub(models.TransientModel):
    _name = "avea.data.hub"
    _description = "Import and export business data"
    _inherit = ["avea.data.file.mixin"]

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    date_from = fields.Date(
        string="From",
        required=True,
        default=lambda self: _month_start(fields.Date.context_today(self)),
    )
    date_to = fields.Date(
        string="To",
        required=True,
        default=lambda self: fields.Date.context_today(self),
    )

    @api.model
    def action_open_data(self):
        record = self.create({"company_id": self.env.company.id})
        view = self.env.ref("avea_till.view_avea_data_hub_form")
        return {
            "type": "ir.actions.act_window",
            "name": _("Data"),
            "res_model": self._name,
            "view_mode": "form",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "res_id": record.id,
            "target": "current",
            "context": {"clear_breadcrumbs": True},
        }

    def _avea_reload(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Data"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "views": [(self.env.ref("avea_till.view_avea_data_hub_form").id, "form")],
            "target": "current",
            "context": {"clear_breadcrumbs": True},
        }

    def action_this_month(self):
        today = fields.Date.context_today(self)
        self.date_from = _month_start(today)
        self.date_to = _month_end(today)
        return self._avea_reload()

    def _company_domain(self, field="company_id"):
        self.ensure_one()
        return ["|", (field, "=", False), (field, "=", self.company_id.id)]

    def _export_bundle(self, data_type):
        self.ensure_one()
        builders = {
            "products": self._export_products,
            "customers": self._export_customers,
            "suppliers": self._export_suppliers,
            "sales": self._export_sales,
            "transactions": self._export_transactions,
        }
        builder = builders.get(data_type)
        if not builder:
            raise UserError(_("Unknown export type."))
        return builder()

    def _download_export(self, data_type):
        headers, rows, slug, sheet = self._export_bundle(data_type)
        content = self._avea_xlsx_workbook(sheet, headers, rows)
        return self._avea_download_bytes(f"avea_{slug}.xlsx", content, XLSX_MIME)

    def action_export_products(self):
        return self._download_export("products")

    def action_export_customers(self):
        return self._download_export("customers")

    def action_export_suppliers(self):
        return self._download_export("suppliers")

    def action_export_sales(self):
        return self._download_export("sales")

    def action_export_transactions(self):
        return self._download_export("transactions")

    def action_import_products(self):
        return self.env["avea.data.import"]._open_wizard("products")

    def action_import_customers(self):
        return self.env["avea.data.import"]._open_wizard("customers")

    def action_import_suppliers(self):
        return self.env["avea.data.import"]._open_wizard("suppliers")

    def action_import_opening_stock(self):
        return self.env["avea.data.import"]._open_wizard("opening_stock")

    def _export_products(self):
        templates = self.env["product.template"].with_context(active_test=False).search(
            self._company_domain() + [("sale_ok", "=", True)],
            order="name, id",
        )
        headers = [
            "SKU",
            "Barcode",
            "Name",
            "Cost EX VAT",
            "Retail INC VAT",
            "Category",
            "Supplier",
            "Supplier code",
            "Sell on POS",
            "Track stock",
            "On hand",
            "Active",
        ]
        rows = []
        for template in templates:
            rows.append(
                [
                    template.default_code or "",
                    template.barcode or "",
                    template.name or "",
                    template.avea_cost_ex_tax or template.standard_price or 0.0,
                    template.list_price or 0.0,
                    template.categ_id.display_name or "",
                    template.avea_supplier_id.display_name or "",
                    template.avea_supplier_code or "",
                    yes_no(template.available_in_pos),
                    yes_no(template.is_storable),
                    template.avea_stock_qty or 0.0,
                    yes_no(template.active),
                ]
            )
        return headers, rows, "products", "Products"

    def _export_partners(self, *, suppliers=False):
        Partner = self.env["res.partner"].with_context(active_test=False)
        domain = self._company_domain()
        if suppliers:
            domain.append(("supplier_rank", ">", 0))
            slug = "suppliers"
            sheet = "Suppliers"
        else:
            domain.append(("customer_rank", ">", 0))
            slug = "customers"
            sheet = "Customers"
        partners = Partner.search(domain, order="name, id")
        headers = ["Name", "Email", "Phone", "Mobile", "VAT", "Street", "City", "ZIP", "Active"]
        rows = [
            [
                partner.name or "",
                partner.email or "",
                partner.phone or "",
                partner.mobile or "",
                partner.vat or "",
                partner.street or "",
                partner.city or "",
                partner.zip or "",
                yes_no(partner.active),
            ]
            for partner in partners
        ]
        return headers, rows, slug, sheet

    def _export_customers(self):
        return self._export_partners(suppliers=False)

    def _export_suppliers(self):
        return self._export_partners(suppliers=True)

    def _export_sales(self):
        self._check_dates()
        start, end = self._avea_day_bounds(self.date_from, self.date_to)
        states = self.env["pos.session"]._avea_paid_order_states()
        orders = self.env["pos.order"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("state", "in", states),
                ("date_order", ">=", start),
                ("date_order", "<", end),
            ],
            order="date_order, id",
        )
        headers = [
            "Date",
            "Order",
            "Customer",
            "Amount",
            "Payments",
            "Cashier",
            "Session",
        ]
        rows = []
        for order in orders:
            payments = ", ".join(
                f"{pay.payment_method_id.display_name} {order.currency_id.round(pay.amount)}"
                for pay in order.payment_ids
            )
            rows.append(
                [
                    format_datetime(self.env, order.date_order, dt_format="short"),
                    order.pos_reference or order.name or "",
                    order.partner_id.display_name or "",
                    order.amount_total or 0.0,
                    payments,
                    order.user_id.display_name or "",
                    order.session_id.display_name or "",
                ]
            )
        slug = f"sales_{self.date_from}_{self.date_to}"
        return headers, rows, slug, "Sales"

    def _export_transactions(self):
        self._check_dates()
        transactions = self.env["avea.business.transaction"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("transaction_date", ">=", self.date_from),
                ("transaction_date", "<=", self.date_to),
            ],
            order="transaction_datetime desc, id desc",
        )
        type_labels = dict(
            self.env["avea.business.transaction"]._fields["transaction_type"].selection
        )
        headers = ["Date", "Type", "Reference", "Amount", "User"]
        rows = [
            [
                format_datetime(self.env, txn.transaction_datetime, dt_format="short")
                if txn.transaction_datetime
                else format_date(self.env, txn.transaction_date),
                type_labels.get(txn.transaction_type, txn.transaction_type or ""),
                txn.reference or "",
                txn.amount or 0.0,
                txn.user_id.display_name or "",
            ]
            for txn in transactions
        ]
        slug = f"transactions_{self.date_from}_{self.date_to}"
        return headers, rows, slug, "Transactions"

    def _check_dates(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("The from date must be on or before the to date."))
