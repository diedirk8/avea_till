import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero
from odoo.tools.misc import format_date, format_time


class PosOrderLine(models.Model):
    _inherit = ["pos.order.line", "avea.performance.analytics.mixin"]

    avea_retail_unit_ex_tax = fields.Float(
        string="Retail unit EX tax at sale",
        digits="Product Price",
        copy=False,
        help="Catalog retail price (EX tax) captured when the sale line was created.",
    )
    avea_order_date = fields.Datetime(
        string="Sale date",
        related="order_id.date_order",
        store=True,
        index=True,
        readonly=True,
    )
    avea_order_date_label = fields.Char(
        string="Date / Time",
        compute="_compute_avea_order_date_label",
        store=True,
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
    @api.depends("avea_order_date")
    def _compute_avea_order_date_label(self):
        for line in self:
            if not line.avea_order_date:
                line.avea_order_date_label = False
                continue
            dt = fields.Datetime.context_timestamp(line, line.avea_order_date)
            date_part = format_date(line.env, dt.date(), date_format="d MMM")
            time_part = format_time(line.env, dt.time(), time_format="short")
            line.avea_order_date_label = f"{date_part}\n{time_part}"

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

    @api.model_create_multi
    def create(self, vals_list):
        Product = self.env["product.product"]
        for vals in vals_list:
            if vals.get("avea_retail_unit_ex_tax") or not vals.get("product_id"):
                continue
            product = Product.browse(vals["product_id"])
            if not product or product.type in ("service", "combo"):
                continue
            template = product.product_tmpl_id
            if template:
                _, _, retail_ex, _, _ = template._avea_pricing_tuple()
                vals["avea_retail_unit_ex_tax"] = retail_ex
        return super().create(vals_list)

    def _avea_sale_time_retail_unit_ex_tax(self):
        """Normal retail EX tax at sale time (stored), with legacy fallbacks."""
        self.ensure_one()
        if self.avea_retail_unit_ex_tax:
            return float(self.avea_retail_unit_ex_tax)
        if self.discount:
            return float(self.price_unit or 0.0)
        qty = float(self.qty or 0.0)
        if qty:
            return abs(float(self.price_subtotal or 0.0) / qty)
        return float(self.price_unit or 0.0)

    def _avea_sale_time_retail_unit_inc_tax(self):
        """Normal retail INC tax at sale time (from stored EX retail)."""
        self.ensure_one()
        template = self.product_id.product_tmpl_id
        if not template:
            return 0.0
        return template._avea_retail_inc_vat_from_ex(
            self._avea_sale_time_retail_unit_ex_tax()
        )

    def _avea_discount_given_ex_tax(self):
        """Signed discount EX tax: positive when less than normal retail was charged."""
        self.ensure_one()
        if self.avea_combo_program_id or self.is_reward_line:
            return -float(self.price_subtotal or 0.0)
        if (
            not self.product_id
            or self.product_id.type in ("service", "combo")
            or self.combo_line_ids
        ):
            return 0.0
        qty = float(self.qty or 0.0)
        if not qty:
            return 0.0
        currency = self.order_id.currency_id or self.env.company.currency_id
        actual = float(self.price_subtotal or 0.0)
        # Some refund lines keep a positive subtotal while qty is negative.
        if qty < 0.0 and actual > 0.0:
            actual = -actual
        # No line discount % and customer paid shelf INC tax (or more): not a discount.
        # This avoids EX-tax / tax-inclusive conversion penny gaps on full-price sales.
        if not self.discount:
            retail_unit_inc = self._avea_sale_time_retail_unit_inc_tax()
            shelf_inc = currency.round(retail_unit_inc * abs(qty))
            actual_inc = currency.round(abs(float(self.price_subtotal_incl or 0.0)))
            if float_compare(
                actual_inc, shelf_inc, precision_rounding=currency.rounding
            ) >= 0:
                return 0.0
        retail_ex = self._avea_sale_time_retail_unit_ex_tax()
        gap = currency.round((retail_ex * qty) - actual)
        if float_is_zero(gap, precision_rounding=currency.rounding):
            return 0.0
        return gap

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

    def _prepare_base_line_for_taxes_computation(self):
        """Exchange orders mix returns and sales; never flip quantities at order level."""
        self.ensure_one()
        if not self.order_id.avea_is_exchange:
            return super()._prepare_base_line_for_taxes_computation()

        commercial_partner = self.order_id.partner_id.commercial_partner_id
        fiscal_position = self.order_id.fiscal_position_id
        line = self.with_company(self.order_id.company_id)
        account = (
            line.product_id._get_product_accounts()["income"]
            or self.order_id.config_id.journal_id.default_account_id
        )
        if not account:
            raise UserError(
                _(
                    "Please define income account for this product: '%(product)s' (id:%(id)d).",
                    product=line.product_id.name,
                    id=line.product_id.id,
                )
            )
        if fiscal_position:
            account = fiscal_position.map_account(account)

        is_refund_line = line.qty * line.price_unit < 0
        lang = line.order_id.partner_id.lang or self.env.user.lang
        product_name = (
            line.with_context(lang=lang).full_product_name
            or line.product_id.with_context(lang=lang).display_name
        )
        if line.product_id.description_sale:
            product_name += "\n" + line.product_id.with_context(lang=lang).description_sale
        return {
            **self.env["account.tax"]._prepare_base_line_for_taxes_computation(
                line,
                partner_id=commercial_partner,
                currency_id=self.order_id.currency_id,
                rate=self.order_id.currency_rate,
                product_id=line.product_id,
                tax_ids=line.tax_ids_after_fiscal_position,
                price_unit=line.price_unit,
                quantity=line.qty,
                discount=line.discount,
                account_id=account,
                is_refund=is_refund_line,
                sign=-1,
            ),
            "uom_id": line.product_uom_id,
            "name": product_name,
        }

    @api.model
    def action_avea_open_sales_ledger(self):
        """Open the global Sales Ledger with the standard completed-sale domain."""
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "avea_till.action_avea_sales_ledger_window"
        )
        action["domain"] = self._avea_sales_ledger_domain()
        return action
