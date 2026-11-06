# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.tools.safe_eval import safe_eval


class ResPartnerSupplierCentre(models.Model):
    _inherit = "res.partner"

    avea_supplierinfo_ids = fields.One2many(
        "product.supplierinfo",
        "partner_id",
        string="Products supplied",
    )
    avea_stock_receive_ids = fields.One2many(
        "avea.stock.receive",
        "partner_id",
        string="Stock receipts",
    )
    avea_supplier_currency_id = fields.Many2one(
        "res.currency",
        string="Supplier currency",
        compute="_compute_avea_supplier_stats",
        store=True,
    )
    avea_supplier_product_count = fields.Integer(
        string="Products",
        compute="_compute_avea_supplier_stats",
        store=True,
    )
    avea_supplier_last_receipt = fields.Date(
        string="Last receipt",
        compute="_compute_avea_supplier_stats",
        store=True,
    )
    avea_supplier_spend_total = fields.Monetary(
        string="Purchases",
        compute="_compute_avea_supplier_stats",
        store=True,
        currency_field="avea_supplier_currency_id",
    )
    avea_supplier_payable = fields.Monetary(
        string="We owe",
        compute="_compute_avea_supplier_stats",
        store=True,
        currency_field="avea_supplier_currency_id",
    )
    avea_supplier_credit_available = fields.Monetary(
        string="Supplier credit",
        compute="_compute_avea_supplier_stats",
        store=True,
        currency_field="avea_supplier_currency_id",
    )
    avea_open_vendor_move_ids = fields.Many2many(
        "account.move",
        string="Open bills",
        compute="_compute_avea_open_vendor_moves",
    )

    @api.depends(
        "company_id",
        "company_id.currency_id",
        "avea_supplierinfo_ids",
        "avea_supplierinfo_ids.product_tmpl_id",
        "avea_stock_receive_ids.state",
        "avea_stock_receive_ids.received_date",
        "invoice_ids.state",
        "invoice_ids.move_type",
        "invoice_ids.amount_total",
        "invoice_ids.amount_residual",
    )
    def _compute_avea_supplier_stats(self):
        currency = self.env.company.currency_id
        spend = {partner.id: 0.0 for partner in self}
        payable = {partner.id: 0.0 for partner in self}
        credit = {partner.id: 0.0 for partner in self}
        partner_ids = [partner.id for partner in self if partner.id]
        if partner_ids:
            Move = self.env["account.move"].sudo()
            bill_groups = Move._read_group(
                domain=[
                    ("partner_id", "in", partner_ids),
                    ("move_type", "=", "in_invoice"),
                    ("state", "=", "posted"),
                ],
                groupby=["partner_id"],
                aggregates=["amount_total:sum", "amount_residual:sum"],
            )
            for partner, total, residual in bill_groups:
                partner_id = partner.id if isinstance(partner, models.Model) else partner
                spend[partner_id] = total or 0.0
                payable[partner_id] = residual or 0.0
            credit_groups = Move._read_group(
                domain=[
                    ("partner_id", "in", partner_ids),
                    ("move_type", "=", "in_refund"),
                    ("state", "=", "posted"),
                ],
                groupby=["partner_id"],
                aggregates=["amount_residual:sum"],
            )
            for partner, residual in credit_groups:
                partner_id = partner.id if isinstance(partner, models.Model) else partner
                credit[partner_id] = abs(residual or 0.0)
        for partner in self:
            partner.avea_supplier_currency_id = (
                partner.company_id.currency_id or currency
            )
            templates = partner.avea_supplierinfo_ids.mapped("product_tmpl_id")
            partner.avea_supplier_product_count = len(templates)
            receipts = partner.avea_stock_receive_ids.filtered(
                lambda receive: receive.state == "done" and receive.received_date
            )
            partner.avea_supplier_last_receipt = max(
                receipts.mapped("received_date"),
                default=False,
            )
            partner.avea_supplier_spend_total = spend.get(partner.id, 0.0)
            partner.avea_supplier_payable = payable.get(partner.id, 0.0)
            partner.avea_supplier_credit_available = credit.get(partner.id, 0.0)

    @api.depends(
        "invoice_ids.state",
        "invoice_ids.move_type",
        "invoice_ids.amount_residual",
    )
    def _compute_avea_open_vendor_moves(self):
        Move = self.env["account.move"].sudo()
        for partner in self:
            if not partner.id:
                partner.avea_open_vendor_move_ids = Move.browse()
                continue
            partner.avea_open_vendor_move_ids = Move.search(
                [
                    ("partner_id", "=", partner.id),
                    ("move_type", "in", ("in_invoice", "in_refund")),
                    ("state", "=", "posted"),
                    ("amount_residual", "!=", 0),
                ],
                order="invoice_date desc, id desc",
            )

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get("avea_supplier_workspace"):
            for vals in vals_list:
                vals.setdefault("supplier_rank", 1)
                vals.setdefault("is_company", True)
        return super().create(vals_list)

    def _avea_use_supplier_workspace_form(self):
        self.ensure_one()
        if self.env.context.get("avea_supplier_workspace"):
            return True
        if self.env.context.get("avea_customer_workspace"):
            return False
        return bool(self.supplier_rank) and not self.customer_rank

    def action_avea_open_supplier(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": self.id,
            "view_mode": "form",
            "views": [
                (self.env.ref("avea_till.view_avea_supplier_form").id, "form"),
            ],
            "target": "current",
            "context": dict(self.env.context, avea_supplier_workspace=True),
        }

    def action_avea_open_supplier_products(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "avea_till.action_avea_stock_workspace"
        )
        action["name"] = _("Products from %s", self.display_name)
        action["domain"] = [
            ("avea_supplier_id", "=", self.id),
        ]
        ctx = action.get("context") or {}
        if isinstance(ctx, str):
            ctx = safe_eval(ctx, {"uid": self.env.uid})
        ctx = dict(ctx)
        ctx["default_avea_supplier_id"] = self.id
        action["context"] = ctx
        return action

    def action_avea_open_what_we_owe(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("What we owe %s", self.display_name),
            "res_model": "account.move",
            "view_mode": "list,form",
            "views": [
                (
                    self.env.ref("avea_till.view_avea_supplier_open_bill_list").id,
                    "list",
                ),
                (
                    self.env.ref("avea_till.view_avea_supplier_bill_form").id,
                    "form",
                ),
            ],
            "domain": [
                ("partner_id", "=", self.id),
                ("move_type", "in", ("in_invoice", "in_refund")),
                ("state", "=", "posted"),
                ("amount_residual", "!=", 0),
            ],
            "context": {
                "avea_supplier_workspace": True,
                "create": False,
                "delete": False,
            },
            "target": "current",
        }

    def action_avea_open_supplier_receipts(self):
        self.ensure_one()
        action = self.env["avea.stock.receive"].action_open_receive_history()
        action["name"] = _("Receipts from %s", self.display_name)
        action["domain"] = [
            ("state", "=", "done"),
            ("partner_id", "=", self.id),
        ]
        return action

    def action_avea_receive_stock(self):
        """Open Receive Stock with this supplier already chosen."""
        self.ensure_one()
        if self.supplier_rank < 1:
            self.sudo().write({"supplier_rank": 1})
        Receive = self.env["avea.stock.receive"]
        draft = Receive.search(
            Receive._avea_draft_domain() + [("partner_id", "=", self.id)],
            order="write_date desc, id desc",
            limit=1,
        )
        if not draft:
            empty = Receive.search(
                Receive._avea_draft_domain()
                + [
                    ("partner_id", "=", False),
                    ("line_ids", "=", False),
                    ("invoice_number", "=", False),
                ],
                order="write_date desc, id desc",
                limit=1,
            )
            draft = empty or Receive._avea_create_draft_receive()
            draft.write({"partner_id": self.id, "add_new_supplier": False})
        else:
            draft._avea_repair_false_done()
        return draft._avea_receive_action(draft)

    def action_avea_add_supplier_expense(self):
        self.ensure_one()
        if self.supplier_rank < 1:
            self.sudo().write({"supplier_rank": 1})
        action = self.env["avea.operational.expense.wizard"].action_open_wizard()
        action["context"] = dict(
            action.get("context") or {},
            default_partner_id=self.id,
            avea_operational_expense_supplier=1,
        )
        return action

    @api.model
    def avea_supplier_owing_domain(self):
        return [("avea_supplier_payable", ">", 0)]

    @api.model
    def avea_supplier_credit_domain(self):
        return [("avea_supplier_credit_available", ">", 0)]
