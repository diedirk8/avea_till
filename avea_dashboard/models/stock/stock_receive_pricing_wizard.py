# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero


class AveaStockReceivePricingWizard(models.TransientModel):
    """Compact popup when receive cost differs from the product cost."""

    _name = "avea.stock.receive.pricing.wizard"
    _description = "Receive Stock Pricing Update"

    line_id = fields.Many2one(
        "avea.stock.receive.line",
        string="Receive line",
        required=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        related="line_id.product_id",
        readonly=True,
    )
    product_tmpl_id = fields.Many2one(
        "product.template",
        related="product_id.product_tmpl_id",
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="line_id.currency_id",
        readonly=True,
    )
    receive_cost = fields.Float(
        string="Receive cost EX Tax",
        digits="Product Price",
        readonly=True,
    )

    # Current product pricing (readonly snapshot)
    current_cost = fields.Float(string="Current cost", digits="Product Price", readonly=True)
    current_retail = fields.Float(
        string="Current retail INC Tax", digits="Product Price", readonly=True
    )
    current_markup = fields.Float(string="Current markup %", digits=(16, 2), readonly=True)
    current_margin = fields.Float(string="Current margin %", digits=(16, 2), readonly=True)

    # Editable "new" pricing (recalculates with product sales tax)
    new_cost = fields.Float(string="Cost EX Tax", digits="Product Price")
    new_retail = fields.Float(string="Retail Price INC Tax", digits="Product Price")
    new_markup = fields.Float(string="Markup %", digits=(16, 2))
    new_margin = fields.Float(string="Margin %", digits=(16, 2))

    preview_note = fields.Char(compute="_compute_preview_note")

    @api.model
    def _avea_pricing_from_cost_retail(self, template, cost, retail_inc):
        cost = cost or 0.0
        retail_inc = retail_inc or 0.0
        retail_ex = template._avea_retail_ex_vat_from_inc(retail_inc)
        currency = template.currency_id or template.env.company.currency_id
        prec = currency.decimal_places
        if float_is_zero(cost, precision_digits=prec):
            markup = 0.0
        else:
            markup = (retail_ex - cost) / cost * 100.0
        if float_is_zero(retail_ex, precision_digits=prec):
            margin = 0.0
        else:
            margin = (retail_ex - cost) / retail_ex * 100.0
        return retail_ex, markup, margin

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        line = self.env["avea.stock.receive.line"].browse(
            self.env.context.get("default_line_id") or res.get("line_id")
        )
        if not line or not line.product_id:
            return res
        template = line.product_id.product_tmpl_id
        cost, retail_inc, _ex, markup, margin = template._avea_pricing_tuple()
        receive_cost = line.price_unit or 0.0
        # Default "new" view: receive cost with current retail (shows margin impact)
        _ex2, new_markup, new_margin = self._avea_pricing_from_cost_retail(
            template, receive_cost, retail_inc
        )
        res.update(
            {
                "line_id": line.id,
                "receive_cost": receive_cost,
                "current_cost": cost,
                "current_retail": retail_inc,
                "current_markup": markup,
                "current_margin": margin,
                "new_cost": receive_cost,
                "new_retail": retail_inc,
                "new_markup": new_markup,
                "new_margin": new_margin,
            }
        )
        return res

    @api.depends("new_cost", "new_retail", "new_markup", "new_margin", "current_margin")
    def _compute_preview_note(self):
        for wizard in self:
            delta = (wizard.new_margin or 0.0) - (wizard.current_margin or 0.0)
            if float_compare(delta, 0.0, precision_digits=2) > 0:
                wizard.preview_note = _("Margin would rise by %.1f points.") % delta
            elif float_compare(delta, 0.0, precision_digits=2) < 0:
                wizard.preview_note = _("Margin would fall by %.1f points.") % abs(delta)
            else:
                wizard.preview_note = _("Margin would stay the same.")

    def _avea_recompute_from_cost_retail(self):
        self.ensure_one()
        template = self.product_tmpl_id
        if not template:
            return
        _ex, markup, margin = self._avea_pricing_from_cost_retail(
            template, self.new_cost, self.new_retail
        )
        self.new_markup = markup
        self.new_margin = margin

    @api.onchange("new_cost")
    def _onchange_new_cost(self):
        if self.env.context.get("avea_pricing_guard"):
            return
        self = self.with_context(avea_pricing_guard=True)
        # Keep retail, show new markup/margin at the new cost.
        self._avea_recompute_from_cost_retail()

    @api.onchange("new_retail")
    def _onchange_new_retail(self):
        if self.env.context.get("avea_pricing_guard"):
            return
        self = self.with_context(avea_pricing_guard=True)
        self._avea_recompute_from_cost_retail()

    @api.onchange("new_markup")
    def _onchange_new_markup(self):
        if self.env.context.get("avea_pricing_guard"):
            return
        self = self.with_context(avea_pricing_guard=True)
        template = self.product_tmpl_id
        if not template:
            return
        cost = self.new_cost or 0.0
        retail_ex = cost * (1.0 + (self.new_markup or 0.0) / 100.0)
        self.new_retail = template._avea_retail_inc_vat_from_ex(retail_ex)
        self._avea_recompute_from_cost_retail()

    @api.onchange("new_margin")
    def _onchange_new_margin(self):
        if self.env.context.get("avea_pricing_guard"):
            return
        margin = self.new_margin or 0.0
        if margin >= 100.0:
            return {
                "warning": {
                    "title": _("Invalid margin"),
                    "message": _("Margin must be less than 100%."),
                }
            }
        self = self.with_context(avea_pricing_guard=True)
        template = self.product_tmpl_id
        if not template:
            return
        cost = self.new_cost or 0.0
        retail_ex = cost / (1.0 - margin / 100.0) if margin < 100.0 else 0.0
        self.new_retail = template._avea_retail_inc_vat_from_ex(retail_ex)
        self._avea_recompute_from_cost_retail()

    def action_keep_current_pricing(self):
        self.ensure_one()
        self.line_id.with_context(avea_skip_pricing_wizard=True).write(
            {
                "avea_pricing_choice": "keep",
                "avea_update_product_cost": False,
                "avea_pending_retail": 0.0,
            }
        )
        return {"type": "ir.actions.act_window_close"}

    def action_update_cost_only(self):
        self.ensure_one()
        template = self.product_tmpl_id
        if not template:
            raise UserError(_("No product on this line."))
        template.standard_price = self.new_cost or self.receive_cost or 0.0
        self.line_id.with_context(avea_skip_pricing_wizard=True).write(
            {
                "avea_pricing_choice": "cost_only",
                "avea_update_product_cost": False,
                "avea_pending_retail": 0.0,
                "price_unit": self.new_cost or self.receive_cost or 0.0,
            }
        )
        return {"type": "ir.actions.act_window_close"}

    def action_update_cost_and_pricing(self):
        self.ensure_one()
        template = self.product_tmpl_id
        if not template:
            raise UserError(_("No product on this line."))
        if (self.new_margin or 0.0) >= 100.0:
            raise UserError(_("Margin must be less than 100%."))
        template.write(
            {
                "standard_price": self.new_cost or 0.0,
                "list_price": self.new_retail or 0.0,
            }
        )
        self.line_id.with_context(avea_skip_pricing_wizard=True).write(
            {
                "avea_pricing_choice": "cost_and_pricing",
                "avea_update_product_cost": False,
                "avea_pending_retail": self.new_retail or 0.0,
                "price_unit": self.new_cost or 0.0,
            }
        )
        return {"type": "ir.actions.act_window_close"}
