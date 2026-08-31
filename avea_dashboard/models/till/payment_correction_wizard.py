from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AveaPaymentCorrectionWizard(models.TransientModel):
    _name = "avea.payment.correction.wizard"
    _description = "Correct Payment Method"

    order_id = fields.Many2one(
        "pos.order",
        string="Order",
        required=True,
        ondelete="cascade",
    )
    current_method_id = fields.Many2one(
        "pos.payment.method",
        string="Current Method",
        readonly=True,
    )
    amount = fields.Monetary(
        string="Amount",
        readonly=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        related="order_id.currency_id",
        string="Currency",
    )
    new_method_id = fields.Many2one(
        "pos.payment.method",
        string="Correct To",
        required=True,
        domain="[('id', 'in', available_method_ids)]",
    )
    available_method_ids = fields.Many2many(
        "pos.payment.method",
        compute="_compute_available_method_ids",
    )
    reason = fields.Char(
        string="Reason",
        required=True,
    )

    @api.depends("order_id", "current_method_id")
    def _compute_available_method_ids(self):
        for wizard in self:
            order = wizard.order_id
            if not order:
                wizard.available_method_ids = False
                continue
            current = wizard.current_method_id
            wizard.available_method_ids = (
                order._avea_open_session_correction_methods() - current
            )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        order = self.env["pos.order"]
        if values.get("order_id"):
            order = self.env["pos.order"].browse(values["order_id"]).exists()
        elif self.env.context.get("active_model") == "pos.order":
            order = self.env["pos.order"].browse(self.env.context.get("active_id")).exists()
        if not order:
            return values
        order._avea_assert_can_correct_payment()
        tender = order._avea_correctable_tender()
        values["order_id"] = order.id
        values["current_method_id"] = tender.payment_method_id.id
        values["amount"] = tender.amount
        return values

    def action_confirm(self):
        self.ensure_one()
        if not self.new_method_id:
            raise UserError(_("Select a payment method."))
        self.order_id.avea_correct_payment_method(self.new_method_id.id, self.reason)
        return {"type": "ir.actions.act_window_close"}
