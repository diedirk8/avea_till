import logging

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero

from .stock_mixin import AVEA_RECEIVE_ORIGIN, AVEA_SUPPLIER_COST_PRECISION

_logger = logging.getLogger(__name__)


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
        help="Usual EX-tax unit cost from the supplier invoice, before any line discount. "
        "This is the figure that can update the product's catalogue cost if you change it. "
        "Use 0 for a free product; the usual cost and selling price stay the same.",
    )
    discount = fields.Float(
        string="Discount (%)",
        digits="Discount",
        default=0.0,
        help="This invoice only. Applied to the EX-tax cost before tax. "
        "It does not change the product's usual catalogue cost.",
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
    avea_previous_cost = fields.Float(
        string="Catalogue cost before receive",
        digits=AVEA_SUPPLIER_COST_PRECISION,
        copy=False,
    )
    avea_previous_retail = fields.Float(
        string="Catalogue retail before receive",
        digits="Product Price",
        copy=False,
    )
    avea_pricing_snapshot = fields.Boolean(
        string="Pricing snapshot captured",
        copy=False,
    )
    avea_open_pricing_wizard = fields.Boolean(
        string="Open pricing wizard",
        store=False,
    )

    def _avea_snapshot_catalog_pricing(self):
        """Remember catalogue cost/retail before a receive changes them."""
        for line in self:
            if line.avea_pricing_snapshot or not line.product_id:
                continue
            template = line.product_id.product_tmpl_id
            cost, retail_inc, _ex, _markup, _margin = template._avea_pricing_tuple()
            line.with_context(avea_skip_pricing_wizard=True).write(
                {
                    "avea_previous_cost": cost,
                    "avea_previous_retail": retail_inc,
                    "avea_pricing_snapshot": True,
                }
            )

    def _avea_product_cost(self):
        self.ensure_one()
        if not self.product_id:
            return 0.0
        return self.product_id.product_tmpl_id._avea_get_cost_ex_tax()

    def _avea_typed_cost_matches_catalogue(self):
        """True when the typed EX-tax unit cost is within 1c of catalogue cost."""
        self.ensure_one()
        return self.env["avea.stock.mixin"]._avea_amounts_within_cent(
            self.price_unit or 0.0,
            self._avea_product_cost(),
        )

    def _avea_discounted_unit_cost(self):
        self.ensure_one()
        return (self.price_unit or 0.0) * (1.0 - (self.discount or 0.0) / 100.0)

    def _avea_is_free_line(self):
        self.ensure_one()
        return (
            self.env["avea.stock.mixin"]._avea_compare_supplier_cost(
                self._avea_discounted_unit_cost(),
                0.0,
            )
            == 0
        )

    def _avea_keep_pricing_for_free_lines(self):
        """Free / FOC lines must not rewrite catalogue cost or retail."""
        for line in self:
            if not line.product_id or not line._avea_is_free_line():
                continue
            if line.avea_pricing_choice:
                continue
            vals = {
                "avea_pricing_choice": "keep",
                "avea_update_product_cost": False,
            }
            if line._origin:
                line.with_context(avea_skip_pricing_wizard=True).write(vals)
            else:
                line.update(vals)

    @api.depends("product_id", "product_id.product_tmpl_id.avea_cost_ex_tax", "price_unit")
    def _compute_avea_cost_differs(self):
        for line in self:
            if not line.product_id:
                line.avea_cost_differs = False
                continue
            line.avea_cost_differs = not line._avea_typed_cost_matches_catalogue()

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

    @api.onchange("price_unit", "discount")
    def _onchange_price_unit_cost_update(self):
        """Flag a pricing review when the typed unit cost differs from catalogue.

        A line discount is this bill only and must not open the cost wizard.
        """
        mixin = self.env["avea.stock.mixin"]
        for line in self:
            if not line.product_id:
                line.avea_pricing_choice = False
                line.avea_open_pricing_wizard = False
                continue
            if line._avea_is_free_line():
                line.avea_pricing_choice = "keep"
                line.avea_open_pricing_wizard = False
                line.avea_update_product_cost = False
                continue
            current = line._avea_product_cost()
            new_cost = line.price_unit or 0.0
            if mixin._avea_amounts_within_cent(new_cost, current):
                line.avea_open_pricing_wizard = False
                line.avea_update_product_cost = False
                if line.avea_pricing_choice == "cost_only":
                    line.avea_pricing_choice = "keep"
                continue
            origin = line._origin
            typed_cost_changed = True
            if origin:
                typed_cost_changed = not mixin._avea_amounts_within_cent(
                    origin.price_unit or 0.0,
                    new_cost,
                )
            if not typed_cost_changed:
                line.avea_open_pricing_wizard = False
                continue
            # Reset previous decision only when the typed unit cost changes.
            line.avea_pricing_choice = False
            line.avea_update_product_cost = False
            line.avea_open_pricing_wizard = True

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("avea_skip_pricing_wizard"):
            return res
        if "price_unit" not in vals and "discount" not in vals:
            return res
        for line in self:
            if not line.product_id:
                continue
            if line._avea_is_free_line():
                if not line.avea_pricing_choice:
                    line.avea_pricing_choice = "keep"
                continue
            if "price_unit" not in vals:
                continue
            if (
                not line._avea_typed_cost_matches_catalogue()
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
    _order = "received_date desc, id desc"

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
        domain="['|', ('supplier_rank', '>', 0), ('avea_credit_balance', '>', 0)]",
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
    payment_date = fields.Date(
        string="Payment date",
        default=fields.Date.context_today,
        help="Date the cash, bank, or store-credit payment is recorded.",
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
    use_store_credit = fields.Boolean(
        string="Pay with store credit",
        help="Pay part of this bill with Pets Empire store credit — for example an animal trade.",
    )
    store_credit_already_issued = fields.Boolean(
        string="Credit already issued",
        help="Tick if you already granted this store credit, even if some was "
        "spent on a sale. Leave unticked to grant new store credit as payment.",
    )
    store_credit_amount = fields.Monetary(
        string="Store credit amount",
        currency_field="currency_id",
    )
    store_credit_available = fields.Monetary(
        string="Store credit on account",
        currency_field="currency_id",
        compute="_compute_store_credit_available",
    )
    has_store_credit = fields.Boolean(
        compute="_compute_store_credit_available",
    )
    store_credit_applied = fields.Monetary(
        string="Store credit applied",
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
    receipt_display = fields.Char(
        string="Receipt",
        compute="_compute_receipt_display",
        store=True,
    )
    can_return_stock = fields.Boolean(
        compute="_compute_can_return_stock",
    )
    can_pay_bill = fields.Boolean(
        compute="_compute_can_pay_bill",
    )
    can_delete_payment = fields.Boolean(
        compute="_compute_can_delete_payment",
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
    payment_journal_amount = fields.Monetary(
        string="Paid from cash or bank",
        currency_field="currency_id",
        compute="_compute_payment_status",
    )
    payment_journal_label = fields.Char(
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

    @api.depends("state", "partner_id", "invoice_number", "new_supplier_name")
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
            elif receive.partner_id:
                receive.display_name = _(
                    "Draft — %(supplier)s",
                    supplier=receive.partner_id.display_name,
                )
            elif receive.new_supplier_name:
                receive.display_name = _(
                    "Draft — %(supplier)s",
                    supplier=receive.new_supplier_name,
                )
            elif receive.invoice_number:
                receive.display_name = _(
                    "Draft — %(invoice)s",
                    invoice=receive.invoice_number,
                )
            else:
                receive.display_name = _("Draft")

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
        "line_ids.product_id",
        "charge_ids.price_subtotal",
        "charge_ids.price_tax",
        "charge_ids.price_total",
        "charge_ids.amount",
        "charge_ids.name",
        "charge_ids",
        "state",
        "bill_id",
        "bill_id.invoice_line_ids",
        "bill_id.invoice_line_ids.price_subtotal",
        "bill_id.invoice_line_ids.price_total",
        "bill_id.invoice_line_ids.product_id",
        "bill_id.invoice_line_ids.name",
        "bill_id.invoice_line_ids.display_type",
        "bill_id.invoice_line_ids.account_id",
        "bill_id.invoice_line_ids.avea_additional_charge",
        "bill_id.amount_untaxed",
        "bill_id.amount_tax",
        "bill_id.amount_total",
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
            extra = receive._avea_bill_extra_charge_lines()
            extra_untaxed = sum(extra.mapped("price_subtotal"))
            extra_total = sum(extra.mapped("price_total"))
            extra_tax = extra_total - extra_untaxed
            receive.amount_charges_untaxed = charge_untaxed + extra_untaxed
            receive.amount_charges_tax = charge_tax + extra_tax
            receive.amount_charges_total = charge_total + extra_total
            receive.charge_count = len(charges) + len(extra)
            receive.charge_line_count = len(receive.charge_ids) + len(extra)
            receive.amount_untaxed = product_untaxed + charge_untaxed + extra_untaxed
            receive.amount_tax = product_tax + charge_tax + extra_tax
            receive.amount_total = product_total + charge_total + extra_total
            # Bank recon matches the paid vendor bill, including its tax rounding.
            if receive.state == "done" and receive.bill_id:
                bill = receive.bill_id
                receive.amount_untaxed = bill.amount_untaxed
                receive.amount_tax = bill.amount_tax
                receive.amount_total = bill.amount_total

    @api.depends("line_ids.product_id", "line_ids.quantity")
    def _compute_confirmation_stats(self):
        for receive in self:
            lines = receive.line_ids.filtered("product_id")
            receive.product_count = len(lines)
            receive.quantity_total = sum(lines.mapped("quantity"))

    def _avea_payment_source_label(self):
        self.ensure_one()
        mixin = self.env["avea.stock.mixin"]
        journal = mixin._avea_journal_from_bill_payment(self.bill_id)
        if journal:
            return journal.display_name
        if self.paid_from_journal_id:
            return self.paid_from_journal_id.display_name
        return False

    @api.depends(
        "amount_total",
        "state",
        "mark_as_paid",
        "paid_from_journal_id",
        "supplier_credit_applied",
        "store_credit_applied",
        "bill_id",
        "bill_id.amount_residual",
        "bill_id.payment_state",
        "bill_id.line_ids.matched_debit_ids",
        "bill_id.line_ids.matched_credit_ids",
        "currency_id",
    )
    def _compute_payment_status(self):
        mixin = self.env["avea.stock.mixin"]
        Statement = self.env["account.bank.statement.line"]
        for receive in self:
            currency = receive.currency_id or receive.env.company.currency_id
            supplier = receive.supplier_credit_applied or 0.0
            store = receive.store_credit_applied or 0.0
            total = receive.amount_total or 0.0
            residual = receive.bill_id.amount_residual if receive.bill_id else 0.0
            payments = (
                mixin._avea_statement_lines_for_bill(receive.bill_id)
                if receive.bill_id
                else Statement
            )

            parts = []
            if not currency.is_zero(supplier):
                parts.append(
                    _("Supplier credit %(amount)s", amount=currency.format(supplier))
                )
            if not currency.is_zero(store):
                parts.append(
                    _("Store credit %(amount)s", amount=currency.format(store))
                )

            journal_amount = 0.0
            source = False
            if payments:
                journal_amount = currency.round(
                    sum(abs(line.amount or 0.0) for line in payments)
                )
                source = payments[:1].journal_id.display_name
                for journal in payments.mapped("journal_id"):
                    amount = currency.round(
                        sum(
                            abs(line.amount or 0.0)
                            for line in payments
                            if line.journal_id == journal
                        )
                    )
                    if currency.is_zero(amount):
                        continue
                    parts.append(
                        _(
                            "%(journal)s %(amount)s",
                            journal=journal.display_name,
                            amount=currency.format(amount),
                        )
                    )
            elif receive.state != "done" and receive.mark_as_paid:
                source = receive._avea_payment_source_label()
                journal_amount = currency.round(total - supplier - store)
                if currency.compare_amounts(journal_amount, 0.0) < 0:
                    journal_amount = 0.0
                if not currency.is_zero(journal_amount):
                    parts.append(
                        _(
                            "%(journal)s %(amount)s",
                            journal=source or _("Cash or bank"),
                            amount=currency.format(journal_amount),
                        )
                    )

            receive.payment_journal_amount = journal_amount
            receive.payment_journal_label = source or _("Cash or bank")

            if receive.bill_id and not currency.is_zero(residual):
                parts.append(_("Still due %(amount)s", amount=currency.format(residual)))
            if not parts:
                if receive.bill_id and receive.bill_id.payment_state in (
                    "paid",
                    "in_payment",
                ):
                    parts.append(_("Paid"))
                else:
                    parts.append(_("Unpaid"))
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
            receive.totals_mismatch = not self.env[
                "avea.stock.mixin"
            ]._avea_amounts_within_cent(receive.amount_total, receive.invoice_total)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if "user_id" in fields_list and not values.get("user_id"):
            values["user_id"] = self.env.user.id
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
            self.paid_from_journal_id = False

    @api.onchange("add_new_supplier")
    def _onchange_add_new_supplier(self):
        if self.add_new_supplier:
            self.partner_id = False

    def _avea_receive_action(self, record, name=None, view_xmlid=None):
        if record and record.exists() and record.state == "done":
            record._avea_sync_charges_from_bill()
        view_id = self.env.ref(
            view_xmlid or "avea_till.view_avea_stock_receive_form"
        ).id
        context = dict(self.env.context)
        context["clear_breadcrumbs"] = True
        context["avea_receive_workspace"] = True
        return {
            "type": "ir.actions.act_window",
            "name": name or _("Receive Stock"),
            "res_model": self._name,
            "view_mode": "form",
            "views": [(view_id, "form")],
            "view_id": view_id,
            "res_id": record.id,
            "target": "main",
            "context": context,
        }

    @api.model
    def action_open_receive(self):
        """Open the Receive Stock list: drafts and recent receipts."""
        list_id = self.env.ref("avea_till.view_avea_stock_receive_list").id
        form_id = self.env.ref("avea_till.view_avea_stock_receive_form").id
        return {
            "type": "ir.actions.act_window",
            "name": _("Receive Stock"),
            "res_model": self._name,
            "view_mode": "list,form",
            "views": [(list_id, "list"), (form_id, "form")],
            "search_view_id": self.env.ref("avea_till.view_avea_stock_receive_search").id,
            "target": "main",
            "context": {
                "clear_breadcrumbs": True,
                "create": False,
                "avea_receive_workspace": True,
            },
        }

    @api.model
    def action_new_receive(self):
        """Start a fresh draft without replacing other in-progress receives."""
        receive = self._avea_create_draft_receive()
        return receive._avea_receive_action(receive)

    def action_open_record(self):
        """Open a draft to continue, or a completed receive from history."""
        self.ensure_one()
        self._avea_repair_false_done()
        if self.state == "done":
            return self._avea_receive_action(
                self,
                name=_("Stock received"),
                view_xmlid="avea_till.view_avea_stock_receive_history_form",
            )
        return self._avea_receive_action(self)

    def action_back_to_receive_list(self):
        """Keep this receive as a draft and return to the list."""
        return self.action_open_receive()

    @api.model
    def action_open_receive_history(self):
        view_id = self.env.ref("avea_till.view_avea_stock_receive_history_list").id
        form_id = self.env.ref("avea_till.view_avea_stock_receive_history_form").id
        return {
            "type": "ir.actions.act_window",
            "name": _("Receive history"),
            "res_model": self._name,
            "view_mode": "list,form",
            "views": [(view_id, "list"), (form_id, "form")],
            "domain": [("state", "=", "done")],
            "search_view_id": self.env.ref(
                "avea_till.view_avea_stock_receive_history_search"
            ).id,
            "target": "main",
            "context": {
                "clear_breadcrumbs": True,
                "create": False,
                "avea_stock_history_readonly": True,
            },
        }

    @api.depends(
        "picking_id",
        "picking_id.display_name",
        "purchase_order_id",
        "bill_id",
        "invoice_number",
        "partner_id",
    )
    def _compute_receipt_display(self):
        for receive in self:
            picking = receive._avea_get_receipt_picking()
            receive.receipt_display = picking.display_name if picking else ""

    @api.model
    def _avea_sync_missing_picking_links(self):
        """Link history rows to WH/IN receipts and purchase orders when missing."""
        receives = self.sudo().search(
            [
                ("state", "=", "done"),
                "|",
                ("picking_id", "=", False),
                ("purchase_order_id", "=", False),
            ]
        )
        updated = 0
        for receive in receives:
            picking = receive._avea_get_receipt_picking()
            order = receive.purchase_order_id
            if not order and receive.bill_id:
                order = receive.bill_id.invoice_line_ids.purchase_line_id.order_id[:1]
            if not order and picking:
                order = picking.move_ids.purchase_line_id.order_id[:1]
            if not order and receive.invoice_number and receive.partner_id:
                order = self.env["purchase.order"].search(
                    [
                        ("origin", "=", AVEA_RECEIVE_ORIGIN),
                        ("partner_id", "=", receive.partner_id.id),
                        ("partner_ref", "=", receive.invoice_number.strip()),
                    ],
                    limit=1,
                )
            vals = {}
            if picking and not receive.picking_id:
                vals["picking_id"] = picking.id
            if order and not receive.purchase_order_id:
                vals["purchase_order_id"] = order.id
            if vals:
                receive.write(vals)
                updated += 1
        return updated

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

    @api.depends("state", "bill_id", "bill_id.amount_residual")
    def _compute_can_pay_bill(self):
        for receive in self:
            bill = receive.bill_id
            receive.can_pay_bill = bool(
                receive.state == "done"
                and bill
                and not bill.currency_id.is_zero(bill.amount_residual)
            )

    @api.depends(
        "state",
        "bill_id",
        "bill_id.line_ids.matched_debit_ids",
        "bill_id.line_ids.matched_credit_ids",
    )
    def _compute_can_delete_payment(self):
        mixin = self.env["avea.stock.mixin"]
        for receive in self:
            lines = mixin._avea_statement_lines_for_bill(receive.bill_id)
            receive.can_delete_payment = bool(
                receive.state == "done"
                and lines.filtered(lambda line: line.avea_can_delete_payment)
            )

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

    @api.depends("partner_id", "effective_partner_id")
    def _compute_store_credit_available(self):
        mixin = self.env["avea.stock.mixin"]
        for receive in self:
            partner = receive.effective_partner_id or receive.partner_id
            available = mixin._avea_partner_store_credit_balance(partner)
            receive.store_credit_available = available
            receive.has_store_credit = available > 0.0

    @api.onchange("use_store_credit")
    def _onchange_use_store_credit(self):
        if not self.use_store_credit:
            return
        partner = self.effective_partner_id or self.partner_id
        balance = self.env["avea.stock.mixin"]._avea_partner_store_credit_balance(
            partner
        )
        self.store_credit_already_issued = balance > 0.0
        if self.currency_id.is_zero(self.store_credit_amount or 0.0):
            total = self.amount_total or 0.0
            self.store_credit_amount = min(total, balance) if balance else total

    def action_return_this_stock(self):
        self.ensure_one()
        picking = self._avea_get_receipt_picking()
        if not picking:
            raise UserError(
                _("No stock receipt was found for this receive. Open the receipt from Inventory.")
            )
        return self.env["avea.stock.return"].action_open_return_for_picking(picking)

    def action_back_to_receive_history(self):
        if self.env.context.get("avea_receive_workspace"):
            return self.action_open_receive()
        return self.action_open_receive_history()

    def action_avea_delete_receive_payment(self):
        self.ensure_one()
        if not self.env.user._avea_can_delete_supplier_payment():
            raise AccessError(_("Only an administrator can delete a payment."))
        mixin = self.env["avea.stock.mixin"].sudo()
        lines = mixin._avea_statement_lines_for_bill(self.bill_id)
        deletable = lines.filtered(
            lambda line: line.avea_is_supplier_payment and not line.avea_cleared
        )
        if not deletable:
            raise UserError(
                _("There is no cash or bank payment on this receipt to delete.")
            )
        for line in deletable:
            line._avea_unlink_supplier_payment()
        self.invalidate_recordset()
        return True

    def action_open_pay_bill_wizard(self):
        self.ensure_one()
        if not self.can_pay_bill:
            raise UserError(_("This bill is already paid or has no balance due."))
        wizard = (
            self.env["avea.stock.receive.pay.wizard"]
            .sudo()
            .create(
                {
                    "receive_id": self.id,
                }
            )
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Pay vendor bill"),
            "res_model": "avea.stock.receive.pay.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

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

    def action_open_product_import(self):
        """Upload an ordered-products spreadsheet into this receive draft."""
        self.ensure_one()
        if self.state != "draft" or self.show_confirmation:
            raise UserError(_("Import products on a Receive Stock draft."))
        wizard = self.env["avea.stock.receive.import"].create(
            {"receive_id": self.id}
        )
        view = self.env.ref("avea_till.view_avea_stock_receive_import_form")
        return {
            "type": "ir.actions.act_window",
            "name": _("Import ordered products"),
            "res_model": "avea.stock.receive.import",
            "res_id": wizard.id,
            "view_mode": "form",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "new",
        }

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
        """Throw away this draft and return to the Receive Stock list."""
        self.ensure_one()
        self._avea_repair_false_done()
        if self.state == "draft":
            self.unlink()
        return self.env["avea.stock.receive"].action_open_receive()

    def _avea_archive_completed(self):
        """Leave completed receives in the database for Receive history."""

    @api.model
    def _avea_backfill_receive_history(self):
        """Recreate history rows from Avea purchase orders (e.g. after old confirmation deletes)."""
        Purchase = self.env["purchase.order"].sudo()
        orders = Purchase.search([("origin", "=", AVEA_RECEIVE_ORIGIN)])
        created = 0
        for order in orders:
            if self._avea_find_history_for_order(order):
                continue
            bill = order.invoice_ids.filtered(
                lambda move: move.move_type == "in_invoice" and move.state == "posted"
            )[:1]
            picking = order.picking_ids.filtered(
                lambda pick: pick.picking_type_code == "incoming" and pick.state == "done"
            )[:1]
            lines = order.order_line.filtered(
                lambda line: not line.display_type and line.product_id
            )
            if not lines:
                continue
            invoice_number = (order.partner_ref or bill.ref or order.name or "").strip()
            invoice_date = (
                bill.invoice_date
                if bill
                else (order.date_order.date() if order.date_order else fields.Date.today())
            )
            received_date = (
                picking.date_done.date()
                if picking and picking.date_done
                else invoice_date
            )
            line_commands = [
                Command.create(
                    {
                        "product_id": line.product_id.id,
                        "quantity": line.product_qty,
                        "price_unit": line.price_unit,
                        "discount": line.discount or 0.0,
                    }
                )
                for line in lines
            ]
            self.sudo().create(
                {
                    "state": "done",
                    "user_id": order.user_id.id or self.env.user.id,
                    "company_id": order.company_id.id,
                    "currency_id": order.currency_id.id,
                    "partner_id": order.partner_id.id,
                    "invoice_number": invoice_number,
                    "invoice_date": invoice_date,
                    "received_date": received_date,
                    "purchase_order_id": order.id,
                    "picking_id": picking.id if picking else False,
                    "bill_id": bill.id if bill else False,
                    "line_ids": line_commands,
                }
            )
            created += 1
        self._avea_sync_missing_picking_links()
        return created

    @api.model
    def _avea_find_history_for_order(self, order):
        domain = [("state", "=", "done"), ("purchase_order_id", "=", order.id)]
        if self.sudo().search_count(domain):
            return True
        bills = order.invoice_ids.ids
        if bills and self.sudo().search_count([("state", "=", "done"), ("bill_id", "in", bills)]):
            return True
        ref = (order.partner_ref or "").strip()
        if ref:
            return bool(
                self.sudo().search_count(
                    [
                        ("state", "=", "done"),
                        ("partner_id", "=", order.partner_id.id),
                        ("invoice_number", "=", ref),
                    ],
                    limit=1,
                )
            )
        return False

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
        self.line_ids._avea_keep_pricing_for_free_lines()
        mixin = self.env["avea.stock.mixin"]
        pending = self.line_ids.filtered(
            lambda line: line.product_id
            and not line._avea_typed_cost_matches_catalogue()
            and not line.avea_pricing_choice
        )
        if pending:
            return pending[0].action_open_pricing_wizard()
        self.line_ids._avea_snapshot_catalog_pricing()
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
        store_credit_applied = 0.0
        if self.use_store_credit:
            store_credit_applied = mixin._avea_apply_store_credit_to_vendor_bill(
                bill,
                partner,
                self.company_id,
                self.store_credit_amount,
                already_issued=self.store_credit_already_issued,
                pay_date=self._avea_payment_date(),
                payment_ref=self.invoice_number,
            )
        if self.mark_as_paid:
            bill.invalidate_recordset(["amount_residual", "payment_state"])
            if not bill.currency_id.is_zero(bill.amount_residual):
                self._avea_pay_vendor_bill(
                    bill,
                    self._avea_payment_journal(),
                    partner,
                    self.company_id,
                    self._avea_payment_date(),
                    self.invoice_number,
                )
        return self._avea_success(
            partner,
            order,
            bill,
            picking=picking,
            credit_applied=credit_applied,
            store_credit_applied=store_credit_applied,
        )

    def _avea_apply_product_cost_updates(self):
        """Pricing updates are applied in the pricing popup; keep for compatibility."""
        return

    def _avea_existing_invoice_receive(self, partner, invoice_number):
        """Find a completed receive with the same supplier invoice number."""
        self.ensure_one()
        number = (invoice_number or "").strip()
        if not partner or not number:
            return self.browse()
        return self.sudo().search(
            [
                ("id", "!=", self.id),
                ("state", "=", "done"),
                ("company_id", "=", self.company_id.id),
                ("partner_id", "=", partner.id),
                ("invoice_number", "=ilike", number),
            ],
            limit=1,
        )

    def _avea_check_receive(self, partner):
        self.ensure_one()
        mixin = self.env["avea.stock.mixin"]
        if not partner:
            raise ValidationError(_("Choose a supplier, or add a new one."))
        invoice_number = (self.invoice_number or "").strip()
        if not invoice_number:
            raise ValidationError(_("Enter the supplier invoice number."))
        existing = self._avea_existing_invoice_receive(partner, invoice_number)
        if existing:
            raise ValidationError(
                _(
                    "Invoice %(invoice)s has already been received for %(supplier)s.",
                    invoice=invoice_number,
                    supplier=partner.display_name,
                )
            )
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
            discounted = line._avea_discounted_unit_cost()
            if mixin._avea_compare_supplier_cost(line.price_unit, 0.0) < 0 or (
                mixin._avea_compare_supplier_cost(discounted, 0.0) < 0
            ):
                raise ValidationError(
                    _(
                        "Cost for %(product)s cannot be negative.",
                        product=line.product_id.display_name,
                    )
                )
            if not line.product_id.is_storable:
                raise ValidationError(
                    _("%(product)s is not a stock product.",
                      product=line.product_id.display_name)
                )
        if self.totals_mismatch:
            raise ValidationError(
                _(
                    "The captured total %(received)s does not match the invoice "
                    "total %(invoice)s. Fix quantities, costs, or charges before receiving.",
                    received=self.currency_id.format(self.amount_total or 0.0),
                    invoice=self.currency_id.format(self.invoice_total or 0.0),
                )
            )
        if self.use_store_credit:
            amount = self.store_credit_amount or 0.0
            if self.currency_id.compare_amounts(amount, 0.0) <= 0:
                raise ValidationError(
                    _("Enter the store credit amount used to pay this supplier.")
                )
        if self.mark_as_paid or self.use_store_credit:
            if not self.payment_date:
                raise ValidationError(_("Enter the payment date."))
        if self.mark_as_paid:
            self._avea_payment_journal()

    def _avea_ensure_supplier(self):
        self.ensure_one()
        if not self.add_new_supplier:
            partner = self.partner_id
            if partner and partner.supplier_rank < 1:
                partner.sudo().write({"supplier_rank": 1})
            return partner
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

    def _avea_charge_match_key(self, name, amount):
        self.ensure_one()
        currency = self.currency_id
        rounded = currency.round(amount) if currency else round(amount or 0.0, 2)
        return ((name or "").strip().casefold(), rounded)

    def _avea_bill_invoice_product_lines(self):
        """Vendor-bill product lines (skip sections, notes, and tax/payable)."""
        self.ensure_one()
        bill = self.bill_id
        if not bill:
            return self.env["account.move.line"]
        return bill.invoice_line_ids.filtered(
            lambda line: line.display_type in (False, "product")
        )

    def _avea_bill_line_is_charge(self, line, receive_products):
        """Postage, courier, and other non-stock bill lines."""
        if line.avea_additional_charge:
            return True
        if not line.product_id:
            return True
        if line.product_id in receive_products:
            return False
        if not line.product_id.is_storable:
            return True
        account = line.account_id
        return bool(
            account
            and (
                account.code == "610060"
                or account.account_type in ("expense", "expense_direct_cost")
            )
        )

    def _avea_bill_extra_charge_lines(self):
        """Bill lines that are not receive products and not already on charge_ids.

        Postage, courier, and other expense lines added on the vendor bill after
        receive would otherwise be missing from Receive history and bank recon.
        """
        self.ensure_one()
        if self.state != "done" or not self.bill_id:
            return self.env["account.move.line"]
        receive_products = self.line_ids.product_id
        currency = self.currency_id
        claimed = [
            self._avea_charge_match_key(charge.name, charge.amount)
            for charge in self.charge_ids.filtered(lambda charge: charge.amount)
        ]
        leftover = self.env["account.move.line"]
        for line in self._avea_bill_invoice_product_lines():
            amount = line.price_subtotal
            if amount <= 0 or (currency and currency.is_zero(amount)):
                continue
            if not self._avea_bill_line_is_charge(line, receive_products):
                continue
            key = self._avea_charge_match_key(line.name, amount)
            matched = False
            for index, claimed_key in enumerate(claimed):
                if claimed_key == key:
                    claimed.pop(index)
                    matched = True
                    break
            if matched:
                continue
            leftover |= line
        return leftover

    def _avea_sync_charges_from_bill(self):
        """Copy extra vendor-bill expense lines onto receive charges."""
        if self.env.context.get("avea_skip_bill_charge_sync"):
            return self
        for receive in self:
            if not receive.exists() or receive.state != "done" or not receive.bill_id:
                continue
            leftover = receive._avea_bill_extra_charge_lines()
            if not leftover:
                continue
            commands = []
            for line in leftover:
                commands.append(
                    Command.create(
                        {
                            "name": (line.name or _("Additional charge")).strip()
                            or _("Additional charge"),
                            "amount": line.price_subtotal,
                            "charge_kind": "expense",
                        }
                    )
                )
            receive.with_context(avea_skip_bill_charge_sync=True).sudo().write(
                {"charge_ids": commands}
            )
            try:
                leftover.sudo().write({"avea_additional_charge": True})
            except Exception:
                _logger.debug(
                    "Could not mark extra vendor-bill lines as Avea charges on receive %s",
                    receive.id,
                    exc_info=True,
                )
        return self

    def web_read(self, *args, **kwargs):
        self._avea_sync_charges_from_bill()
        return super().web_read(*args, **kwargs)

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

    def _avea_payment_date(self):
        self.ensure_one()
        return self.payment_date or self.invoice_date or fields.Date.context_today(self)

    @api.onchange("mark_as_paid", "use_store_credit", "invoice_date")
    def _onchange_payment_date_default(self):
        if (self.mark_as_paid or self.use_store_credit) and not self.payment_date:
            self.payment_date = self.invoice_date or fields.Date.context_today(self)

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

    def _avea_success(
        self,
        partner,
        order,
        bill,
        picking=False,
        credit_applied=0.0,
        store_credit_applied=0.0,
    ):
        self.write(
            {
                "state": "done",
                "bill_id": bill.id,
                "partner_id": partner.id,
                "add_new_supplier": False,
                "purchase_order_id": order.id,
                "picking_id": picking.id if picking else False,
                "supplier_credit_applied": credit_applied,
                "store_credit_applied": store_credit_applied,
                "mark_as_paid": self.mark_as_paid,
                "payment_date": self._avea_payment_date()
                if self.mark_as_paid or self.use_store_credit
                else self.payment_date,
                "paid_from_journal_id": (
                    self.paid_from_journal_id.id
                    if self.mark_as_paid and self.paid_from_journal_id
                    else False
                ),
            }
        )
        try:
            self._avea_send_receive_report()
        except Exception:
            _logger.exception(
                "Failed to email the Receive Stock report for receive %s",
                self.id,
            )
        return self._avea_confirmation_action()

    def _avea_confirmation_action(self):
        self.ensure_one()
        return self._avea_receive_action(
            self,
            name=_("Stock Received"),
        )
