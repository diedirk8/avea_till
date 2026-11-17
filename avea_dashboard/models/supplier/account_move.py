# -*- coding: utf-8 -*-
from collections.abc import Collection

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools.safe_eval import safe_eval


def _avea_search_values(value):
    """Unwrap Odoo 19 domain values (`in` + OrderedSet) into a plain list."""
    if isinstance(value, str) or value is False or value is True or value is None:
        return [value]
    if isinstance(value, Collection):
        return list(value)
    return [value]


class AccountMoveSupplierBill(models.Model):
    _inherit = "account.move"

    avea_supplier_bill_label = fields.Char(
        string="What this is",
        compute="_compute_avea_supplier_bill_info",
        search="_search_avea_supplier_bill_label",
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
        search="_search_avea_supplier_bill_source",
    )
    avea_linked_receive_id = fields.Many2one(
        "avea.stock.receive",
        string="Stock receipt",
        compute="_compute_avea_supplier_bill_info",
    )
    avea_can_pay_bill = fields.Boolean(
        compute="_compute_avea_supplier_bill_info",
    )
    avea_bill_status = fields.Selection(
        selection=[
            ("open", "Open"),
            ("overdue", "Overdue"),
            ("paid", "Paid"),
            ("credit", "Credit"),
        ],
        string="Bill status",
        compute="_compute_avea_bill_status",
        search="_search_avea_bill_status",
    )
    avea_amount_paid = fields.Monetary(
        string="Amount paid",
        currency_field="currency_id",
        compute="_compute_avea_bill_status",
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

    def _search_avea_supplier_bill_label(self, operator, value):
        return [
            "|",
            "|",
            ("ref", operator, value),
            ("name", operator, value),
            ("invoice_origin", operator, value),
        ]

    def _search_avea_supplier_bill_source(self, operator, value):
        if operator not in ("=", "in", "!=", "not in"):
            return NotImplemented
        values = _avea_search_values(value)
        stock_bills = (
            self.env["avea.stock.receive"]
            .sudo()
            .search([("bill_id", "!=", False)])
            .mapped("bill_id")
        )
        parts = []
        for item in values:
            if item == "credit":
                parts.append(Domain([("move_type", "=", "in_refund")]))
            elif item == "stock":
                parts.append(Domain([("id", "in", stock_bills.ids)]))
            elif item == "expense":
                parts.append(Domain([("invoice_origin", "ilike", "operational expense")]))
            elif item == "bill":
                parts.append(
                    Domain(
                        [
                            ("move_type", "=", "in_invoice"),
                            ("id", "not in", stock_bills.ids),
                            ("invoice_origin", "not ilike", "operational expense"),
                        ]
                    )
                )
        if not parts:
            result = Domain(False)
        else:
            result = Domain.OR(parts)
        if operator in ("!=", "not in"):
            return ~result
        return result

    @api.depends(
        "move_type",
        "invoice_date",
        "invoice_date_due",
        "amount_residual",
        "amount_total",
        "currency_id",
    )
    def _compute_avea_bill_status(self):
        today = fields.Date.context_today(self)
        for move in self:
            if move._name != "account.move":
                move.avea_amount_paid = 0.0
                move.avea_bill_status = False
                continue
            paid = move.amount_total - move.amount_residual
            move.avea_amount_paid = move.currency_id.round(paid) if move.currency_id else paid
            if move.move_type == "in_refund":
                move.avea_bill_status = "credit"
                continue
            if not move.currency_id or move.currency_id.is_zero(move.amount_residual):
                move.avea_bill_status = "paid"
                continue
            due = move.invoice_date_due or move.invoice_date
            if due and due < today:
                move.avea_bill_status = "overdue"
            else:
                move.avea_bill_status = "open"

    def _search_avea_bill_status(self, operator, value):
        if operator not in ("=", "in", "!=", "not in"):
            return NotImplemented
        values = _avea_search_values(value)
        today = fields.Date.context_today(self)
        domains = []
        for status in values:
            if status == "credit":
                domains.append(
                    Domain(
                        [("move_type", "=", "in_refund"), ("state", "=", "posted")]
                    )
                )
            elif status == "paid":
                domains.append(
                    Domain(
                        [
                            ("move_type", "=", "in_invoice"),
                            ("state", "=", "posted"),
                            ("amount_residual", "=", 0),
                        ]
                    )
                )
            elif status == "overdue":
                domains.append(
                    Domain(
                        [
                            ("move_type", "=", "in_invoice"),
                            ("state", "=", "posted"),
                            ("amount_residual", "!=", 0),
                            "|",
                            ("invoice_date_due", "<", today),
                            "&",
                            ("invoice_date_due", "=", False),
                            ("invoice_date", "<", today),
                        ]
                    )
                )
            elif status == "open":
                domains.append(
                    Domain(
                        [
                            ("move_type", "=", "in_invoice"),
                            ("state", "=", "posted"),
                            ("amount_residual", "!=", 0),
                            "|",
                            ("invoice_date_due", ">=", today),
                            "&",
                            ("invoice_date_due", "=", False),
                            "|",
                            ("invoice_date", "=", False),
                            ("invoice_date", ">=", today),
                        ]
                    )
                )
        result = Domain.OR(domains) if domains else Domain(False)
        if operator in ("!=", "not in"):
            return ~result
        return result

    def action_avea_pay_bills(self):
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "avea_till.action_avea_pay_bills_wizard"
        )
        ctx = action.get("context") or {}
        if isinstance(ctx, str):
            ctx = safe_eval(ctx, {"uid": self.env.uid})
        ctx = dict(ctx)
        ctx["avea_supplier_workspace"] = True
        moves = self.filtered(lambda move: move.move_type == "in_invoice")
        if len(moves) == 1:
            ctx["default_partner_id"] = moves.partner_id.id
            ctx["default_bill_id"] = moves.id
        elif len(moves.mapped("partner_id")) == 1:
            ctx["default_partner_id"] = moves.partner_id.id
        action["context"] = ctx
        return action

    def action_avea_open_bills(self):
        return self.env["ir.actions.act_window"]._for_xml_id(
            "avea_till.action_avea_bills"
        )

    def _avea_use_supplier_bill_form(self):
        self.ensure_one()
        if self._name != "account.move":
            return False
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
        wizard = (
            self.env["avea.supplier.bill.pay.wizard"]
            .sudo()
            .create(
                {
                    "bill_id": self.id,
                    "amount": self.amount_residual,
                    "pay_date": fields.Date.context_today(self),
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
