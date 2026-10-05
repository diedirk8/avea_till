from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero

from .stock_mixin import AVEA_RECEIVE_ORIGIN, AVEA_SUPPLIER_COST_PRECISION


class AveaStockReceiveLine(models.Model):
    _name = "avea.stock.receive.line"
    _description = "Receive Stock Line"
    _order = "id"

    receive_id = fields.Many2one(
        "avea.stock.receive",
        string="Receive Stock",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(related="receive_id.company_id")
    currency_id = fields.Many2one(related="receive_id.currency_id")
    partner_id = fields.Many2one(related="receive_id.partner_id")
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        domain="[('is_storable', '=', True), ('purchase_ok', '=', True)]",
    )
    quantity = fields.Float(
        string="Quantity",
        digits="Product Unit",
        required=True,
        default=1.0,
    )
    price_unit = fields.Float(
        string="EX-Tax Cost",
        digits=AVEA_SUPPLIER_COST_PRECISION,
        default=0.0,
        help="Original EX-tax unit cost from the supplier invoice, before discount.",
    )
    discount = fields.Float(
        string="Discount (%)",
        digits="Discount",
        default=0.0,
        help="Percentage discount on this line. Applied to the EX-tax cost before tax.",
    )
    price_unit_discounted = fields.Float(
        string="Discounted Cost",
        digits=AVEA_SUPPLIER_COST_PRECISION,
        compute="_compute_price_unit_discounted",
        help="EX-tax unit cost after the line discount.",
    )
    price_subtotal = fields.Monetary(
        string="Line Total",
        currency_field="currency_id",
        compute="_compute_line_totals",
    )
    price_tax = fields.Monetary(
        string="Tax",
        currency_field="currency_id",
        compute="_compute_line_totals",
    )
    price_total = fields.Monetary(
        string="Total",
        currency_field="currency_id",
        compute="_compute_line_totals",
    )
    avea_cost_differs = fields.Boolean(
        string="Cost differs",
        compute="_compute_avea_cost_differs",
    )
    avea_pricing_choice = fields.Selection(
        selection=[
            ("keep", "Keep Current Pricing"),
            ("cost_only", "Update Cost Only"),
            ("cost_and_pricing", "Update Cost & Pricing"),
        ],
        string="Pricing choice",
        copy=False,
    )
    avea_update_product_cost = fields.Boolean(
        string="Update product cost",
        default=False,
        help="Legacy flag; pricing updates are handled by the pricing popup.",
    )
    avea_pending_retail = fields.Float(
        string="Pending retail",
        digits="Product Price",
        copy=False,
    )
    avea_open_pricing_wizard = fields.Boolean(
        string="Open pricing wizard",
        store=False,
    )

    def _avea_product_cost(self):
        self.ensure_one()
        if not self.product_id:
            return 0.0
        return self.product_id.product_tmpl_id._avea_get_cost_ex_tax()

    @api.depends("product_id", "product_id.product_tmpl_id.avea_cost_ex_tax", "price_unit")
    def _compute_avea_cost_differs(self):
        mixin = self.env["avea.stock.mixin"]
        for line in self:
            if not line.product_id:
                line.avea_cost_differs = False
                continue
            line.avea_cost_differs = (
                mixin._avea_compare_supplier_cost(
                    line.price_unit,
                    line._avea_product_cost(),
                )
                != 0
            )

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for line in self:
            if not line.product_id:
                line.avea_pricing_choice = False
                line.avea_update_product_cost = False
                line.avea_open_pricing_wizard = False
                continue
            seller = line._avea_seller()
            line.price_unit = seller.price if seller else line._avea_product_cost()
            line.discount = seller.discount if seller else 0.0
            line.avea_pricing_choice = False
            line.avea_update_product_cost = False
            line.avea_open_pricing_wizard = False

    @api.onchange("price_unit")
    def _onchange_price_unit_cost_update(self):
        """Flag a pricing review when receive cost differs from the product cost."""
        for line in self:
            if not line.product_id:
                line.avea_pricing_choice = False
                line.avea_open_pricing_wizard = False
                continue
            current = line._avea_product_cost()
            new_cost = line.price_unit or 0.0
            mixin = self.env["avea.stock.mixin"]
            if mixin._avea_compare_supplier_cost(new_cost, current) == 0:
                line.avea_pricing_choice = False
                line.avea_open_pricing_wizard = False
                line.avea_update_product_cost = False
                continue
            # Reset previous decision whenever the typed cost changes.
            line.avea_pricing_choice = False
            line.avea_update_product_cost = False
            line.avea_open_pricing_wizard = True

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("avea_skip_pricing_wizard"):
            return res
        if "price_unit" in vals:
            mixin = self.env["avea.stock.mixin"]
            for line in self:
                if (
                    line.product_id
                    and mixin._avea_compare_supplier_cost(
                        line.price_unit,
                        line._avea_product_cost(),
                    )
                    != 0
                    and not line.avea_pricing_choice
                ):
                    # Persisted signal for the receive form JS to open the popup.
                    line.avea_pricing_choice = False
        return res

    def action_open_pricing_wizard(self):
        self.ensure_one()
        if not self.product_id:
            raise UserError(_("Choose a product first."))
        line = self._avea_ensure_persisted()
        if not line:
            raise UserError(
                _(
                    "Could not open pricing for this line yet. "
                    "Check the product and cost, then try again."
                )
            )
        wizard = (
            self.env["avea.stock.receive.pricing.wizard"]
            .with_context(default_line_id=line.id)
            .create({"line_id": line.id})
        )
        view = self.env.ref("avea_till.view_avea_stock_receive_pricing_wizard_form")
        return {
            "type": "ir.actions.act_window",
            "name": _("Pricing update"),
            "res_model": "avea.stock.receive.pricing.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "new",
            "context": {"default_line_id": line.id},
        }

    def _avea_ensure_persisted(self):
        """Return a saved receive line, matching unsaved inline rows when needed."""
        self.ensure_one()
        mixin = self.env["avea.stock.mixin"]
        if self.id:
            return self
        receive = self.receive_id
        if not receive or not receive.id or not self.product_id:
            return self.env["avea.stock.receive.line"]
        candidates = receive.line_ids.filtered(
            lambda line: line.product_id == self.product_id
        )
        if candidates:
            for line in reversed(candidates):
                if mixin._avea_compare_supplier_cost(
                    line.price_unit or 0.0,
                    self.price_unit or 0.0,
                ) == 0:
                    return line
            return candidates[-1]
        return self.create(
            {
                "receive_id": receive.id,
                "product_id": self.product_id.id,
                "quantity": self.quantity or 1.0,
                "price_unit": self.price_unit or 0.0,
                "discount": self.discount or 0.0,
            }
        )

    def _avea_seller(self):
        self.ensure_one()
        product = self.product_id
        partner = self.receive_id.partner_id
        if product and partner:
            return product._select_seller(
                partner_id=partner,
                quantity=self.quantity or 1.0,
            )
        return self.env["product.supplierinfo"]

    @api.depends("price_unit", "discount")
    def _compute_price_unit_discounted(self):
        for line in self:
            line.price_unit_discounted = line.price_unit * (1 - (line.discount or 0.0) / 100.0)

    def _avea_line_taxes(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        taxes = self.product_id.supplier_taxes_id.filtered(
            lambda tax: tax.type_tax_use == "purchase"
            and (not tax.company_id or tax.company_id == company)
        )
        if not taxes:
            taxes = company.account_purchase_tax_id
        partner = self.receive_id.effective_partner_id
        fiscal_position = partner.with_company(company).property_account_position_id
        if fiscal_position:
            taxes = fiscal_position.map_tax(taxes)
        return taxes

    @api.depends(
        "product_id",
        "quantity",
        "price_unit",
        "discount",
        "receive_id.partner_id",
        "receive_id.add_new_supplier",
        "currency_id",
    )
    def _compute_line_totals(self):
        AccountTax = self.env["account.tax"]
        for line in self:
            if not line.product_id or not line.currency_id:
                line.price_subtotal = 0.0
                line.price_tax = 0.0
                line.price_total = 0.0
                continue
            company = line.company_id or self.env.company
            taxes = line._avea_line_taxes()
            base_line = AccountTax._prepare_base_line_for_taxes_computation(
                line,
                tax_ids=taxes,
                quantity=line.quantity,
                partner_id=line.receive_id.effective_partner_id,
                currency_id=line.currency_id,
                price_unit=line.price_unit,
                discount=line.discount or 0.0,
                product_id=line.product_id,
            )
            AccountTax._add_tax_details_in_base_line(base_line, company)
            AccountTax._round_base_lines_tax_details([base_line], company)
            line.price_subtotal = base_line["tax_details"]["total_excluded_currency"]
            line.price_total = base_line["tax_details"]["total_included_currency"]
            line.price_tax = line.price_total - line.price_subtotal


class AveaStockReceive(models.Model):
    _name = "avea.stock.receive"
    _description = "Receive Stock"
    _inherit = ["avea.stock.mixin"]
    _order = "write_date desc, id desc"

    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        default=lambda self: self.env.user,
        index=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Supplier",
        domain="[('supplier_rank', '>', 0)]",
    )
    add_new_supplier = fields.Boolean(
        string="Add a new supplier",
    )
    new_supplier_name = fields.Char(
        string="Supplier name",
    )
    new_supplier_vat = fields.Char(
        string="VAT number",
    )
    effective_partner_id = fields.Many2one(
        "res.partner",
        compute="_compute_effective_partner_id",
    )
    invoice_number = fields.Char(
        string="Invoice number",
    )
    invoice_date = fields.Date(
        string="Invoice date",
        required=True,
        default=fields.Date.context_today,
    )
    received_date = fields.Date(
        string="Date received",
        required=True,
        default=fields.Date.context_today,
    )
    invoice_document = fields.Binary(
        string="Invoice document",
        attachment=False,
    )
    invoice_document_filename = fields.Char(
        string="Invoice filename",
    )
    line_ids = fields.One2many(
        "avea.stock.receive.line",
        "receive_id",
        string="Products",
    )
    charge_ids = fields.One2many(
        "avea.stock.receive.charge",
        "receive_id",
        string="Additional Charges",
    )
    amount_untaxed = fields.Monetary(
        string="Ex-tax total",
        currency_field="currency_id",
        compute="_compute_amounts",
    )
    amount_tax = fields.Monetary(
        string="Tax",
        currency_field="currency_id",
        compute="_compute_amounts",
    )
    amount_total = fields.Monetary(
        string="Total including tax",
        currency_field="currency_id",
        compute="_compute_amounts",
    )
    amount_charges_untaxed = fields.Monetary(
        string="Charges ex-tax",
        currency_field="currency_id",
        compute="_compute_amounts",
    )
    amount_charges_tax = fields.Monetary(
        string="Charges tax",
        currency_field="currency_id",
        compute="_compute_amounts",
    )
    amount_charges_total = fields.Monetary(
        string="Charges total",
        currency_field="currency_id",
        compute="_compute_amounts",
    )
    charge_count = fields.Integer(
        string="Charges",
        compute="_compute_amounts",
    )
    charge_line_count = fields.Integer(
        string="Charge lines",
        compute="_compute_amounts",
    )
    invoice_total = fields.Monetary(
        string="Invoice total",
        currency_field="currency_id",
        help="Optional. Type the total from the supplier invoice to check your capture.",
    )
    totals_mismatch = fields.Boolean(
        compute="_compute_totals_mismatch",
    )
    invoice_difference = fields.Monetary(
        string="Difference",
        currency_field="currency_id",
        compute="_compute_totals_mismatch",
    )
    mark_as_paid = fields.Boolean(
        string="Mark as Paid",
    )
    use_supplier_credit = fields.Boolean(
        string="Apply supplier credit",
        help="Use open vendor credit notes from returns against this bill before paying cash or bank.",
    )
    supplier_credit_available = fields.Monetary(
        string="Supplier credit available",
        currency_field="currency_id",
        compute="_compute_supplier_credit_available",
    )
    has_supplier_credit = fields.Boolean(
        compute="_compute_supplier_credit_available",
    )
    supplier_credit_applied = fields.Monetary(
        string="Supplier credit applied",
        currency_field="currency_id",
        readonly=True,
        copy=False,
    )
    purchase_order_id = fields.Many2one(
        "purchase.order",
        string="Purchase order",
        readonly=True,
        copy=False,
    )
    picking_id = fields.Many2one(
        "stock.picking",
        string="Receipt",
        readonly=True,
        copy=False,
    )
    can_return_stock = fields.Boolean(
        compute="_compute_can_return_stock",
    )
    bill_residual = fields.Monetary(
        related="bill_id.amount_residual",
        currency_field="currency_id",
    )
    paid_from_journal_id = fields.Many2one(
        "account.journal",
        string="Paid From",
        domain="[('id', 'in', available_journal_ids)]",
    )
    available_journal_ids = fields.Many2many(
        "account.journal",
        compute="_compute_available_journal_ids",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("done", "Done"),
        ],
        default="draft",
        required=True,
    )
    bill_id = fields.Many2one(
        "account.move",
        string="Vendor Bill",
        readonly=True,
    )
    product_count = fields.Integer(
        string="Products",
        compute="_compute_confirmation_stats",
    )
    quantity_total = fields.Float(
        string="Total quantity",
        digits="Product Unit",
        compute="_compute_confirmation_stats",
    )
    payment_status = fields.Char(
        string="Payment status",
        compute="_compute_payment_status",
    )
    show_confirmation = fields.Boolean(
        compute="_compute_show_confirmation",
    )

    @api.depends("state", "bill_id")
    def _compute_show_confirmation(self):
        for receive in self:
            receive.show_confirmation = (
                receive.state == "done" and bool(receive.bill_id)
            )

    @api.depends("state", "partner_id", "invoice_number")
    def _compute_display_name(self):
        for receive in self:
            if receive.state == "done":
                if receive.partner_id and receive.invoice_number:
                    receive.display_name = _(
                        "Stock Received — %(supplier)s %(invoice)s",
                        supplier=receive.partner_id.display_name,
                        invoice=receive.invoice_number,
                    )
                else:
                    receive.display_name = _("Stock Received")
            else:
                receive.display_name = _("Receive Stock")

    @api.depends("partner_id", "add_new_supplier")
    def _compute_effective_partner_id(self):
        for receive in self:
            receive.effective_partner_id = (
                False if receive.add_new_supplier else receive.partner_id
            )

    @api.depends("company_id")
    def _compute_available_journal_ids(self):
        for receive in self:
            company = receive.company_id
            receive.available_journal_ids = (
                company._avea_expense_journals() if company else False
            )

    @api.depends(
        "line_ids.price_subtotal",
        "line_ids.price_tax",
        "line_ids.price_total",
        "charge_ids.price_subtotal",
        "charge_ids.price_tax",
        "charge_ids.price_total",
        "charge_ids.amount",
        "charge_ids.name",
        "charge_ids",
    )
    def _compute_amounts(self):
        for receive in self:
            product_untaxed = sum(receive.line_ids.mapped("price_subtotal"))
            product_tax = sum(receive.line_ids.mapped("price_tax"))
            product_total = sum(receive.line_ids.mapped("price_total"))
            charges = receive.charge_ids.filtered(lambda charge: charge.amount)
            charge_untaxed = sum(charges.mapped("price_subtotal"))
            charge_tax = sum(charges.mapped("price_tax"))
            charge_total = sum(charges.mapped("price_total"))
            receive.amount_charges_untaxed = charge_untaxed
            receive.amount_charges_tax = charge_tax
            receive.amount_charges_total = charge_total
            receive.charge_count = len(charges)
            receive.charge_line_count = len(receive.charge_ids)
            receive.amount_untaxed = product_untaxed + charge_untaxed
            receive.amount_tax = product_tax + charge_tax
            receive.amount_total = product_total + charge_total

    @api.depends("line_ids.product_id", "line_ids.quantity")
    def _compute_confirmation_stats(self):
        for receive in self:
            lines = receive.line_ids.filtered("product_id")
            receive.product_count = len(lines)
            receive.quantity_total = sum(lines.mapped("quantity"))

    @api.depends(
        "mark_as_paid",
        "paid_from_journal_id",
        "supplier_credit_applied",
        "bill_id",
        "bill_id.amount_residual",
        "bill_id.payment_state",
    )
    def _compute_payment_status(self):
        for receive in self:
            parts = []
            if receive.supplier_credit_applied:
                parts.append(
                    _("Credit applied %(amount)s", amount=receive.supplier_credit_applied)
                )
            bill = receive.bill_id
            if bill and not bill.currency_id.is_zero(bill.amount_residual):
                parts.append(_("Balance due %(amount)s", amount=bill.amount_residual))
            elif bill and receive.supplier_credit_applied and not receive.mark_as_paid:
                parts.append(_("Paid with supplier credit"))
            if receive.mark_as_paid:
                journal = receive.paid_from_journal_id
                parts.append(
                    _("Paid from %s") % journal.display_name if journal else _("Paid")
                )
            if not parts:
                receive.payment_status = _("Unpaid")
            else:
                receive.payment_status = " · ".join(parts)

    @api.depends("amount_total", "invoice_total", "currency_id")
    def _compute_totals_mismatch(self):
        for receive in self:
            currency = receive.currency_id or receive.env.company.currency_id
            if not receive.invoice_total:
                receive.totals_mismatch = False
                receive.invoice_difference = 0.0
                continue
            difference = currency.round(receive.amount_total - receive.invoice_total)
            receive.invoice_difference = difference
            receive.totals_mismatch = not currency.is_zero(difference)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if "user_id" in fields_list and not values.get("user_id"):
            values["user_id"] = self.env.user.id
        if "paid_from_journal_id" in fields_list and not values.get(
            "paid_from_journal_id"
        ):
            journal = self._avea_default_paid_from_journal(self.env.company)
            if journal:
                values["paid_from_journal_id"] = journal.id
        return values

    @api.model
    def _avea_draft_domain(self):
        return [
            ("state", "=", "draft"),
            ("user_id", "=", self.env.user.id),
            ("company_id", "=", self.env.company.id),
        ]

    @api.model
    def _avea_find_draft_receive(self):
        """Resume the user's most useful in-progress receive."""
        Receive = self.sudo()
        domain = self._avea_draft_domain()
        with_lines = Receive.search(
            domain + [("line_ids", "!=", False)],
            order="write_date desc, id desc",
            limit=1,
        )
        if with_lines:
            return with_lines.with_env(self.env)
        with_header = Receive.search(
            domain
            + [
                "|",
                ("partner_id", "!=", False),
                ("invoice_number", "!=", False),
            ],
            order="write_date desc, id desc",
            limit=1,
        )
        if with_header:
            return with_header.with_env(self.env)
        draft = Receive.search(domain, order="write_date desc, id desc", limit=1)
        return draft.with_env(self.env) if draft else self.env["avea.stock.receive"]

    @api.model
    def _avea_create_draft_receive(self):
        return self.create(
            {
                "user_id": self.env.user.id,
                "company_id": self.env.company.id,
            }
        )

    def _avea_repair_false_done(self):
        broken = self.filtered(lambda receive: receive.state == "done" and not receive.bill_id)
        if broken:
            broken.write({"state": "draft"})
        return self - broken

    @api.model
    def _avea_default_paid_from_journal(self, company):
        journals = company._avea_expense_journals() if company else self.env["account.journal"]
        return journals.filtered(lambda journal: journal.type == "cash")[:1] or journals[:1]

    @api.onchange("company_id")
    def _onchange_company_id_paid_from(self):
        allowed = self.available_journal_ids
        if self.paid_from_journal_id and self.paid_from_journal_id not in allowed:
            self.paid_from_journal_id = self._avea_default_paid_from_journal(self.company_id)

    @api.onchange("add_new_supplier")
    def _onchange_add_new_supplier(self):
        if self.add_new_supplier:
            self.partner_id = False

    def _avea_receive_action(self, record, name=None, view_xmlid=None):
        view_id = self.env.ref(
            view_xmlid or "avea_till.view_avea_stock_receive_form"
        ).id
        return {
            "type": "ir.actions.act_window",
            "name": name or _("Receive Stock"),
            "res_model": self._name,
            "view_mode": "form",
            "views": [(view_id, "form")],
            "view_id": view_id,
            "res_id": record.id,
            "target": "main",
            "context": {"clear_breadcrumbs": True},
        }

    @api.model
    def action_open_receive(self):
        receive = self._avea_find_draft_receive()
        if not receive:
            receive = self._avea_create_draft_receive()
        else:
            receive._avea_repair_false_done()
        return receive._avea_receive_action(receive)

    @api.model
    def action_open_receive_history(self):
        view_id = self.env.ref("avea_till.view_avea_stock_receive_history_list").id
        return {
            "type": "ir.actions.act_window",
            "name": _("Receive history"),
            "res_model": self._name,
            "view_mode": "list,form",
            "views": [(view_id, "list"), (False, "form")],
            "domain": [("state", "=", "done")],
            "target": "main",
            "context": {"clear_breadcrumbs": True, "create": False},
        }

    def _avea_get_receipt_picking(self):
        self.ensure_one()
        if self.picking_id:
            return self.picking_id
        order = self.purchase_order_id
        if not order and self.bill_id:
            order = self.bill_id.invoice_line_ids.purchase_line_id.order_id[:1]
        if order:
            picking = order.picking_ids.filtered(
                lambda picking: picking.picking_type_code == "incoming"
                and picking.state == "done"
            )[:1]
            if picking:
                return picking
        if self.invoice_number and self.partner_id:
            return self.env["stock.picking"]._avea_find_receipt_for_return(
                self.invoice_number,
                partner=self.partner_id,
                company=self.company_id,
            )
        return self.env["stock.picking"]

    @api.depends("state", "picking_id", "purchase_order_id", "bill_id", "invoice_number")
    def _compute_can_return_stock(self):
        Return = self.env["avea.stock.return"]
        for receive in self:
            receive.can_return_stock = False
            if receive.state != "done":
                continue
            picking = receive._avea_get_receipt_picking()
            if not picking or picking.state != "done":
                continue
            for move in picking.move_ids.filtered(lambda move: move.state == "done"):
                available = Return._avea_qty_available_to_return(move)
                if not float_is_zero(available, precision_rounding=move.product_uom.rounding):
                    receive.can_return_stock = True
                    break

    @api.depends("partner_id", "effective_partner_id", "company_id")
    def _compute_supplier_credit_available(self):
        mixin = self.env["avea.stock.mixin"]
        for receive in self:
            partner = receive.effective_partner_id or receive.partner_id
            available = (
                mixin._avea_supplier_credit_available(partner, receive.company_id)
                if partner
                else 0.0
            )
            receive.supplier_credit_available = available
            receive.has_supplier_credit = available > 0.0

    def action_return_this_stock(self):
        self.ensure_one()
        picking = self._avea_get_receipt_picking()
        if not picking:
            raise UserError(
                _("No stock receipt was found for this receive. Open the receipt from Inventory.")
            )
        return self.env["avea.stock.return"].action_open_return_for_picking(picking)

    def action_open_return(self):
        return self.env["avea.stock.return"].action_open_return()

    def action_new_stock_item(self):
        """Open New Stock Item and return here with the product on the receive list."""
        self.ensure_one()
        if self.state != "draft" or self.show_confirmation:
            raise UserError(_("Start a new Receive Stock draft before adding a product."))
        action = self.env["product.template"].action_avea_new_stock_item()
        context = dict(action.get("context") or {})
        context.update(
            {
                "avea_return_receive_id": self.id,
                "avea_stock_workspace": True,
                "avea_quick_product_add": True,
            }
        )
        if self.partner_id:
            context["default_avea_supplier_id"] = self.partner_id.id
        action["context"] = context
        return action

    def action_done(self):
        self._avea_archive_completed()
        return self.env["avea.stock.receive"].action_open_receive()

    def action_receive_another(self):
        self._avea_archive_completed()
        receive = self.env["avea.stock.receive"]._avea_create_draft_receive()
        return receive._avea_receive_action(receive)

    def action_add_charge_line(self):
        """Add a blank charge row from the compact Totals header."""
        self.ensure_one()
        if self.state != "draft":
            return False
        self.charge_ids = [
            Command.create(
                {
                    "name": "",
                    "amount": 0.0,
                }
            )
        ]
        return False

    def action_cancel_receive(self):
        self.ensure_one()
        self._avea_repair_false_done()
        if self.state == "draft":
            self.unlink()
        return self.env["avea.stock.receive"].action_open_receive()

    def _avea_archive_completed(self):
        self.filtered(lambda receive: receive.show_confirmation).unlink()

    def action_view_bill(self):
        self.ensure_one()
        if not self.bill_id:
            raise UserError(_("There is no vendor bill to open."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Vendor Bill"),
            "res_model": "account.move",
            "res_id": self.bill_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
        }

    def action_receive_stock(self):
        self.ensure_one()
        self._avea_repair_false_done()
        if self.show_confirmation:
            return self._avea_confirmation_action()
        partner = self._avea_ensure_supplier()
        self._avea_check_receive(partner)
        mixin = self.env["avea.stock.mixin"]
        pending = self.line_ids.filtered(
            lambda line: line.product_id
            and mixin._avea_compare_supplier_cost(
                line.price_unit,
                line._avea_product_cost(),
            )
            != 0
            and not line.avea_pricing_choice
        )
        if pending:
            return pending[0].action_open_pricing_wizard()
        order = self._avea_create_purchase_order(partner)
        self._avea_confirm_purchase_order(order)
        picking = self._avea_incoming_picking(order)
        self._avea_complete_picking(picking, date_done=self.received_date)
        bill = self._avea_create_vendor_bill(order)
        if self.invoice_document:
            self._avea_attach_invoice(bill)
        credit_applied = 0.0
        if self.use_supplier_credit:
            credit_applied = mixin._avea_apply_supplier_credits_to_bill(
                bill, partner, self.company_id
            )
        if self.mark_as_paid:
            self._avea_pay_vendor_bill(
                bill,
                self._avea_payment_journal(),
                partner,
                self.company_id,
                self.invoice_date,
                self.invoice_number,
            )
        return self._avea_success(
            partner,
            order,
            bill,
            picking=picking,
            credit_applied=credit_applied,
        )

    def _avea_apply_product_cost_updates(self):
        """Pricing updates are applied in the pricing popup; keep for compatibility."""
        return

    def _avea_check_receive(self, partner):
        self.ensure_one()
        if not partner:
            raise ValidationError(_("Choose a supplier, or add a new one."))
        if not self.invoice_number or not self.invoice_number.strip():
            raise ValidationError(_("Enter the supplier invoice number."))
        lines = self.line_ids.filtered("product_id")
        if not lines:
            raise ValidationError(_("Add at least one product to receive."))
        for line in lines:
            if line.quantity <= 0:
                raise ValidationError(
                    _("Quantity for %(product)s must be greater than zero.",
                      product=line.product_id.display_name)
                )
            if line.discount < 0 or line.discount > 100:
                raise ValidationError(
                    _("Discount for %(product)s must be between 0 and 100%.",
                      product=line.product_id.display_name)
                )
            if not line.product_id.is_storable:
                raise ValidationError(
                    _("%(product)s is not a stock product.",
                      product=line.product_id.display_name)
                )
        if self.mark_as_paid:
            self._avea_payment_journal()

    def _avea_ensure_supplier(self):
        self.ensure_one()
        if not self.add_new_supplier:
            return self.partner_id
        name = (self.new_supplier_name or "").strip()
        if not name:
            raise ValidationError(_("Enter the new supplier's name."))
        vat = (self.new_supplier_vat or "").strip() or False
        vals = {
            "name": name,
            "vat": vat,
            "supplier_rank": 1,
            "company_id": self.company_id.id,
            "is_company": True,
        }
        try:
            partner = self.env["res.partner"].sudo().create(vals)
        except ValidationError:
            if not vat:
                raise
            vals.pop("vat")
            partner = self.env["res.partner"].sudo().create(vals)
            partner.message_post(
                body=_("VAT number %(vat)s was not saved because it is not valid.", vat=vat)
            )
        self.partner_id = partner
        return partner

    def _avea_create_purchase_order(self, partner):
        self.ensure_one()
        warehouse = self.env["stock.warehouse"].sudo().search(
            [("company_id", "=", self.company_id.id)],
            limit=1,
        )
        if not warehouse:
            raise UserError(
                _("No warehouse is configured. Ask your administrator to set one up.")
            )
        order_lines = []
        for line in self.line_ids.filtered("product_id"):
            taxes = line._avea_line_taxes()
            order_lines.append(
                Command.create(
                    {
                        "product_id": line.product_id.id,
                        "name": line.product_id.display_name,
                        "product_qty": line.quantity,
                        "product_uom_id": line.product_id.uom_id.id,
                        "price_unit": line.price_unit,
                        "discount": line.discount or 0.0,
                        "technical_price_unit": 0.0,
                        "tax_ids": [Command.set(taxes.ids)],
                        "date_planned": self._avea_datetime_at_noon(self.received_date),
                    }
                )
            )
        order_vals = {
            "partner_id": partner.id,
            "partner_ref": self.invoice_number.strip(),
            "date_order": self._avea_datetime_at_noon(self.invoice_date),
            "date_planned": self._avea_datetime_at_noon(self.received_date),
            "company_id": self.company_id.id,
            "currency_id": self.currency_id.id,
            "origin": AVEA_RECEIVE_ORIGIN,
            "picking_type_id": warehouse.in_type_id.id,
            "order_line": order_lines,
        }
        order = (
            self.env["purchase.order"]
            .sudo()
            .with_company(self.company_id)
            .with_context(mail_create_nolog=True)
            .create(order_vals)
        )
        self._avea_force_line_prices(order)
        return order

    def _avea_force_line_prices(self, order):
        """Keep the captured EX-VAT costs and discounts; do not let seller pricelists overwrite them."""
        sources = self.line_ids.filtered("product_id")
        po_lines = order.order_line.filtered(lambda line: not line.display_type)
        for po_line, source in zip(po_lines, sources):
            if po_line.product_id != source.product_id:
                continue
            po_line.write(
                {
                    "price_unit": source.price_unit,
                    "discount": source.discount or 0.0,
                    "technical_price_unit": 0.0,
                }
            )

    def _avea_confirm_purchase_order(self, order):
        order.sudo().button_confirm()
        if order.state == "to approve":
            order.sudo().button_approve()
        self._avea_force_line_prices(order)
        if order.state not in ("purchase", "done"):
            raise UserError(
                _("The supplier order could not be confirmed. Ask your administrator to check Purchase.")
            )
        return order

    def _avea_create_vendor_bill(self, order):
        self.ensure_one()
        existing = order.invoice_ids
        order.sudo().with_context(default_move_type="in_invoice").action_create_invoice()
        bill = (order.invoice_ids - existing).filtered(lambda move: move.state == "draft")[:1]
        if not bill:
            bill = order.invoice_ids.filtered(lambda move: move.state == "draft")[:1]
        if not bill:
            raise UserError(
                _("The supplier bill could not be created. Receive the stock first, then try again.")
            )
        bill.sudo().write(
            {
                "invoice_date": self.invoice_date,
                "date": self.invoice_date,
                "invoice_date_due": self.invoice_date,
                "ref": self.invoice_number.strip(),
            }
        )
        self._avea_add_charge_lines_to_bill(bill)
        bill.sudo().action_post()
        if bill.state != "posted":
            raise UserError(_("The supplier bill could not be posted."))
        return bill

    def _avea_additional_charge_account(self):
        """Expense account for receive charges (not stock valuation)."""
        self.ensure_one()
        company = self.company_id
        Account = self.env["account.account"].sudo().with_company(company)
        account = Account.search([("code", "=", "610060")], limit=1)
        if not account:
            account = Account.search(
                [
                    ("account_type", "=", "expense"),
                    ("name", "ilike", "Shipping"),
                ],
                limit=1,
            )
        if not account:
            account = Account.search(
                [("account_type", "in", ("expense", "expense_direct_cost"))],
                limit=1,
            )
        if not account:
            raise UserError(
                _(
                    "No expense account is available for additional charges. "
                    "Ask an administrator to configure a Shipping or expense account."
                )
            )
        return account

    def _avea_add_charge_lines_to_bill(self, bill):
        """Append expense lines for additional charges before the bill is posted.

        Charges are never written into inventory valuation. They remain ordinary
        vendor-bill expense lines (``avea_additional_charge``) so a later Landed
        Costs feature can optionally select them without changing this path.
        """
        self.ensure_one()
        charges = self.charge_ids.filtered(
            lambda charge: charge.name and charge.amount and charge.charge_kind == "expense"
        )
        if not charges:
            return bill
        account = self._avea_additional_charge_account()
        commands = []
        for charge in charges:
            taxes = charge._avea_charge_taxes()
            commands.append(
                Command.create(
                    {
                        "name": charge.name.strip(),
                        "quantity": 1.0,
                        "price_unit": charge.amount,
                        "account_id": account.id,
                        "tax_ids": [Command.set(taxes.ids)],
                        "display_type": "product",
                        "avea_additional_charge": True,
                    }
                )
            )
        bill.sudo().write({"invoice_line_ids": commands})
        return bill

    def _avea_attach_invoice(self, bill):
        self.ensure_one()
        filename = self.invoice_document_filename or _("Supplier Invoice")
        self.env["ir.attachment"].sudo().create(
            {
                "name": filename,
                "datas": self.invoice_document,
                "res_model": "account.move",
                "res_id": bill.id,
                "type": "binary",
            }
        )

    def _avea_payment_journal(self):
        self.ensure_one()
        journal = self.paid_from_journal_id
        allowed = self.company_id._avea_expense_journals()
        if not allowed:
            raise UserError(
                _(
                    "No company money accounts are available. Ask an administrator "
                    "to select them under Settings → Avea Dashboard."
                )
            )
        if not journal or journal not in allowed:
            raise UserError(
                _(
                    "Choose a company cash or bank account to pay from. Ask an "
                    "administrator to update Settings → Avea Dashboard if the "
                    "account you need is missing."
                )
            )
        return journal

    def _avea_success(self, partner, order, bill, picking=False, credit_applied=0.0):
        self.write(
            {
                "state": "done",
                "bill_id": bill.id,
                "partner_id": partner.id,
                "add_new_supplier": False,
                "purchase_order_id": order.id,
                "picking_id": picking.id if picking else False,
                "supplier_credit_applied": credit_applied,
            }
        )
        return self._avea_confirmation_action()

    def _avea_confirmation_action(self):
        self.ensure_one()
        return self._avea_receive_action(
            self,
            name=_("Stock Received"),
        )
