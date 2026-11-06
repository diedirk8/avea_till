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
        string="Bill type",
        compute="_compute_avea_supplier_bill_info",
    )
    avea_linked_receive_id = fields.Many2one(
        "avea.stock.receive",
        string="Stock receipt",
        compute="_compute_avea_supplier_bill_info",
    )
    avea_can_pay_bill = fields.Boolean(
        compute="_compute_avea_supplier_bill_info",
    )

    @api.depends(
        "move_type",
        "state",
        "ref",
        "name",
        "invoice_origin",
        "invoice_line_ids.name",
        "amount_residual",
        "currency_id",
    )
    def _compute_avea_supplier_bill_info(self):
        Receive = self.env["avea.stock.receive"].sudo()
        receives = Receive.search([("bill_id", "in", self.ids)])
        receive_by_bill = {receive.bill_id.id: receive for receive in receives}
        for move in self:
            receive = receive_by_bill.get(move.id)
            move.avea_linked_receive_id = receive
            move.avea_can_pay_bill = bool(
                move.move_type == "in_invoice"
                and move.state == "posted"
                and move.currency_id
                and not move.currency_id.is_zero(move.amount_residual)
            )
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

    def action_avea_open_supplier(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("This bill has no supplier."))
        return self.partner_id.action_avea_open_supplier()

    def action_avea_pay_supplier_bill(self):
        self.ensure_one()
        if not self.avea_can_pay_bill:
            raise UserError(_("This bill is already paid or is not a supplier bill."))
        journals = (
            self.company_id.sudo()._avea_expense_journals()
            if self.company_id
            else self.env["account.journal"]
        )
        default_journal = journals.filtered(
            lambda journal: journal.type == "cash"
        )[:1] or journals[:1]
        wizard = (
            self.env["avea.supplier.bill.pay.wizard"]
            .sudo()
            .create(
                {
                    "bill_id": self.id,
                    "amount": self.amount_residual,
                    "pay_date": fields.Date.context_today(self),
                    "journal_id": default_journal.id if default_journal else False,
                }
            )
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Record payment"),
            "res_model": "avea.supplier.bill.pay.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
            "context": {"avea_supplier_workspace": True},
        }
