# -*- coding: utf-8 -*-
import json

from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError

from .data_file import cell_bool, cell_float, cell_text, parse_named_rows

PRODUCT_ALIASES = {
    "sku": {"sku", "internal reference", "default code", "product sku", "code"},
    "barcode": {"barcode", "ean", "ean13"},
    "name": {"name", "product", "product name", "description", "item"},
    "cost_ex_vat": {
        "cost ex vat",
        "cost ex tax",
        "cost",
        "unit cost",
        "standard price",
        "cost_ex_vat",
    },
    "retail_inc_vat": {
        "retail inc vat",
        "retail",
        "list price",
        "price",
        "selling price",
        "retail_inc_vat",
    },
    "category": {"category", "product category"},
    "supplier_name": {"supplier", "supplier name", "vendor"},
    "supplier_code": {"supplier code", "vendor code", "supplier sku"},
    "sell_on_pos": {"sell on pos", "available in pos", "pos"},
    "track_stock": {"track stock", "is storable", "storable"},
    "active": {"active"},
}

CUSTOMER_ALIASES = {
    "name": {"name", "customer", "customer name", "supplier", "supplier name"},
    "email": {"email", "e-mail"},
    "phone": {"phone", "telephone"},
    "mobile": {"mobile", "cell", "cellphone"},
    "vat": {"vat", "vat number", "tax id"},
    "street": {"street", "address"},
    "city": {"city"},
    "zip": {"zip", "postal code", "postcode"},
    "active": {"active"},
}

OPENING_ALIASES = {
    "sku": {"sku", "internal reference", "default code", "code"},
    "barcode": {"barcode", "ean"},
    "qty": {"qty", "quantity", "on hand", "counted", "opening stock", "stock"},
}

TEMPLATES = {
    "products": {
        "sheet": "Products",
        "headers": (
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
        ),
        "example": (
            "RC-MINI-2KG",
            "6001234567890",
            "Royal Canin Mini Adult 2kg",
            185.0,
            269.0,
            "Dog Food",
            "Royal Canin",
            "10403310",
            "yes",
            "yes",
        ),
        "notes": (
            "SKU is the match key for updates. Barcode is used if SKU is blank.",
            "Cost is excluding tax. Retail is including tax.",
            "Sell on POS and Track stock accept yes/no.",
            "Delete the example row before importing your own lines.",
        ),
        "filename": "avea_products_template.xlsx",
    },
    "customers": {
        "sheet": "Customers",
        "headers": ("Name", "Email", "Phone", "Mobile", "VAT", "Street", "City", "ZIP"),
        "example": (
            "Jane Owner",
            "jane@example.com",
            "011 555 0100",
            "082 555 0100",
            "",
            "12 Main Road",
            "Johannesburg",
            "2000",
        ),
        "notes": (
            "Email is the match key when present. Phone is used if email is blank.",
            "Name is required when creating a new customer.",
            "Delete the example row before importing your own lines.",
        ),
        "filename": "avea_customers_template.xlsx",
    },
    "suppliers": {
        "sheet": "Suppliers",
        "headers": ("Name", "Email", "Phone", "VAT", "Street", "City", "ZIP"),
        "example": (
            "Acme Wholesale",
            "orders@acme.example",
            "011 555 0200",
            "4123456789",
            "8 Industrial Park",
            "Johannesburg",
            "2094",
        ),
        "notes": (
            "Email is the match key when present. Name is used if email is blank.",
            "Delete the example row before importing your own lines.",
        ),
        "filename": "avea_suppliers_template.xlsx",
    },
    "opening_stock": {
        "sheet": "Opening stock",
        "headers": ("SKU", "Barcode", "Qty"),
        "example": ("RC-MINI-2KG", "6001234567890", 12),
        "notes": (
            "SKU or barcode must already exist. Import products first if needed.",
            "This creates a Stock Take in review. Check it, then apply.",
            "Delete the example row before importing your own lines.",
        ),
        "filename": "avea_opening_stock_template.xlsx",
    },
}


class AveaDataImport(models.TransientModel):
    _name = "avea.data.import"
    _description = "Import Avea spreadsheet"
    _inherit = ["avea.data.file.mixin"]

    data_type = fields.Selection(
        [
            ("products", "Products"),
            ("customers", "Customers"),
            ("suppliers", "Suppliers"),
            ("opening_stock", "Opening stock"),
        ],
        required=True,
    )
    spreadsheet = fields.Binary(string="Spreadsheet", attachment=False)
    spreadsheet_filename = fields.Char(string="Filename")
    state = fields.Selection(
        [("upload", "Upload"), ("preview", "Preview")],
        default="upload",
        required=True,
    )
    line_ids = fields.One2many("avea.data.import.line", "import_id", string="Rows")
    create_count = fields.Integer(compute="_compute_counts")
    update_count = fields.Integer(compute="_compute_counts")
    error_count = fields.Integer(compute="_compute_counts")
    type_label = fields.Char(compute="_compute_type_label")

    @api.depends("data_type")
    def _compute_type_label(self):
        labels = dict(self._fields["data_type"].selection)
        for wizard in self:
            wizard.type_label = labels.get(wizard.data_type) or ""

    @api.depends("line_ids.action")
    def _compute_counts(self):
        for wizard in self:
            wizard.create_count = len(wizard.line_ids.filtered(lambda line: line.action == "create"))
            wizard.update_count = len(wizard.line_ids.filtered(lambda line: line.action == "update"))
            wizard.error_count = len(wizard.line_ids.filtered(lambda line: line.action == "error"))

    @api.model
    def _open_wizard(self, data_type):
        wizard = self.create({"data_type": data_type})
        view = self.env.ref("avea_till.view_avea_data_import_form")
        return {
            "type": "ir.actions.act_window",
            "name": _("Import %s", wizard.type_label),
            "res_model": self._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "current",
            "context": {"clear_breadcrumbs": True},
        }

    def action_back_to_data(self):
        return self.env["avea.data.hub"].action_open_data()

    def action_download_template(self):
        self.ensure_one()
        spec = TEMPLATES[self.data_type]
        content = self._avea_xlsx_workbook(
            spec["sheet"],
            spec["headers"],
            [],
            notes=spec["notes"],
            example=spec["example"],
        )
        return self._avea_download_bytes(spec["filename"], content, (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ))

    def action_preview(self):
        self.ensure_one()
        if not self.spreadsheet:
            raise UserError(_("Upload the filled spreadsheet first."))
        raw = self._avea_spreadsheet_bytes(self.spreadsheet_filename, self.spreadsheet)
        lines = self._preview_rows(raw)
        if not lines:
            raise UserError(_("No data rows were found. Use the template headers."))
        self.line_ids.unlink()
        self.write(
            {
                "state": "preview",
                "line_ids": [Command.create(vals) for vals in lines],
            }
        )
        return self._reopen()

    def _reopen(self):
        self.ensure_one()
        view = self.env.ref("avea_till.view_avea_data_import_form")
        return {
            "type": "ir.actions.act_window",
            "name": _("Import %s", self.type_label),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "current",
            "context": {"clear_breadcrumbs": True},
        }

    def _preview_rows(self, raw):
        if self.data_type == "products":
            return self._preview_products(raw)
        if self.data_type in ("customers", "suppliers"):
            return self._preview_partners(raw)
        return self._preview_opening_stock(raw)

    def _preview_products(self, raw):
        parsed = parse_named_rows(
            self.spreadsheet_filename,
            raw,
            PRODUCT_ALIASES,
            ("sku", "barcode", "name"),
        )
        seen = set()
        lines = []
        for index, values in enumerate(parsed, start=2):
            sku = cell_text(values.get("sku"))
            barcode = cell_text(values.get("barcode"))
            name = cell_text(values.get("name"))
            key = (sku or barcode).lower()
            if key and key in seen:
                lines.append(self._line_vals(index, "error", name or sku or barcode, sku or barcode, _("Duplicate SKU or barcode in this file.")))
                continue
            if key:
                seen.add(key)
            payload = {
                "sku": sku,
                "barcode": barcode,
                "name": name,
            }
            if "cost_ex_vat" in values:
                payload["cost_ex_vat"] = cell_float(values.get("cost_ex_vat"))
            if "retail_inc_vat" in values:
                payload["retail_inc_vat"] = cell_float(values.get("retail_inc_vat"))
            if "category" in values:
                payload["category"] = cell_text(values.get("category"))
            if "supplier_name" in values:
                payload["supplier_name"] = cell_text(values.get("supplier_name"))
            if "supplier_code" in values:
                payload["supplier_code"] = cell_text(values.get("supplier_code"))
            if "sell_on_pos" in values:
                payload["sell_on_pos"] = cell_bool(values.get("sell_on_pos"), True)
            if "track_stock" in values:
                payload["track_stock"] = cell_bool(values.get("track_stock"), True)
            if "active" in values:
                payload["active"] = cell_bool(values.get("active"), True)
            product = self._find_product(sku, barcode)
            if product:
                lines.append(
                    self._line_vals(
                        index,
                        "update",
                        product.display_name,
                        sku or barcode or product.default_code,
                        _("Update existing product."),
                        payload,
                    )
                )
                continue
            if not name:
                lines.append(
                    self._line_vals(index, "error", sku or barcode, sku or barcode, _("Name is required to create a product."))
                )
                continue
            if not sku and not barcode:
                lines.append(
                    self._line_vals(index, "error", name, "", _("SKU or barcode is required."))
                )
                continue
            lines.append(
                self._line_vals(index, "create", name, sku or barcode, _("Create new product."), payload)
            )
        return lines

    def _preview_partners(self, raw):
        parsed = parse_named_rows(
            self.spreadsheet_filename,
            raw,
            CUSTOMER_ALIASES,
            ("name", "email", "phone"),
        )
        suppliers = self.data_type == "suppliers"
        seen = set()
        lines = []
        for index, values in enumerate(parsed, start=2):
            payload = {
                "name": cell_text(values.get("name")),
                "email": cell_text(values.get("email")),
                "phone": cell_text(values.get("phone")),
                "vat": cell_text(values.get("vat")),
                "street": cell_text(values.get("street")),
                "city": cell_text(values.get("city")),
                "zip": cell_text(values.get("zip")),
            }
            if "mobile" in values:
                payload["mobile"] = cell_text(values.get("mobile"))
            if "active" in values:
                payload["active"] = cell_bool(values.get("active"), True)
            key = (payload["email"] or payload["phone"] or payload["name"]).lower()
            if key and key in seen:
                lines.append(
                    self._line_vals(index, "error", payload["name"] or key, key, _("Duplicate row in this file."))
                )
                continue
            if key:
                seen.add(key)
            partner = self._find_partner(payload, suppliers=suppliers)
            if partner:
                lines.append(
                    self._line_vals(
                        index,
                        "update",
                        partner.display_name,
                        payload["email"] or payload["phone"] or partner.display_name,
                        _("Update existing record."),
                        payload,
                    )
                )
                continue
            if not payload["name"]:
                lines.append(
                    self._line_vals(index, "error", payload["email"] or payload["phone"], payload["email"], _("Name is required to create a record."))
                )
                continue
            lines.append(
                self._line_vals(
                    index,
                    "create",
                    payload["name"],
                    payload["email"] or payload["phone"] or payload["name"],
                    _("Create new record."),
                    payload,
                )
            )
        return lines

    def _preview_opening_stock(self, raw):
        parsed = parse_named_rows(
            self.spreadsheet_filename,
            raw,
            OPENING_ALIASES,
            ("sku", "barcode"),
        )
        seen = set()
        lines = []
        for index, values in enumerate(parsed, start=2):
            sku = cell_text(values.get("sku"))
            barcode = cell_text(values.get("barcode"))
            qty = cell_float(values.get("qty"))
            key = (sku or barcode).lower()
            if key and key in seen:
                lines.append(self._line_vals(index, "error", sku or barcode, key, _("Duplicate SKU or barcode in this file.")))
                continue
            if key:
                seen.add(key)
            if qty is None:
                lines.append(self._line_vals(index, "error", sku or barcode, sku or barcode, _("Quantity is required.")))
                continue
            if qty < 0:
                lines.append(self._line_vals(index, "error", sku or barcode, sku or barcode, _("Quantity cannot be negative.")))
                continue
            product = self._find_variant(sku, barcode)
            if not product:
                lines.append(
                    self._line_vals(index, "error", sku or barcode, sku or barcode, _("Product not found. Import products first."))
                )
                continue
            if not product.is_storable:
                lines.append(
                    self._line_vals(index, "error", product.display_name, sku or barcode, _("This product does not track stock."))
                )
                continue
            payload = {"product_id": product.id, "qty": qty}
            lines.append(
                self._line_vals(
                    index,
                    "update",
                    product.display_name,
                    sku or barcode or product.default_code,
                    _("Set opening quantity to %(qty)s.", qty=qty),
                    payload,
                )
            )
        return lines

    def _line_vals(self, row_number, action, name, key, message, payload=None):
        return {
            "row_number": row_number,
            "action": action,
            "name": name or "",
            "key": key or "",
            "message": message,
            "payload": json.dumps(payload or {}),
        }

    def _company_domain(self):
        company = self.env.company
        return ["|", ("company_id", "=", False), ("company_id", "=", company.id)]

    def _find_product(self, sku, barcode):
        Product = self.env["product.template"].with_context(active_test=False)
        domain = self._company_domain()
        if sku:
            match = Product.search(domain + [("default_code", "=ilike", sku)], limit=1)
            if match:
                return match
        if barcode:
            return Product.search(domain + [("barcode", "=", barcode)], limit=1)
        return Product.browse()

    def _find_variant(self, sku, barcode):
        template = self._find_product(sku, barcode)
        return template.product_variant_id if template else self.env["product.product"]

    def _find_partner(self, payload, suppliers=False):
        Partner = self.env["res.partner"].with_context(active_test=False)
        domain = self._company_domain()
        domain.append(("supplier_rank", ">", 0) if suppliers else ("customer_rank", ">", 0))
        if payload.get("email"):
            match = Partner.search(domain + [("email", "=ilike", payload["email"])], limit=1)
            if match:
                return match
        if payload.get("phone"):
            match = Partner.search(domain + [("phone", "=", payload["phone"])], limit=1)
            if match:
                return match
        if suppliers and payload.get("name"):
            return Partner.search(domain + [("name", "=ilike", payload["name"])], limit=1)
        return Partner.browse()

    def action_apply(self):
        self.ensure_one()
        if self.state != "preview":
            raise UserError(_("Preview the spreadsheet before applying it."))
        ready = self.line_ids.filtered(lambda line: line.action in ("create", "update"))
        if not ready:
            raise UserError(_("Nothing to import. Fix the errors and preview again."))
        if self.data_type == "products":
            created, updated = self._apply_products(ready)
            message = _("Created %(created)s products, updated %(updated)s.", created=created, updated=updated)
            return self._notify_done(message)
        if self.data_type in ("customers", "suppliers"):
            created, updated = self._apply_partners(ready)
            label = _("suppliers") if self.data_type == "suppliers" else _("customers")
            message = _("Created %(created)s %(label)s, updated %(updated)s.", created=created, updated=updated, label=label)
            return self._notify_done(message)
        return self._apply_opening_stock(ready)

    def _notify_done(self, message):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Import complete"),
                "message": message,
                "type": "success",
                "sticky": False,
                "next": self.env["avea.data.hub"].action_open_data(),
            },
        }

    def _apply_products(self, lines):
        created = updated = 0
        mixin = self.env["avea.stock.mixin"]
        Product = self.env["product.template"].with_context(avea_stock_workspace=True)
        for line in lines:
            values = json.loads(line.payload or "{}")
            vals = self._product_vals(values, mixin)
            product = self._find_product(values.get("sku"), values.get("barcode"))
            if product:
                product.with_context(avea_stock_workspace=True).write(vals)
                updated += 1
            else:
                Product.create(vals)
                created += 1
        return created, updated

    def _product_vals(self, values, mixin):
        vals = {
            "sale_ok": True,
            "purchase_ok": True,
            "type": "consu",
        }
        if values.get("name"):
            vals["name"] = values["name"]
        if values.get("sku"):
            vals["default_code"] = values["sku"]
        if values.get("barcode"):
            vals["barcode"] = values["barcode"]
        if values.get("cost_ex_vat") is not None:
            cost = mixin._avea_round_supplier_cost(values["cost_ex_vat"])
            vals["avea_cost_ex_tax"] = cost
            vals["standard_price"] = mixin._avea_round_product_cost(cost)
        if values.get("retail_inc_vat") is not None:
            vals["list_price"] = mixin._avea_round_product_cost(values["retail_inc_vat"])
        if "sell_on_pos" in values:
            vals["available_in_pos"] = bool(values["sell_on_pos"])
        if "track_stock" in values:
            vals["is_storable"] = bool(values["track_stock"])
        if "active" in values:
            vals["active"] = bool(values["active"])
        if values.get("category"):
            vals["categ_id"] = self._category(values["category"]).id
        if values.get("supplier_name"):
            vals["avea_supplier_id"] = self._supplier(values["supplier_name"]).id
        if values.get("supplier_code"):
            vals["avea_supplier_code"] = values["supplier_code"]
        sale_tax = self.env.company.account_sale_tax_id
        if sale_tax and "name" in vals:
            vals.setdefault("taxes_id", [Command.set(sale_tax.ids)])
        return vals

    def _category(self, name):
        Category = self.env["product.category"]
        category = Category.search([("name", "=ilike", name)], limit=1)
        if category:
            return category
        return Category.create({"name": name})

    def _supplier(self, name):
        Partner = self.env["res.partner"]
        domain = self._company_domain() + [("supplier_rank", ">", 0), ("name", "=ilike", name)]
        partner = Partner.search(domain, limit=1)
        if partner:
            return partner
        return Partner.create(
            {
                "name": name,
                "supplier_rank": 1,
                "company_id": self.env.company.id,
                "is_company": True,
            }
        )

    def _apply_partners(self, lines):
        created = updated = 0
        suppliers = self.data_type == "suppliers"
        Partner = self.env["res.partner"]
        for line in lines:
            values = json.loads(line.payload or "{}")
            vals = {
                key: values[key]
                for key in ("name", "email", "phone", "vat", "street", "city", "zip")
                if values.get(key) not in (None, "")
            }
            if "mobile" in values and "mobile" in Partner._fields and values.get("mobile") not in (None, ""):
                vals["mobile"] = values["mobile"]
            if "active" in values:
                vals["active"] = bool(values["active"])
            if suppliers:
                vals["supplier_rank"] = 1
            else:
                vals["customer_rank"] = 1
            partner = self._find_partner(values, suppliers=suppliers)
            if partner:
                partner.write(vals)
                updated += 1
            else:
                vals.setdefault("company_id", self.env.company.id)
                Partner.create(vals)
                created += 1
        return created, updated

    def _apply_opening_stock(self, lines):
        Take = self.env["avea.stock.take"]
        location = Take._avea_default_stock_location(self.env.company)
        qty_by_product = {}
        for line in lines:
            values = json.loads(line.payload or "{}")
            product_id = values.get("product_id")
            if not product_id:
                continue
            qty_by_product[product_id] = values.get("qty") or 0.0
        if not qty_by_product:
            raise UserError(_("No matching products to count."))
        take = Take.create(
            {
                "name": _("Opening stock %s", fields.Date.context_today(self)),
                "scope_mode": "partial",
                "counting_mode": "review",
                "company_id": self.env.company.id,
                "location_id": location.id,
                "manual_product_ids": [Command.set(list(qty_by_product))],
            }
        )
        take._avea_populate_lines()
        for line in take.line_ids:
            line._avea_set_counted_qty(qty_by_product.get(line.product_id.id, 0.0))
        take.state = "review"
        return take._avea_open_client_action()


class AveaDataImportLine(models.TransientModel):
    _name = "avea.data.import.line"
    _description = "Import preview row"
    _order = "row_number, id"

    import_id = fields.Many2one("avea.data.import", required=True, ondelete="cascade")
    row_number = fields.Integer(string="Row")
    action = fields.Selection(
        [
            ("create", "Create"),
            ("update", "Update"),
            ("error", "Error"),
        ],
        required=True,
    )
    name = fields.Char(string="Record")
    key = fields.Char(string="Match")
    message = fields.Char(string="Result")
    payload = fields.Text()
