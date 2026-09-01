from datetime import datetime, time

from odoo import _, fields, models
from odoo.exceptions import UserError


AVEA_RECEIVE_ORIGIN = "Avea Receive Stock"
AVEA_SUPPLIER_COST_PRECISION = "Avea Supplier Cost"


class AveaStockMixin(models.AbstractModel):
    _name = "avea.stock.mixin"
    _description = "Avea Stock Helpers"

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
