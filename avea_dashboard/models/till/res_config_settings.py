from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    avea_cash_safe_journal_id = fields.Many2one(
        related="company_id.avea_cash_safe_journal_id",
        readonly=False,
        string="Cash Safe / Company Cash Journal",
        domain=(
            "[('type', '=', 'cash'), "
            "('company_id', '=', company_id), "
            "('name', 'not ilike', 'store credit')]"
        ),
    )
    avea_transfer_journal_ids = fields.Many2many(
        related="company_id.avea_transfer_journal_ids",
        readonly=False,
        string="Accounts available for Transfer Money",
        domain=(
            "[('type', 'in', ('cash', 'bank')), "
            "('company_id', '=', company_id), "
            "('name', 'not ilike', 'store credit')]"
        ),
    )
    avea_register_closure_report_email = fields.Char(
        related="company_id.avea_register_closure_report_email",
        readonly=False,
        string="Register Closure Report Email",
    )
    avea_expense_journal_ids = fields.Many2many(
        related="company_id.avea_expense_journal_ids",
        readonly=False,
        string="Accounts available for Operational Expenses",
        domain=(
            "[('type', 'in', ('cash', 'bank')), "
            "('company_id', '=', company_id), "
            "('name', 'not ilike', 'store credit')]"
        ),
    )
    pos_avea_needs_dedicated_cash_journal = fields.Boolean(
        related="pos_config_id.avea_needs_dedicated_cash_journal",
    )
    pos_avea_product_layout = fields.Selection(
        related="pos_config_id.avea_product_layout",
        readonly=False,
    )
    pos_avea_show_product_code = fields.Boolean(
        related="pos_config_id.avea_show_product_code",
        readonly=False,
    )
    pos_avea_show_stock_quantity = fields.Boolean(
        related="pos_config_id.avea_show_stock_quantity",
        readonly=False,
    )
    pos_avea_show_stock_status = fields.Boolean(
        related="pos_config_id.avea_show_stock_status",
        readonly=False,
    )
    pos_avea_products_per_page = fields.Selection(
        related="pos_config_id.avea_products_per_page",
        readonly=False,
    )
    pos_avea_nav_category_ids = fields.Many2many(
        related="pos_config_id.avea_nav_category_ids",
        readonly=False,
    )

    def action_avea_ensure_dedicated_cash_journal(self):
        self.ensure_one()
        self.pos_config_id.action_avea_ensure_dedicated_cash_journal()
        return {"type": "ir.actions.client", "tag": "reload"}
