# -*- coding: utf-8 -*-
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class AveaSupplierOpeningArrearsWizard(models.TransientModel):
    _name = "avea.supplier.opening.arrears.wizard"
    _description = "Supplier Opening Arrears"

    partner_id = fields.Many2one(
        "res.partner",
        string="Supplier",
        required=True,
        domain="[('supplier_rank', '>', 0)]",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    bill_date = fields.Date(
        string="Outstanding from",
        required=True,
        default=fields.Date.context_today,
        help="Date the old account starts in Avea. Use the date you switched systems.",
    )
    amount = fields.Monetary(
        string="Still owed",
        currency_field="currency_id",
        required=True,
    )
    ref = fields.Char(
        string="Their reference",
        help="Optional — invoice numbers from the previous system.",
    )
    offset_account_id = fields.Many2one(
        "account.account",
        string="Opening account",
        required=True,
        domain=(
            "[('company_ids', 'in', company_id), "
            "('account_type', 'in', ('equity', 'equity_unaffected'))]"
        ),
        help="The other side of the old debt. This is not an expense — it is "
        "the opening balance brought in from the previous system.",
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        values.setdefault("company_id", self.env.company.id)
        partner = self.env["res.partner"].browse(
            values.get("partner_id") or self.env.context.get("default_partner_id")
        )
        if partner:
            values["partner_id"] = partner.id
        company = self.env["res.company"].browse(
            values.get("company_id") or self.env.company.id
        )
        if "offset_account_id" in (fields_list or ["offset_account_id"]) and not values.get(
            "offset_account_id"
        ):
            account = self._avea_default_offset_account(company)
            if account:
                values["offset_account_id"] = account.id
        return values

    @api.model
    def _avea_default_offset_account(self, company):
        Account = self.env["account.account"].sudo()
        domain = [
            ("company_ids", "in", company.id),
            ("account_type", "in", ("equity", "equity_unaffected")),
        ]
        named = Account.search(
            domain + [("name", "ilike", "opening")],
            limit=1,
        )
        return named or Account.search(domain, limit=1, order="code")

    def action_create_arrears(self):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        amount = currency.round(self.amount or 0.0)
        if currency.compare_amounts(amount, 0.0) <= 0:
            raise UserError(_("Enter the amount still owed to this supplier."))
        if not self.offset_account_id:
            raise UserError(_("Choose the opening-balance account for the other side."))
        bill = self.env["account.move"].sudo().create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_id.id,
                "company_id": self.company_id.id,
                "invoice_date": self.bill_date,
                "invoice_date_due": self.bill_date,
                "ref": self.ref or _("Opening arrears"),
                "invoice_origin": _("Opening arrears"),
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": self.ref or _("Opening arrears from previous system"),
                            "account_id": self.offset_account_id.id,
                            "quantity": 1,
                            "price_unit": amount,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
            }
        )
        bill.action_post()
        self.partner_id.invalidate_recordset()
        return {
            "type": "ir.actions.act_window",
            "name": _("Bills — %s", self.partner_id.display_name),
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": bill.id,
            "views": [
                (
                    self.env.ref("avea_till.view_avea_supplier_bill_form").id,
                    "form",
                )
            ],
            "context": {"avea_supplier_workspace": True},
            "target": "current",
        }
