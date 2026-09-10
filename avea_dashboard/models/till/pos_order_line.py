import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date


class PosOrderLine(models.Model):
    _inherit = ["pos.order.line", "avea.performance.analytics.mixin"]

    avea_order_date = fields.Datetime(
        string="Sale date",
        related="order_id.date_order",
        store=True,
        index=True,
        readonly=True,
    )
    avea_order_partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        related="order_id.partner_id",
        store=True,
        index=True,
        readonly=True,
    )
    avea_order_reference = fields.Char(
        string="Order #",
        compute="_compute_avea_order_reference",
        store=True,
        index=True,
        readonly=True,
    )
    avea_product_reference = fields.Char(
        string="Ref",
        compute="_compute_avea_product_display",
        store=True,
        index=True,
        readonly=True,
    )
    avea_product_display = fields.Char(
        string="Product name",
        compute="_compute_avea_product_display",
        store=True,
        index=True,
        readonly=True,
    )
    @api.depends("order_id.pos_reference", "order_id.name")
    def _compute_avea_order_reference(self):
        for line in self:
            order = line.order_id
            if not order:
                line.avea_order_reference = False
                continue
            reference = order._avea_till_display_reference()
            line.avea_order_reference = reference or str(order.id)

    @api.depends(
        "full_product_name",
        "product_id.display_name",
        "product_id.name",
        "product_id.default_code",
    )
    def _compute_avea_product_display(self):
        bracket_ref_re = re.compile(r"^\[(?P<ref>[^\]]+)\]\s*(?P<name>.*)$")
        for line in self:
            reference = (line.product_id.default_code or "").strip()
            raw = (
                line.full_product_name
                or line.product_id.display_name
                or line.product_id.name
                or ""
            ).strip()
            name = raw
            if raw:
                match = bracket_ref_re.match(raw)
                if match:
                    bracket_ref = match.group("ref").strip()
                    bracket_name = match.group("name").strip()
                    if not reference:
                        reference = bracket_ref
                    name = bracket_name or raw
                elif reference and raw.startswith(f"[{reference}]"):
                    name = raw[len(f"[{reference}]") :].strip() or raw
            line.avea_product_reference = reference or False
            line.avea_product_display = name or raw

    @api.model
    def _avea_sales_ledger_domain(self):
        """Completed POS sale lines across all sessions (source: pos.order.line)."""
        paid_states = self.env["pos.session"]._avea_paid_order_states()
        return [
            ("order_id.state", "in", paid_states),
            ("product_id", "!=", False),
            ("product_id.type", "not in", ("service", "combo")),
            ("combo_line_ids", "=", False),
            ("qty", "!=", 0.0),
        ]

    @api.model
    def _avea_sales_ledger_search_domain(self, *, product=None, customer=None, order_ref=None, date_from=None, date_to=None):
        """Build filter domain for tests and programmatic search."""
        domain = list(self._avea_sales_ledger_domain())
        if product:
            domain += [
                "|",
                "|",
                ("avea_product_display", "ilike", product),
                ("avea_product_reference", "ilike", product),
                ("product_id", "ilike", product),
            ]
        if customer:
            domain.append(("avea_order_partner_id", "ilike", customer))
        if order_ref:
            domain += [
                "|",
                ("avea_order_reference", "ilike", order_ref),
                ("order_id.name", "ilike", order_ref),
            ]
        if date_from:
            domain.append(("avea_order_date", ">=", date_from))
        if date_to:
            domain.append(("avea_order_date", "<=", date_to))
        return domain

    @api.model
    def _avea_format_ledger_date(self, dt):
        if not dt:
            return False
        return format_date(self.env, fields.Datetime.to_datetime(dt).date())

    @api.model
    def avea_sales_ledger_banner_info(self, domain=None):
        """Summary text for the Sales Ledger hero banner."""
        domain = list(domain or self._avea_sales_ledger_domain())
        total = self.search_count(domain)
        if not total:
            return {
                "total": 0,
                "range_display": _("No sale lines match the current filters"),
                "summary_display": _("0 sale lines"),
            }

        oldest = self.search(domain, order="avea_order_date asc, id asc", limit=1)
        newest = self.search(domain, order="avea_order_date desc, id desc", limit=1)
        oldest_label = self._avea_format_ledger_date(oldest.avea_order_date)
        newest_label = self._avea_format_ledger_date(newest.avea_order_date)
        if oldest_label == newest_label:
            range_display = oldest_label
        else:
            range_display = _("%(from)s – %(to)s") % {
                "from": oldest_label,
                "to": newest_label,
            }

        summary_display = _("%(count)s sale lines") % {
            "count": f"{total:,}",
        }
        return {
            "total": total,
            "range_display": range_display,
            "summary_display": summary_display,
        }

    def action_avea_open_pos_order(self):
        self.ensure_one()
        order = self.order_id
        if not order:
            raise UserError(_("This sale line is not linked to an order."))
        return {
            "type": "ir.actions.act_window",
            "name": _("POS Order"),
            "res_model": "pos.order",
            "res_id": order.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    @api.model
    def action_avea_open_sales_ledger(self):
        """Open the global Sales Ledger with the standard completed-sale domain."""
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "avea_till.action_avea_sales_ledger_window"
        )
        action["domain"] = self._avea_sales_ledger_domain()
        return action
