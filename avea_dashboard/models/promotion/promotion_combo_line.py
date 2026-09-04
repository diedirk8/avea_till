from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AveaPromotionComboLine(models.Model):
    _name = "avea.promotion.combo.line"
    _description = "Avea Combo Price Line"
    _order = "id"

    promotion_id = fields.Many2one(
        "avea.promotion",
        required=True,
        ondelete="cascade",
        index=True,
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        domain="[('sale_ok', '=', True), ('available_in_pos', '=', True)]",
    )
    quantity = fields.Float(
        string="Qty",
        required=True,
        default=1.0,
        digits="Product Unit",
    )
    company_id = fields.Many2one(related="promotion_id.company_id", store=True)
    currency_id = fields.Many2one(related="promotion_id.currency_id")

    @api.constrains("quantity", "product_id", "promotion_id")
    def _check_combo_line(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("Combo product quantity must be greater than zero."))
            duplicates = line.promotion_id.combo_line_ids.filtered(
                lambda other: other.product_id == line.product_id and other.id != line.id
            )
            if duplicates:
                raise ValidationError(
                    _("Each product can only appear once in a combo. Increase the quantity instead.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.mapped("promotion_id").filtered(
            lambda promotion: promotion.deal_type == "combo_price"
        )._sync_loyalty_program()
        return lines

    def write(self, vals):
        res = super().write(vals)
        self.mapped("promotion_id").filtered(
            lambda promotion: promotion.deal_type == "combo_price"
        )._sync_loyalty_program()
        return res

    def unlink(self):
        promotions = self.mapped("promotion_id").filtered(
            lambda promotion: promotion.deal_type == "combo_price"
        )
        res = super().unlink()
        promotions.exists()._sync_loyalty_program()
        return res
