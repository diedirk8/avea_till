from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AveaCreditIssueWizard(models.TransientModel):
    _name = "avea.credit.issue.wizard"
    _description = "Issue Store Credit"

    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
    )
    amount = fields.Monetary(
        string="Amount",
        required=True,
        currency_field="currency_id",
    )
    reason_id = fields.Many2one(
        "avea.credit.reason",
        string="Reason",
        required=True,
        domain="[('active', '=', True), ('manual_issue', '=', True)]",
        default=lambda self: self._default_reason_id(),
    )
    notes = fields.Text(
        string="Notes",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )

    @api.model
    def _default_reason_id(self):
        return self.env["avea.credit.reason"].search(
            [("active", "=", True), ("manual_issue", "=", True)],
            order="sequence, name, id",
            limit=1,
        )

    @api.constrains("amount")
    def _check_amount_positive(self):
        for wizard in self:
            if wizard.currency_id.compare_amounts(wizard.amount, 0.0) <= 0:
                raise ValidationError(
                    _("Store credit amount must be greater than zero.")
                )

    def action_issue_credit(self):
        self.ensure_one()
        self.partner_id._avea_credit_ensure_customer()
        self.env["avea.credit.ledger.entry"].create_issued_credit(
            partner=self.partner_id,
            amount=self.amount,
            reason=self.reason_id,
            notes=self.notes,
        )
        action = self.env["avea.credit.ledger.entry"].action_open_ledger(
            partner_id=self.partner_id.id,
        )
        action["name"] = _("%s — Store Credit") % self.partner_id.display_name
        return action

    @api.model
    def action_open_wizard(self, partner_id=None):
        context = {}
        if partner_id:
            context["default_partner_id"] = partner_id
        return {
            "type": "ir.actions.act_window",
            "name": _("Issue Store Credit"),
            "res_model": self._name,
            "view_mode": "form",
            "view_id": self.env.ref(
                "avea_till.view_avea_credit_issue_wizard_form"
            ).id,
            "target": "new",
            "context": context,
        }
