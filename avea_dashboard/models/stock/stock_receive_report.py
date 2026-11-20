# -*- coding: utf-8 -*-
import logging

from markupsafe import escape

from odoo import _, models
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
        cost = line.price_unit_discounted or line.price_unit or 0.0
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
            "cost_before_discount": line.price_unit or 0.0,
            "discount": line.discount or 0.0,
            "retail_inc": retail_inc,
            "retail_ex": retail_ex,
            "markup": markup,
            "margin": margin,
            "profit_unit": profit_unit,
            "profit_line": profit_unit * qty,
            "line_total": line.price_total or 0.0,
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
            parts = [
                _(
                    "Cost %(old)s → %(new)s",
                    old=self._avea_receive_report_money(line.avea_previous_cost),
                    new=self._avea_receive_report_money(values["cost"]),
                )
            ]
            if choice == "cost_and_pricing":
                new_retail = line.avea_pending_retail or values["retail_inc"]
                if (
                    mixin._avea_compare_product_cost(
                        new_retail,
                        line.avea_previous_retail,
                    )
                    != 0
                ):
                    parts.append(
                        _(
                            "Retail %(old)s → %(new)s",
                            old=self._avea_receive_report_money(line.avea_previous_retail),
                            new=self._avea_receive_report_money(new_retail),
                        )
                    )
                else:
                    parts.append(_("Retail unchanged"))
            else:
                parts.append(_("Retail unchanged"))
            parts.append(
                _("Markup %(markup)s · Margin %(margin)s · Profit %(profit)s / unit",
                  markup=self._avea_receive_report_percent(values["markup"]),
                  margin=self._avea_receive_report_percent(values["margin"]),
                  profit=self._avea_receive_report_money(values["profit_unit"]))
            )
            changes.append(
                {
                    "product": values["name"],
                    "detail": " · ".join(parts),
                    "choice": self._avea_receive_report_pricing_label(choice),
                }
            )
        return changes

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

    def _avea_receive_report_metric_cell(self, label, value, last=False):
        border = "none" if last else "1px solid #eef0f3"
        return (
            "<td style='padding:8px 10px;border-bottom:%s;width:25%%;vertical-align:top;'>"
            "<div style='font-size:11px;color:#6b7280;'>%s</div>"
            "<div style='font-weight:600;'>%s</div>"
            "</td>"
            % (border, escape(label), escape(value))
        )

    def _avea_receive_report_item_html(self, line):
        values = self._avea_receive_report_line_values(line)
        codes = [
            _("SKU %(sku)s", sku=self._avea_receive_report_text(values["sku"])),
            _("Barcode %(barcode)s", barcode=self._avea_receive_report_text(values["barcode"])),
            _(
                "Supplier code %(code)s",
                code=self._avea_receive_report_text(values["supplier_code"]),
            ),
        ]
        discount_note = ""
        if values["discount"]:
            discount_note = (
                "<div style='color:#6b7280;font-size:12px;margin-top:2px;'>"
                + escape(
                    _(
                        "Discount %(percent)s%% (list cost %(cost)s)",
                        percent=values["discount"],
                        cost=self._avea_receive_report_money(values["cost_before_discount"]),
                    )
                )
                + "</div>"
            )
        choice_note = ""
        choice_label = self._avea_receive_report_pricing_label(values["pricing_choice"])
        if choice_label:
            choice_note = (
                "<div style='color:#6b7280;font-size:12px;margin-top:2px;'>"
                + escape(choice_label)
                + "</div>"
            )
        return f"""
<table style="width:100%;border-collapse:collapse;margin:0 0 12px 0;border:1px solid #e5e7eb;border-radius:8px;">
  <tr>
    <td colspan="4" style="padding:10px 12px;background:#f8fafc;border-bottom:1px solid #e5e7eb;">
      <div style="font-weight:700;">{escape(values["name"])}</div>
      <div style="color:#6b7280;font-size:12px;margin-top:2px;">{escape(" · ".join(codes))}</div>
      {discount_note}{choice_note}
    </td>
  </tr>
  <tr>
    {self._avea_receive_report_metric_cell(_("Qty"), self._avea_receive_report_qty(values["qty"]))}
    {self._avea_receive_report_metric_cell(_("EX-tax cost"), self._avea_receive_report_money(values["cost"]))}
    {self._avea_receive_report_metric_cell(_("Retail INC tax"), self._avea_receive_report_money(values["retail_inc"]))}
    {self._avea_receive_report_metric_cell(_("Retail EX tax"), self._avea_receive_report_money(values["retail_ex"]), last=True)}
  </tr>
  <tr>
    {self._avea_receive_report_metric_cell(_("Markup"), self._avea_receive_report_percent(values["markup"]))}
    {self._avea_receive_report_metric_cell(_("Margin"), self._avea_receive_report_percent(values["margin"]))}
    {self._avea_receive_report_metric_cell(_("Profit / unit"), self._avea_receive_report_money(values["profit_unit"]))}
    {self._avea_receive_report_metric_cell(_("Line profit"), self._avea_receive_report_money(values["profit_line"]), last=True)}
  </tr>
  <tr>
    <td colspan="3" style="padding:8px 12px;">{escape(_("Line total"))}</td>
    <td style="padding:8px 12px;text-align:right;font-weight:700;">{escape(self._avea_receive_report_money(values["line_total"]))}</td>
  </tr>
</table>
"""

    def _avea_receive_report_charge_html(self, charge):
        return f"""
<table style="width:100%;border-collapse:collapse;margin:0 0 12px 0;border:1px solid #e5e7eb;">
  <tr>
    <td style="padding:10px 12px;">
      <div style="font-weight:700;">{escape(charge.name or _("Additional charge"))}</div>
      <div style="color:#6b7280;font-size:12px;">{escape(_("Not a stock item — billed as an expense"))}</div>
    </td>
    <td style="padding:10px 12px;text-align:right;font-weight:700;white-space:nowrap;">
      {escape(self._avea_receive_report_money(charge.price_total))}
    </td>
  </tr>
</table>
"""

    def _avea_receive_report_body_html(self):
        self.ensure_one()
        company = self.company_id
        accent = (company.avea_receipt_email_accent_color or "#c45c26").strip() or "#c45c26"
        supplier = self.partner_id.display_name or _("Supplier")
        received_by = self.user_id.display_name or _("Unknown")
        received_date = format_date(self.env, self.received_date) if self.received_date else ""
        issues = self._avea_receive_report_issues()
        changes = self._avea_receive_report_price_changes()
        lines = self.line_ids.filtered("product_id")
        profit_total = sum(
            self._avea_receive_report_line_values(line)["profit_line"] for line in lines
        )

        if issues:
            issue_items = "".join(
                f"<li style='margin:0 0 6px 0;'>{escape(issue)}</li>" for issue in issues
            )
            issues_block = (
                "<div style='margin:0 0 18px 0;padding:14px 16px;background:#fff7ed;"
                "border:1px solid #fdba74;border-radius:8px;'>"
                "<p style='margin:0 0 8px 0;font-weight:600;color:#9a3412;'>"
                + escape(_("Needs attention"))
                + "</p>"
                f"<ul style='margin:0;padding-left:18px;color:#7c2d12;'>{issue_items}</ul>"
                "</div>"
            )
        else:
            issues_block = (
                "<div style='margin:0 0 18px 0;padding:14px 16px;background:#f0fdf4;"
                "border:1px solid #86efac;border-radius:8px;color:#166534;'>"
                + escape(_("No issues recorded on this receive."))
                + "</div>"
            )

        if changes:
            change_rows = "".join(
                "<tr>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #eef0f3;'>{escape(change['product'])}</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #eef0f3;'>{escape(change['choice'])}</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #eef0f3;'>{escape(change['detail'])}</td>"
                "</tr>"
                for change in changes
            )
            changes_block = (
                "<h2 style='margin:0 0 10px 0;font-size:16px;color:#111827;'>"
                + escape(_("Price changes"))
                + "</h2>"
                "<table style='width:100%;border-collapse:collapse;margin:0 0 18px 0;'>"
                "<thead><tr>"
                "<th style='padding:8px 10px;background:#f8fafc;border-bottom:1px solid #e5e7eb;text-align:left;font-size:12px;color:#6b7280;'>"
                + escape(_("Product"))
                + "</th>"
                "<th style='padding:8px 10px;background:#f8fafc;border-bottom:1px solid #e5e7eb;text-align:left;font-size:12px;color:#6b7280;'>"
                + escape(_("Action"))
                + "</th>"
                "<th style='padding:8px 10px;background:#f8fafc;border-bottom:1px solid #e5e7eb;text-align:left;font-size:12px;color:#6b7280;'>"
                + escape(_("Change"))
                + "</th>"
                "</tr></thead>"
                f"<tbody>{change_rows}</tbody></table>"
            )
        else:
            changes_block = (
                "<p style='margin:0 0 18px 0;color:#6b7280;'>"
                + escape(_("No catalogue prices were changed."))
                + "</p>"
            )

        item_blocks = "".join(self._avea_receive_report_item_html(line) for line in lines)
        charge_blocks = "".join(
            self._avea_receive_report_charge_html(charge)
            for charge in self.charge_ids.filtered(lambda charge: charge.amount)
        )

        return f"""
<div style="font-family:Arial,Helvetica,sans-serif;color:#1f2937;font-size:14px;line-height:1.5;max-width:800px;">
  <div style="border-bottom:3px solid {escape(accent)};padding-bottom:12px;margin-bottom:18px;">
    <div style="font-size:12px;letter-spacing:0.04em;text-transform:uppercase;color:#6b7280;">
      {escape(company.name)}
    </div>
    <h1 style="margin:6px 0 0 0;font-size:22px;line-height:1.25;color:#111827;">
      {escape(_("Stock received"))}
    </h1>
    <p style="margin:8px 0 0 0;color:#6b7280;">
      {escape(supplier)}
      &nbsp;·&nbsp; {escape(self.invoice_number or "")}
      &nbsp;·&nbsp; {escape(received_date)}
    </p>
  </div>

  <table style="width:100%;border-collapse:collapse;margin:0 0 18px 0;">
    <tr>
      <td style="width:50%;padding:10px 12px;background:#f8fafc;border:1px solid #e5e7eb;">
        <div style="font-size:12px;color:#6b7280;">{escape(_("Received by"))}</div>
        <div style="font-weight:600;">{escape(received_by)}</div>
      </td>
      <td style="width:50%;padding:10px 12px;background:#f8fafc;border:1px solid #e5e7eb;border-left:none;">
        <div style="font-size:12px;color:#6b7280;">{escape(_("Payment"))}</div>
        <div style="font-weight:600;">{escape(self.payment_status or _("Unpaid"))}</div>
      </td>
    </tr>
  </table>

  {issues_block}
  {changes_block}

  <h2 style="margin:0 0 10px 0;font-size:16px;color:#111827;">{escape(_("Items received"))}</h2>
  {item_blocks}
  {charge_blocks}

  <table style="width:100%;border-collapse:collapse;margin:12px 0 18px 0;">
    <tr>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;">{escape(_("Products"))}</td>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;text-align:right;font-weight:600;">{self.product_count}</td>
    </tr>
    <tr>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;">{escape(_("Quantity"))}</td>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;text-align:right;font-weight:600;">{escape(self._avea_receive_report_qty(self.quantity_total))}</td>
    </tr>
    <tr>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;">{escape(_("Estimated profit"))}</td>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;text-align:right;font-weight:600;">{escape(self._avea_receive_report_money(profit_total))}</td>
    </tr>
    <tr>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;">{escape(_("Ex-tax total"))}</td>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;text-align:right;">{escape(self._avea_receive_report_money(self.amount_untaxed))}</td>
    </tr>
    <tr>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;">{escape(_("Tax"))}</td>
      <td style="padding:8px 0;border-bottom:1px solid #eef0f3;text-align:right;">{escape(self._avea_receive_report_money(self.amount_tax))}</td>
    </tr>
    <tr>
      <td style="padding:8px 0;">{escape(_("Total"))}</td>
      <td style="padding:8px 0;text-align:right;font-weight:600;">{escape(self._avea_receive_report_money(self.amount_total))}</td>
    </tr>
  </table>

  <p style="margin:0;color:#6b7280;font-size:12px;">
    {escape(_("This is an automated Receive Stock report from Avea POS. Profit is retail EX tax minus the received EX-tax cost."))}
  </p>
</div>
"""

    def _avea_send_receive_report(self):
        """Email the owner a summary after stock is received. Never blocks the receive."""
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
