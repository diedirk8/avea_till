from datetime import datetime, time

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_round


AVEA_RECEIVE_ORIGIN = "Avea Receive Stock"
AVEA_SUPPLIER_COST_PRECISION = "Avea Supplier Cost"
AVEA_PRODUCT_COST_PRECISION = "Product Price"


class AveaStockMixin(models.AbstractModel):
    _name = "avea.stock.mixin"
    _description = "Avea Stock Helpers"

    @api.model
    def _avea_product_cost_digits(self):
        return self.env["decimal.precision"].precision_get(AVEA_PRODUCT_COST_PRECISION)

    @api.model
    def _avea_supplier_cost_digits(self):
        return self.env["decimal.precision"].precision_get(AVEA_SUPPLIER_COST_PRECISION)

    @api.model
    def _avea_round_product_cost(self, amount):
        return float_round(amount or 0.0, precision_digits=self._avea_product_cost_digits())

    @api.model
    def _avea_round_supplier_cost(self, amount):
        return float_round(amount or 0.0, precision_digits=self._avea_supplier_cost_digits())

    @api.model
    def _avea_round_percent(self, amount):
        return float_round(amount or 0.0, precision_digits=2)

    @api.model
    def _avea_compare_product_cost(self, left, right):
        return float_compare(
            left or 0.0,
            right or 0.0,
            precision_digits=self._avea_product_cost_digits(),
        )

    @api.model
    def _avea_compare_supplier_cost(self, left, right):
        return float_compare(
            left or 0.0,
            right or 0.0,
            precision_digits=self._avea_supplier_cost_digits(),
        )

    @api.model
    def _avea_supplier_cost_matches_product_cost(self, supplier_cost, product_cost):
        """True when a 4dp supplier cost equals a 2dp Avea product cost."""
        return (
            self._avea_compare_product_cost(supplier_cost, product_cost) == 0
            or self._avea_compare_product_cost(
                self._avea_round_supplier_cost(supplier_cost), product_cost
            )
            == 0
        )

    def _avea_datetime_at_noon(self, date_value):
        if not date_value:
            return fields.Datetime.now()
        if isinstance(date_value, datetime):
            return date_value
        return datetime.combine(date_value, time(12, 0, 0))

    def _avea_complete_picking(self, picking, date_done=None):
        """Confirm and validate a picking without exposing Odoo wizards."""
        self.ensure_one()
        picking = picking.sudo()
        if not picking:
            raise UserError(_("There is no stock receipt to complete."))
        if picking.state == "draft":
            picking.action_confirm()
        for move in picking.move_ids.filtered(lambda move: move.state != "cancel"):
            if move.product_uom.is_zero(move.quantity) and not move.product_uom.is_zero(
                move.product_uom_qty
            ):
                move.quantity = move.product_uom_qty
            move.picked = True
        picking.with_context(
            skip_backorder=True,
            skip_sanity_check=True,
            cancel_backorder=True,
            button_validate_picking_ids=picking.ids,
        ).button_validate()
        if picking.state != "done":
            picking._action_done()
        if picking.state != "done":
            raise UserError(
                _("The stock receipt could not be completed. Ask your administrator to check Inventory.")
            )
        if date_done:
            done_at = self._avea_datetime_at_noon(date_done)
            picking.write({"date_done": done_at, "scheduled_date": done_at})
            picking.move_ids.write({"date": done_at})
        return picking

    def _avea_incoming_picking(self, purchase_order):
        pickings = purchase_order.sudo().picking_ids.filtered(
            lambda picking: picking.state not in ("done", "cancel")
            and picking.picking_type_code == "incoming"
        )
        return pickings[:1]

    def _avea_supplier_payable_account(self, partner, company):
        payable = partner.with_company(company).property_account_payable_id
        if not payable:
            raise UserError(
                _("This supplier has no payable account. Ask your accountant to set one up.")
            )
        return payable

    def _avea_pay_vendor_bill(self, bill, journal, partner, company, pay_date, payment_ref):
        """Pay a vendor bill from an Avea cash/bank journal.

        Matches Operational Expense: statement line + payable reconciliation.
        """
        payable = self._avea_supplier_payable_account(partner, company)
        amount = bill.amount_residual
        if bill.currency_id.is_zero(amount):
            return self.env["account.bank.statement.line"]
        statement_line = (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(
                {
                    "journal_id": journal.id,
                    "amount": -amount,
                    "date": pay_date,
                    "payment_ref": payment_ref,
                    "partner_id": partner.id,
                    "counterpart_account_id": payable.id,
                }
            )
        )
        bill_lines = bill.line_ids.filtered(
            lambda line: line.account_id == payable and not line.reconciled
        )
        statement_lines = statement_line.move_id.line_ids.filtered(
            lambda line: line.account_id == payable and not line.reconciled
        )
        to_reconcile = bill_lines | statement_lines
        if len(to_reconcile) >= 2:
            to_reconcile.sudo().reconcile()
        return statement_line
