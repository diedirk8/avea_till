# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountMoveSupplierBill(models.Model):
    _inherit = "account.move"

    avea_supplier_bill_label = fields.Char(
        string="What this is",
        compute="_compute_avea_supplier_bill_info",
    )
    avea_supplier_bill_source = fields.Selection(
        selection=[
            ("stock", "Stock receipt"),
            ("expense", "Expense"),
            ("credit", "Credit note"),
            ("bill", "Supplier bill"),
        ],
        string="Source",
        compute="_compute_avea_supplier_bill_info",
    )
    avea_linked_receive_id = fields.Many2one(
        "avea.stock.receive",
        string="Stock receipt",
        compute="_compute_avea_supplier_bill_info",
    )
    avea_can_pay_from_receive = fields.Boolean(
        compute="_compute_avea_supplier_bill_info",
    )

    @api.depends(
        "move_type",
        "ref",
        "name",
        "invoice_origin",
        "invoice_line_ids.name",
        "amount_residual",
    )
    def _compute_avea_supplier_bill_info(self):
        Receive = self.env["avea.stock.receive"].sudo()
        receives = Receive.search([("bill_id", "in", self.ids)])
        receive_by_bill = {receive.bill_id.id: receive for receive in receives}
        for move in self:
            receive = receive_by_bill.get(move.id)
            move.avea_linked_receive_id = receive
            move.avea_can_pay_from_receive = bool(receive and receive.can_pay_bill)
            if move.move_type == "in_refund":
                move.avea_supplier_bill_source = "credit"
                move.avea_supplier_bill_label = (
                    move.ref or move.name or _("Supplier credit note")
                )
                continue
            if receive:
                move.avea_supplier_bill_source = "stock"
                invoice = receive.invoice_number or move.ref or move.name
                move.avea_supplier_bill_label = _("Stock receipt %s", invoice)
                continue
            origin = (move.invoice_origin or "").lower()
            if "operational expense" in origin:
                lines = move.invoice_line_ids.filtered(
                    lambda line: line.display_type == "product"
                )
                move.avea_supplier_bill_source = "expense"
                move.avea_supplier_bill_label = (
                    lines[:1].name or move.ref or _("Expense")
                )
                continue
            move.avea_supplier_bill_source = "bill"
            move.avea_supplier_bill_label = (
                move.ref or move.invoice_origin or move.name or _("Supplier bill")
            )

    def _avea_use_supplier_bill_form(self):
        self.ensure_one()
        if self.env.context.get("avea_supplier_workspace"):
            return self.move_type in ("in_invoice", "in_refund")
        user = self.env.user
        if not (
            hasattr(user, "_avea_uses_product_shell") and user._avea_uses_product_shell()
        ):
            return False
        return self.move_type in ("in_invoice", "in_refund")

    def get_formview_id(self, access_uid=None):
        user = self.env.user
        if access_uid:
            user = self.env["res.users"].browse(access_uid)
        if hasattr(user, "_avea_uses_product_shell") and user._avea_uses_product_shell():
            if len(self) == 1 and self._avea_use_supplier_bill_form():
                return self.env.ref("avea_till.view_avea_supplier_bill_form").id
        return super().get_formview_id(access_uid=access_uid)

    def get_formview_action(self, access_uid=None):
        action = super().get_formview_action(access_uid=access_uid)
        user = self.env.user
        if access_uid:
            user = self.env["res.users"].browse(access_uid)
        if hasattr(user, "_avea_uses_product_shell") and user._avea_uses_product_shell():
            if len(self) == 1 and self._avea_use_supplier_bill_form():
                view_id = self.env.ref("avea_till.view_avea_supplier_bill_form").id
                action["views"] = [(view_id, "form")]
                ctx = dict(action.get("context") or {})
                ctx["avea_supplier_workspace"] = True
                action["context"] = ctx
        return action

    def action_avea_open_linked_receive(self):
        self.ensure_one()
        receive = self.avea_linked_receive_id
        if not receive:
            raise UserError(_("This bill is not linked to a stock receipt."))
        return receive._avea_receive_action(
            receive,
            name=_("Stock received"),
            view_xmlid="avea_till.view_avea_stock_receive_history_form",
        )

    def action_avea_pay_supplier_bill(self):
        self.ensure_one()
        receive = self.avea_linked_receive_id
        if receive and receive.can_pay_bill:
            return receive.action_open_pay_bill_wizard()
        raise UserError(
            _(
                "This bill is not an unpaid stock receipt. "
                "If it is an expense, record the payment from Money."
            )
        )
