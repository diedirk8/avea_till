# -*- coding: utf-8 -*-
import re

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .supplier_invoice_reader import AveaSupplierInvoiceReader, document_bytes

_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "per",
    "each",
    "pack",
    "item",
}


class AveaStockReceiveUnmatched(models.Model):
    _name = "avea.stock.receive.unmatched"
    _description = "Receive Stock invoice line that was not matched"
    _order = "id"

    receive_id = fields.Many2one(
        "avea.stock.receive",
        required=True,
        ondelete="cascade",
    )
    description = fields.Char(string="On the invoice", required=True)
    quantity = fields.Float(string="Quantity", digits="Product Unit", default=1.0)
    price_unit = fields.Float(string="EX-Tax cost", digits="Avea Supplier Cost")
    supplier_code = fields.Char(string="Supplier code")
    product_id = fields.Many2one(
        "product.product",
        string="Closest product",
        domain="[('is_storable', '=', True), ('purchase_ok', '=', True)]",
    )

    def action_add_to_receive(self):
        for line in self:
            line._add_to_receive()
        return True

    def _add_to_receive(self):
        self.ensure_one()
        if not self.product_id:
            raise UserError(_("Choose the product that matches “%s”.", self.description))
        self.receive_id._avea_remember_supplier_code(self.product_id, self.supplier_code)
        self.env["avea.stock.receive.line"].create(
            {
                "receive_id": self.receive_id.id,
                "product_id": self.product_id.id,
                "quantity": self.quantity or 1.0,
                "price_unit": self.price_unit or 0.0,
            }
        )
        self.unlink()


class AveaStockReceiveInvoiceImport(models.Model):
    _inherit = "avea.stock.receive"

    invoice_read_summary = fields.Text(
        string="Invoice reading",
        copy=False,
    )
    unmatched_line_ids = fields.One2many(
        "avea.stock.receive.unmatched",
        "receive_id",
        string="Not found on the invoice",
        copy=False,
    )

    def action_read_supplier_invoice(self):
        """Fill this receive from the uploaded invoice. Does not receive stock."""
        self.ensure_one()
        if self.line_ids:
            raise UserError(
                _(
                    "Clear the product lines first, then read the invoice again. "
                    "Reading replaces the lines it fills in."
                )
            )
        self._avea_apply_invoice_reading(self._avea_parsed_invoice())
        return True

    def _avea_parsed_invoice(self):
        self.ensure_one()
        if not self.invoice_document:
            raise UserError(_("Upload the invoice first."))
        raw = document_bytes(self.invoice_document)
        if not raw:
            raise UserError(_("The uploaded invoice is empty."))
        try:
            parsed = AveaSupplierInvoiceReader.read_document(
                self.invoice_document_filename,
                raw,
            )
        except ValueError as error:
            raise UserError(str(error)) from error
        if not parsed["lines"]:
            raise UserError(
                _(
                    "No product lines could be read from this invoice. "
                    "A clearer photo or the supplier's digital PDF usually works. "
                    "You can still enter the lines yourself."
                )
            )
        return parsed

    @api.onchange("invoice_document", "invoice_document_filename")
    def _onchange_invoice_document(self):
        """Read the file as soon as it is chosen. The button remains for a second read."""
        if not self.invoice_document or self.line_ids or self.unmatched_line_ids:
            return
        try:
            parsed = self._avea_parsed_invoice()
        except UserError as error:
            return {"warning": {"title": _("Invoice"), "message": str(error)}}
        for field_name, value in self._avea_invoice_values(parsed).items():
            self[field_name] = value

    def action_add_matched_invoice_lines(self):
        self.ensure_one()
        chosen = self.unmatched_line_ids.filtered("product_id")
        if not chosen:
            raise UserError(_("Choose a product on the lines that were not found."))
        chosen.action_add_to_receive()
        return True

    def _avea_apply_invoice_reading(self, parsed):
        self.ensure_one()
        self.with_context(avea_skip_pricing_wizard=True).write(self._avea_invoice_values(parsed))

    def _avea_invoice_values(self, parsed):
        self.ensure_one()
        mixin = self.env["avea.stock.mixin"]
        rate = (parsed.get("vat_rate") or 15.0) / 100.0
        inclusive = parsed.get("vat_mode") == "inclusive"
        partner = self.partner_id
        supplier_note = ""
        if not partner and not self.add_new_supplier:
            partner = self._avea_match_invoice_supplier(parsed.get("supplier_hint"), parsed.get("text"))
            if partner:
                supplier_note = _(
                    "Supplier set to %(name)s. Change it if that is wrong.",
                    name=partner.display_name,
                )
            else:
                supplier_note = _("The supplier was not filled in. Choose it.")
        matched_commands = []
        unmatched_commands = []
        printed_total = 0.0
        for row in parsed["lines"]:
            printed_total += (row["quantity"] or 0.0) * (row["unit_price"] or 0.0)
            cost = row["unit_price"]
            if inclusive and rate:
                cost = cost / (1.0 + rate)
            cost = mixin._avea_round_supplier_cost(cost)
            product, suggestion, supplier_code = self._avea_match_invoice_product(
                row["description"], row["codes"], partner
            )
            if product:
                matched_commands.append(
                    Command.create(
                        {
                            "product_id": product.id,
                            "quantity": row["quantity"],
                            "price_unit": cost,
                        }
                    )
                )
                self._avea_remember_supplier_code(product, supplier_code, partner)
            else:
                unmatched_commands.append(
                    Command.create(
                        {
                            "description": row["description"][:240],
                            "quantity": row["quantity"],
                            "price_unit": cost,
                            "supplier_code": supplier_code or False,
                            "product_id": suggestion.id if suggestion else False,
                        }
                    )
                )
        values = {
            "line_ids": matched_commands,
            "unmatched_line_ids": [Command.clear(), *unmatched_commands],
            "invoice_read_summary": self._avea_invoice_read_summary(
                parsed,
                len(matched_commands),
                len(unmatched_commands),
                printed_total,
                supplier_note,
            ),
        }
        if parsed.get("invoice_number") and not (self.invoice_number or "").strip():
            values["invoice_number"] = parsed["invoice_number"]
        if parsed.get("invoice_date"):
            values["invoice_date"] = parsed["invoice_date"]
        if partner and not self.partner_id and not self.add_new_supplier:
            values["partner_id"] = partner.id
        return values

    def _avea_invoice_read_summary(
        self, parsed, matched_count, unmatched_count, printed_total, supplier_note
    ):
        if parsed.get("source") == "ocr":
            source = _(
                "Read with built-in OCR on this server (the document was not sent anywhere). "
                "Scans misread more often, so check every line."
            )
        elif parsed.get("source") == "pdf":
            source = _("Read from the PDF text.")
        else:
            source = _("Read from the uploaded file.")
        mode = parsed.get("vat_mode")
        rate = parsed.get("vat_rate") or 15.0
        if mode == "inclusive":
            vat = _(
                "Prices include VAT at %(rate)s%%. Costs were reduced to the ex-tax amount.",
                rate=rate,
            )
        elif mode == "exclusive":
            vat = _("Prices are excluding VAT. Costs were entered as printed.")
        else:
            vat = _(
                "Could not tell if prices include VAT, so costs were entered exactly as printed. "
                "Change a cost if the invoice is VAT inclusive."
            )
        lines = [
            source,
            vat,
            self._avea_subtotal_note(parsed.get("subtotal"), printed_total),
            _(
                "Matched %(matched)s. Not found %(unmatched)s.",
                matched=matched_count,
                unmatched=unmatched_count,
            ),
        ]
        if supplier_note:
            lines.append(supplier_note)
        lines.append(
            _(
                "Nothing is received until you press Receive Stock. "
                "A closest product is only a suggestion until you press Add."
            )
        )
        return "\n".join(lines)

    def _avea_subtotal_note(self, printed_subtotal, printed_total):
        symbol = self.currency_id.symbol or ""
        lines_amount = f"{symbol} {printed_total:,.2f}".strip()
        if printed_subtotal is None:
            return _("Lines %(amount)s. No subtotal was printed on the invoice.", amount=lines_amount)
        invoice_amount = f"{symbol} {printed_subtotal:,.2f}".strip()
        if abs((printed_subtotal or 0.0) - printed_total) < 0.05:
            return _(
                "Lines %(lines)s. Invoice subtotal %(invoice)s.",
                lines=lines_amount,
                invoice=invoice_amount,
            )
        return _(
            "Lines %(lines)s. Invoice subtotal %(invoice)s. They differ, so check the lines.",
            lines=lines_amount,
            invoice=invoice_amount,
        )

    def _avea_remember_supplier_code(self, product, code, partner=None):
        """Store the supplier's code on the product when it does not have one yet."""
        partner = partner or self.partner_id
        if not product or not code or not partner:
            return
        template = product.product_tmpl_id
        current_supplier = template.avea_supplier_id
        if current_supplier and current_supplier != partner:
            return
        if (template.avea_supplier_code or "").strip():
            return
        template.avea_supplier_id = partner
        template.avea_supplier_code = code

    def _avea_match_invoice_product(self, description, codes, partner=None):
        """Return the product to fill in, a suggestion, and the supplier code to store.

        A line is filled in only when one product is clearly ahead and the size agrees.
        A close product that fails that test is returned as a suggestion.
        """
        Product = self.env["product.product"].browse()
        stored_code = _supplier_code_to_store(codes)
        by_code = self._avea_product_for_codes(codes, partner)
        if by_code:
            return by_code, Product, stored_code
        ranked = self._avea_rank_invoice_names(description)
        if not ranked:
            return Product, Product, stored_code
        best_score, best = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0
        size_ok = _size_agrees(description, best._avea_plain_name() or best.name)
        clearly_ahead = best_score >= 2 and best_score > second_score and size_ok
        if clearly_ahead:
            return best, Product, stored_code
        suggestion = best if best_score >= 2 else Product
        return Product, suggestion, stored_code

    def _avea_product_for_codes(self, codes, partner):
        Product = self.env["product.product"]
        base = [("is_storable", "=", True), ("purchase_ok", "=", True)]
        for code in codes or []:
            found = Product.search(
                base + ["|", ("default_code", "=", code), ("barcode", "=", code)],
                limit=2,
            )
            if len(found) == 1:
                return found
            sellers = self.env["product.supplierinfo"].search(
                [("product_code", "=", code)]
                + ([("partner_id", "=", partner.id)] if partner else []),
                limit=2,
            )
            if len(sellers) == 1:
                product = sellers.product_id or sellers.product_tmpl_id.product_variant_id
                if product and product.is_storable and product.purchase_ok:
                    return product
        return Product.browse()

    def _avea_rank_invoice_names(self, description):
        words = _name_words(description)
        if not words:
            return []
        Product = self.env["product.product"]
        base = [("is_storable", "=", True), ("purchase_ok", "=", True)]
        candidates = Product.browse()
        for word in words:
            if len(word) < 4:
                continue
            candidates |= Product.search(base + [("name", "ilike", word)], limit=25)
        scored = []
        for product in candidates:
            haystack = (product._avea_plain_name() or product.name or "").lower()
            score = sum(1 for word in words if word in haystack)
            if score:
                scored.append((score, product))
        scored.sort(key=lambda item: (item[0], -len(item[1].name or "")), reverse=True)
        return scored

    def _avea_match_invoice_supplier(self, hint, text):
        partners = self.env["res.partner"].search([("supplier_rank", ">", 0)], limit=200)
        blob = (text or "")[:1500].lower()
        hits = partners.filtered(
            lambda partner: partner.name and len(partner.name) >= 5 and partner.name.lower() in blob
        )
        if len(hits) == 1:
            return hits
        if hint:
            exact = partners.filtered(lambda partner: (partner.name or "").lower() == hint.lower())
            if len(exact) == 1:
                return exact
        return self.env["res.partner"].browse()


_LONG_CODE_RE = re.compile(r"^[A-Z]{2,}(?:-[A-Z0-9]+){2,}$")
_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*(kg|g|ml|l)\b"
    r"|(\d+(?:\.\d+)?)\s*(kg|g|ml|l)\b",
    re.IGNORECASE,
)


def re_words(description):
    return re.findall(r"[a-z0-9]+", (description or "").lower())


def _name_words(description):
    words = []
    for word in re_words(description):
        if word in _STOP_WORDS or len(word) < 3 or word.isdigit():
            continue
        words.append(word)
    return words


def _supplier_code_to_store(codes):
    for code in codes or []:
        if _LONG_CODE_RE.match(code or ""):
            return code
    return False


def _size_key(text):
    keys = []
    for match in _SIZE_RE.finditer(text or ""):
        if match.group(1):
            keys.append((float(match.group(1)), float(match.group(2)), match.group(3).lower()))
        else:
            keys.append((float(match.group(4)), match.group(5).lower()))
    return tuple(keys)


def _size_agrees(invoice_text, product_name):
    left, right = _size_key(invoice_text), _size_key(product_name)
    if not left or not right:
        return True
    return left == right
