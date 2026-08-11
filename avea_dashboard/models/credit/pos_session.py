from odoo import models, api


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _load_pos_data_models(self, config):
        models = super()._load_pos_data_models(config)
        if config.avea_credit_enabled:
            models.append("avea.credit.reason")
        return models

    def load_data(self, models_to_load):
        response = super().load_data(models_to_load)
        config = self.config_id
        credit_enabled = config.avea_credit_enabled
        credit_manager_xmlid = "avea_till.group_avea_credit_manager"

        for user_data in response.get("res.users", []):
            user = self.env["res.users"].browse(user_data["id"])
            can_issue = credit_enabled and user.has_group(credit_manager_xmlid)
            user_data["can_issue_store_credit"] = can_issue
            user_data["_can_issue_store_credit"] = can_issue

        for employee_data in response.get("hr.employee", []):
            user = self.env["hr.employee"].browse(employee_data["id"]).user_id
            can_issue = (
                credit_enabled
                and bool(user)
                and user.has_group(credit_manager_xmlid)
            )
            employee_data["can_issue_store_credit"] = can_issue
            employee_data["_can_issue_store_credit"] = can_issue

        return response

    def action_pos_session_close(
        self,
        balancing_account=False,
        amount_to_balance=0,
        bank_payment_method_diffs=None,
    ):
        # Ensure PM/journal/liability are aligned before Odoo creates session-close
        # account moves (_validate_session → _create_account_move).
        companies = self.mapped("config_id.company_id")
        companies.with_context(
            avea_credit_before_session_close=True
        )._avea_credit_ensure_accounting_setup()
        return super().action_pos_session_close(
            balancing_account, amount_to_balance, bank_payment_method_diffs
        )
