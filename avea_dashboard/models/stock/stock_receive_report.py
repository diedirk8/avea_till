# -*- coding: utf-8 -*-
import base64
import logging
import re

from markupsafe import Markup, escape

from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools import formataddr, format_date
from odoo.tools.misc import formatLang

_logger = logging.getLogger(__name__)


class AveaStockReceiveReport(models.Model):
    _inherit = "avea.stock.receive"

    def _avea_receive_report_money(self, amount):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        return formatLang(self.env, amount or 0.0, currency_obj=currency)

    def _avea_receive_report_qty(self, qty):
        if qty is None:
            return "0"
        if float(qty).is_integer():
            return "%d" % int(qty)
        return ("%0.2f" % qty).rstrip("0").rstrip(".")

    def _avea_receive_report_percent(self, value):
        return "%.1f%%" % (value or 0.0)

    def _avea_receive_report_text(self, value):
        text = (value or "").strip()
        return text or "—"

    def _avea_receive_report_pricing_label(self, choice):
        return {
            "keep": _("Kept current pricing"),
            "cost_only": _("Updated cost only"),
            "cost_and_pricing": _("Updated cost and retail"),
        }.get(choice, "")

    def _avea_receive_report_supplier_code(self, line):
        seller = line._avea_seller()
        if seller and seller.product_code:
            return seller.product_code
        template = line.product_id.product_tmpl_id
        return template.avea_supplier_code or ""

    def _avea_receive_report_line_values(self, line):
        """Full per-line facts for the owner email."""
        self.ensure_one()
        product = line.product_id
        template = product.product_tmpl_id
        catalog_cost = line.price_unit or 0.0
        cost = line.price_unit_discounted or catalog_cost
        retail_inc = template.list_price or 0.0
        retail_ex, markup, margin = template._avea_pricing_from_cost_retail(
            cost, retail_inc
        )
        qty = line.quantity or 0.0
        profit_unit = retail_ex - cost
        return {
            "name": product.display_name,
            "sku": product.default_code or "",
            "barcode": product.barcode or "",
            "supplier_code": self._avea_receive_report_supplier_code(line),
            "qty": qty,
            "cost": cost,
            "catalog_cost": catalog_cost,
            "cost_before_discount": catalog_cost,
            "discount": line.discount or 0.0,
            "retail_inc": retail_inc,
            "retail_ex": retail_ex,
            "markup": markup,
            "margin": margin,
            "profit_unit": profit_unit,
            "profit_line": profit_unit * qty,
            "line_total": line.price_subtotal or 0.0,
            "pricing_choice": line.avea_pricing_choice,
        }

    def _avea_receive_report_issues(self):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        mixin = self.env["avea.stock.mixin"]
        issues = []
        if self.totals_mismatch:
            issues.append(
                _(
                    "Invoice total %(invoice)s does not match received total %(received)s "
                    "(difference %(difference)s).",
                    invoice=self._avea_receive_report_money(self.invoice_total),
                    received=self._avea_receive_report_money(self.amount_total),
                    difference=self._avea_receive_report_money(self.invoice_difference),
                )
            )
        for unmatched in self.unmatched_line_ids:
            label = unmatched.description or _("Unnamed invoice line")
            extras = []
            if unmatched.sku:
                extras.append(_("SKU %(sku)s", sku=unmatched.sku))
            if unmatched.supplier_code:
                extras.append(
                    _("Supplier code %(code)s", code=unmatched.supplier_code)
                )
            extra = " · ".join(extras)
            if extra:
                label = "%s (%s)" % (label, extra)
            issues.append(
                _(
                    "Not received: %(item)s × %(qty)s at %(cost)s.",
                    item=label,
                    qty=self._avea_receive_report_qty(unmatched.quantity),
                    cost=self._avea_receive_report_money(unmatched.price_unit),
                )
            )
        for line in self.line_ids.filtered("product_id"):
            if line.avea_pricing_choice != "keep":
                continue
            if (
                mixin._avea_compare_supplier_cost(
                    line.price_unit,
                    line.avea_previous_cost,
                )
                != 0
            ):
                issues.append(
                    _(
                        "%(product)s: invoice cost %(invoice)s differs from catalogue "
                        "cost %(catalogue)s. Current pricing was kept.",
                        product=line.product_id.display_name,
                        invoice=self._avea_receive_report_money(line.price_unit),
                        catalogue=self._avea_receive_report_money(line.avea_previous_cost),
                    )
                )
        residual = self.bill_id.amount_residual if self.bill_id else 0.0
        if self.bill_id and not currency.is_zero(residual):
            issues.append(
                _(
                    "Vendor bill still due %(amount)s.",
                    amount=self._avea_receive_report_money(residual),
                )
            )
        return issues

    def _avea_receive_report_price_changes(self):
        self.ensure_one()
        mixin = self.env["avea.stock.mixin"]
        changes = []
        for line in self.line_ids.filtered("product_id"):
            choice = line.avea_pricing_choice
            if choice not in ("cost_only", "cost_and_pricing"):
                continue
            values = self._avea_receive_report_line_values(line)
            catalog_cost = values["catalog_cost"]
            cost_changed = (
                mixin._avea_compare_supplier_cost(
                    catalog_cost,
                    line.avea_previous_cost,
                )
                != 0
            )
            retail_changed = False
            new_retail = values["retail_inc"]
            if choice == "cost_and_pricing":
                new_retail = line.avea_pending_retail or values["retail_inc"]
                retail_changed = (
                    mixin._avea_compare_product_cost(
                        new_retail,
                        line.avea_previous_retail,
                    )
                    != 0
                )
            if not cost_changed and not retail_changed:
                continue
            parts = []
            if cost_changed:
                parts.append(
                    _(
                        "Buying cost %(old)s → %(new)s",
                        old=self._avea_receive_report_money(line.avea_previous_cost),
                        new=self._avea_receive_report_money(catalog_cost),
                    )
                )
            else:
                parts.append(
                    _(
                        "Buying cost unchanged at %(cost)s",
                        cost=self._avea_receive_report_money(catalog_cost),
                    )
                )
            if retail_changed:
                parts.append(
                    _(
                        "Selling price %(old)s → %(new)s",
                        old=self._avea_receive_report_money(line.avea_previous_retail),
                        new=self._avea_receive_report_money(new_retail),
                    )
                )
            else:
                parts.append(_("Selling price unchanged"))
            retail_ex, markup, margin = line.product_id.product_tmpl_id._avea_pricing_from_cost_retail(
                catalog_cost, new_retail
            )
            parts.append(
                _("Markup %(markup)s · Margin %(margin)s · Profit %(profit)s / unit",
                  markup=self._avea_receive_report_percent(markup),
                  margin=self._avea_receive_report_percent(margin),
                  profit=self._avea_receive_report_money(retail_ex - catalog_cost))
            )
            changes.append(
                {
                    "product": values["name"],
                    "detail": " · ".join(parts),
                    "choice": self._avea_receive_report_pricing_label(choice),
                    "retail_changed": retail_changed,
                }
            )
        return changes

    def _avea_receive_report_price_changes_copy(self, changes):
        """Plain-language heading so cost-only updates are not read as shelf prices."""
        if not changes:
            return {
                "title": "",
                "intro": _(
                    "No catalogue buying costs or selling prices were changed. "
                    "A line discount on this invoice is this bill only."
                ),
            }
        if any(change.get("retail_changed") for change in changes):
            return {
                "title": _("Cost and selling price updates"),
                "intro": _(
                    "The typed EX-tax unit cost and/or till selling price was updated. "
                    "A line discount on this invoice is this bill only and does not change catalogue cost."
                ),
            }
        return {
            "title": _("Buying cost updates"),
            "intro": _(
                "The stored buying cost was updated because the typed EX-tax unit cost "
                "differed from the catalogue. A line discount on this invoice is this bill "
                "only and does not change the usual cost. Selling prices on the till were not changed."
            ),
        }

    def _avea_receive_report_subject(self):
        self.ensure_one()
        supplier = self.partner_id.display_name or _("Supplier")
        invoice = (self.invoice_number or "").strip()
        if invoice:
            return _(
                "Stock received — %(supplier)s %(invoice)s",
                supplier=supplier,
                invoice=invoice,
            )
        return _("Stock received — %(supplier)s", supplier=supplier)

    def _avea_receive_report_pdf_filename(self):
        self.ensure_one()
        supplier = re.sub(
            r"[\\/]+", "-", self.partner_id.display_name or _("Supplier")
        )
        invoice = re.sub(r"[\\/]+", "-", (self.invoice_number or "").strip())
        if invoice:
            return _("Stock received - %s %s.pdf") % (supplier, invoice)
        return _("Stock received - %s.pdf") % supplier

    def get_stock_receive_report_payload(self):
        """Structured data for the Receive Stock PDF."""
        self.ensure_one()
        lines = []
        profit_total = 0.0
        for line in self.line_ids.filtered("product_id"):
            values = self._avea_receive_report_line_values(line)
            profit_total += values["profit_line"]
            sku = self._avea_receive_report_text(values["sku"])
            barcode = self._avea_receive_report_text(values["barcode"])
            supplier_code = self._avea_receive_report_text(values["supplier_code"])
            codes = [
                _("SKU %(sku)s", sku=sku),
                _("Barcode %(barcode)s", barcode=barcode),
                _("Supplier code %(code)s", code=supplier_code),
            ]
            discount_note = ""
            if values["discount"]:
                discount_note = _(
                    "Discount %(percent)s%% (list cost %(cost)s)",
                    percent=values["discount"],
                    cost=self._avea_receive_report_money(values["cost_before_discount"]),
                )
            lines.append(
                {
                    "name": values["name"],
                    "codes": " · ".join(codes),
                    "sku": values["sku"],
                    "barcode": values["barcode"],
                    "sku_barcode": sku,
                    "barcode_display": barcode,
                    "supplier_code": values["supplier_code"],
                    "discount_note": discount_note,
                    "pricing_label": self._avea_receive_report_pricing_label(
                        values["pricing_choice"]
                    ),
                    "qty": self._avea_receive_report_qty(values["qty"]),
                    "cost": self._avea_receive_report_money(values["cost"]),
                    "retail": self._avea_receive_report_money(values["retail_ex"]),
                    "retail_inc": self._avea_receive_report_money(values["retail_inc"]),
                    "markup": self._avea_receive_report_percent(values["markup"]),
                    "margin": self._avea_receive_report_percent(values["margin"]),
                    "profit_line": self._avea_receive_report_money(values["profit_line"]),
                    "line_total": self._avea_receive_report_money(values["line_total"]),
                }
            )
        charges = [
            {
                "name": charge.name or _("Additional charge"),
                "total": self._avea_receive_report_money(charge.price_subtotal),
            }
            for charge in self.charge_ids.filtered(lambda charge: charge.amount)
        ]
        price_changes = self._avea_receive_report_price_changes()
        price_copy = self._avea_receive_report_price_changes_copy(price_changes)
        return {
            "supplier": self.partner_id.display_name or _("Supplier"),
            "invoice": (self.invoice_number or "").strip() or "—",
            "received_date": format_date(self.env, self.received_date)
            if self.received_date
            else "",
            "received_by": self.user_id.display_name or _("Unknown"),
            "payment_status": self.payment_status or _("Unpaid"),
            "issues": self._avea_receive_report_issues(),
            "price_changes": price_changes,
            "price_changes_title": price_copy["title"],
            "price_changes_intro": price_copy["intro"],
            "lines": lines,
            "charges": charges,
            "product_count": self.product_count,
            "quantity_total": self._avea_receive_report_qty(self.quantity_total),
            "profit_total": self._avea_receive_report_money(profit_total),
            "amount_untaxed": self._avea_receive_report_money(self.amount_untaxed),
            "amount_tax": self._avea_receive_report_money(self.amount_tax),
            "amount_total": self._avea_receive_report_money(self.amount_total),
        }

    def _avea_receive_report_pdf_content(self):
        self.ensure_one()
        report = self.env.ref("avea_till.action_report_avea_stock_receive")
        pdf_content, _report_format = report.with_context(
            force_report_rendering=True,
            report_pdf_no_attachment=True,
        )._render_qweb_pdf(
            "avea_till.report_avea_stock_receive_document",
            res_ids=self.ids,
        )
        if not pdf_content or not pdf_content.startswith(b"%PDF"):
            raise UserError(_("The stock receive PDF could not be created."))
        return pdf_content

    def _avea_receive_report_body_html(self):
        """Short email body. Line-level detail lives in the attached PDF."""
        self.ensure_one()
        payload = self.get_stock_receive_report_payload()
        company = self.company_id
        accent = (company.avea_receipt_email_accent_color or "#c45c26").strip() or "#c45c26"
        if payload["issues"]:
            issue_items = "".join(
                f"<br/>{escape(issue)}" for issue in payload["issues"]
            )
            issues_block = (
                f'<p style="margin:0 0 16px 0;color:#9a3412;">'
                f"<strong>{escape(_('Needs attention'))}</strong>"
                f"{issue_items}</p>"
            )
        else:
            issues_block = ""
        # Keep this an f-string (never str + Markup). Concatenating a plain
        # HTML string with escape() escapes the tags, which Gmail then shows.
        return Markup(
            f"""
<div style="font-family:Arial,Helvetica,sans-serif;color:#1f2937;font-size:14px;line-height:1.5;max-width:640px;">
  <div style="border-bottom:3px solid {escape(accent)};padding-bottom:12px;margin-bottom:16px;">
    <div style="font-size:12px;letter-spacing:0.04em;text-transform:uppercase;color:#6b7280;">
      {escape(company.name)}
    </div>
    <h1 style="margin:6px 0 0 0;font-size:20px;line-height:1.25;color:#111827;">
      {escape(_("Stock received"))}
    </h1>
  </div>
  <p style="margin:0 0 8px 0;">
    {escape(payload["supplier"])}
    &nbsp;·&nbsp; {escape(payload["invoice"])}
    &nbsp;·&nbsp; {escape(payload["received_date"])}
  </p>
  <p style="margin:0 0 16px 0;color:#6b7280;">
    {escape(_("Received by %(name)s", name=payload["received_by"]))}
    &nbsp;·&nbsp; {escape(payload["payment_status"])}
    &nbsp;·&nbsp; {escape(_("Total %(amount)s", amount=payload["amount_total"]))}
  </p>
  {issues_block}
  <p style="margin:0;color:#6b7280;font-size:13px;">
    {escape(_("The full receive report is attached as a PDF."))}
  </p>
</div>
"""
        )

    def _avea_send_receive_report(self):
        """Email the owner a PDF after stock is received. Never blocks the receive."""
        self.ensure_one()
        if self.state != "done":
            return False
        company = self.company_id
        recipients = company._avea_stock_receive_report_recipients()
        if not recipients:
            _logger.info(
                "Skipping Receive Stock report for receive %s: no owner email configured.",
                self.id,
            )
            return False
        sender_email = company._avea_receipt_email_sender_email()
        if not sender_email:
            parsed = company._avea_parse_email_list(company.email)
            sender_email = parsed[0] if parsed else False
        if not sender_email:
            _logger.warning(
                "Skipping Receive Stock report for receive %s: no sender email configured.",
                self.id,
            )
            return False
        pdf_content = self._avea_receive_report_pdf_content()
        filename = self._avea_receive_report_pdf_filename()
        attachment = (
            self.env["ir.attachment"]
            .sudo()
            .create(
                {
                    "name": filename,
                    "type": "binary",
                    "datas": base64.b64encode(pdf_content),
                    "mimetype": "application/pdf",
                    "res_model": self._name,
                    "res_id": self.id,
                }
            )
        )
        sender_name = company._avea_receipt_email_business_name() or company.name
        mail = (
            self.env["mail.mail"]
            .sudo()
            .create(
                {
                    "subject": self._avea_receive_report_subject(),
                    "body_html": self._avea_receive_report_body_html(),
                    "email_from": formataddr((sender_name, sender_email)),
                    "email_to": ", ".join(recipients),
                    "reply_to": company._avea_receipt_email_reply_to() or sender_email,
                    "attachment_ids": [(4, attachment.id)],
                    "auto_delete": True,
                }
            )
        )
        mail.send()
        _logger.info(
            "Receive Stock report emailed for receive %s to %s",
            self.id,
            ", ".join(recipients),
        )
        return True
