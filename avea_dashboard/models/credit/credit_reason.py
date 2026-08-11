from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AveaCreditReason(models.Model):
    _name = "avea.credit.reason"
    _inherit = ["pos.load.mixin"]
    _description = "Credit Reason"
    _order = "sequence, name, id"

    name = fields.Char(
        string="Name",
        required=True,
        translate=True,
    )
    active = fields.Boolean(
        string="Active",
        default=True,
    )
    sequence = fields.Integer(
        string="Sequence",
        default=10,
    )
    manual_issue = fields.Boolean(
        string="Manual Issue",
        default=False,
        help="Available when issuing store credit manually.",
    )
    system_generated = fields.Boolean(
        string="System Generated",
        default=False,
        help="Used for automated store credit transactions such as POS refunds.",
    )
    protected = fields.Boolean(
        string="Protected",
        default=False,
        help="Application-owned credit reasons cannot be archived or deleted.",
    )
    is_outflow = fields.Boolean(
        string="Reduces Balance",
        default=False,
        help="When set, this reason reduces the customer's store credit balance.",
    )

    def _raise_protected_reason_error(self):
        raise ValidationError(
            _(
                "System credit reasons are required by the application and "
                "cannot be archived or deleted."
            )
        )

    def write(self, vals):
        if vals.get("active") is False and self.filtered("protected"):
            self._raise_protected_reason_error()
        return super().write(vals)

    def unlink(self):
        if self.filtered("protected"):
            self._raise_protected_reason_error()
        return super().unlink()

    @api.model
    def _load_pos_data_domain(self, data, config):
        if not config.avea_credit_enabled:
            return False
        return [("active", "=", True), ("manual_issue", "=", True)]

    @api.model
    def _load_pos_data_fields(self, config):
        return ["id", "name", "sequence"]
