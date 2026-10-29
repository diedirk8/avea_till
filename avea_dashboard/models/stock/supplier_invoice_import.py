# -*- coding: utf-8 -*-
import re

from odoo import Command, _, fields, models
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
    product_id = fields.Many2one(
        "product.product",
        string="Product",
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
        self._avea_apply_invoice_reading(parsed)
        return True

    def action_add_matched_invoice_lines(self):
        self.ensure_one()
        chosen = self.unmatched_line_ids.filtered("product_id")
        if not chosen:
            raise UserError(_("Choose a product on the lines that were not found."))
        chosen.action_add_to_receive()
        return True

    def _avea_apply_invoice_reading(self, parsed):
        self.ensure_one()
        mixin = self.env["avea.stock.mixin"]
        rate = (parsed.get("vat_rate") or 15.0) / 100.0
        inclusive = parsed.get("vat_mode") == "inclusive"
        matched_commands = []
        unmatched_commands = []
        for row in parsed["lines"]:
            cost = row["unit_price"]
            if inclusive and rate:
                cost = cost / (1.0 + rate)
            cost = mixin._avea_round_supplier_cost(cost)
            product = self._avea_match_invoice_product(row["description"], row["codes"])
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
            else:
                unmatched_commands.append(
                    Command.create(
                        {
                            "description": row["description"][:240],
                            "quantity": row["quantity"],
                            "price_unit": cost,
                        }
                    )
                )
        values = {
            "line_ids": matched_commands,
            "unmatched_line_ids": [Command.clear(), *unmatched_commands],
            "invoice_read_summary": self._avea_invoice_read_summary(
                parsed, len(matched_commands), len(unmatched_commands)
            ),
        }
        if parsed.get("invoice_number") and not (self.invoice_number or "").strip():
            values["invoice_number"] = parsed["invoice_number"]
        if parsed.get("invoice_date"):
            values["invoice_date"] = parsed["invoice_date"]
        if not self.partner_id and not self.add_new_supplier:
            partner = self._avea_match_invoice_supplier(parsed.get("supplier_hint"), parsed.get("text"))
            if partner:
                values["partner_id"] = partner.id
        self.with_context(avea_skip_pricing_wizard=True).write(values)

    def _avea_invoice_read_summary(self, parsed, matched_count, unmatched_count):
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
        return "\n".join(
            [
                source,
                vat,
                _(
                    "Matched %(matched)s. Not found %(unmatched)s.",
                    matched=matched_count,
                    unmatched=unmatched_count,
                ),
                _(
                    "Nothing is received until you press Receive Stock. "
                    "For a line that was not found, choose the product or create it with + New Stock Item."
                ),
            ]
        )

    def _avea_match_invoice_product(self, description, codes):
        """Return one product only when the invoice line is unambiguous."""
        Product = self.env["product.product"]
        base = [("is_storable", "=", True), ("purchase_ok", "=", True)]
        for code in codes or []:
            found = Product.search(
                base + ["|", ("default_code", "=", code), ("barcode", "=", code)],
                limit=2,
            )
            if len(found) == 1:
                return found
        words = [
            word
            for word in re_words(description)
            if word not in _STOP_WORDS and len(word) >= 3
        ]
        if not words:
            return Product.browse()
        needle = max(words, key=len)
        candidates = Product.search(base + [("name", "ilike", needle)], limit=30)
        scored = []
        for product in candidates:
            haystack = (product._avea_plain_name() or product.name or "").lower()
            score = sum(1 for word in words if word in haystack)
            if score:
                scored.append((score, len(haystack), product))
        if not scored:
            return Product.browse()
        scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        best_score, _length, best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0
        if best_score >= 2 and best_score > second:
            return best
        if len(scored) == 1 and best_score >= 1 and len(needle) >= 6:
            return best
        return Product.browse()

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


def re_words(description):
    return re.findall(r"[a-z0-9]+", (description or "").lower())
