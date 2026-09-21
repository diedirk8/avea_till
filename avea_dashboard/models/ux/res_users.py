from odoo import api, models


class ResUsers(models.Model):
    _inherit = ["res.users", "avea.nav.mixin"]

    def _avea_uses_product_shell(self):
        """Normal Avea users see Avea, not the Odoo app switcher.

        Settings administrators keep the full Odoo backend so operators can
        still reach underlying functionality without it appearing in the
        retail product navigation.
        """
        self.ensure_one()
        return (
            not self._is_system()
            and self.has_group("avea_till.group_avea_cashier")
        )

    def _avea_home_action(self):
        """Home action for /web and /odoo when no deeper URL was requested."""
        self.ensure_one()
        if not self._avea_uses_product_shell():
            return self.env["ir.actions.actions"]
        xmlid = "avea_till.action_avea_business_overview"
        if not self.has_group("avea_till.group_avea_manager"):
            xmlid = "avea_till.action_avea_session_dashboard"
        action = self.env.ref(xmlid, raise_if_not_found=False)
        return action or self.env["ir.actions.actions"]

    def _avea_home_url(self):
        action = self._avea_home_action()
        if not action:
            return False
        return "/odoo/action-%s" % action.id

    def _avea_sync_home_action(self):
        for user in self:
            action = user._avea_home_action()
            if action and user.action_id.id != action.id:
                user.with_context(avea_skip_home_action=True).sudo().write(
                    {"action_id": action.id}
                )

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._avea_sync_home_action()
        return users

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("avea_skip_home_action"):
            return result
        if "group_ids" in vals:
            self._avea_sync_home_action()
        return result

    @api.model
    def _avea_assign_default_roles(self):
        """Give existing POS users an Avea role so menu groups stay coherent.

        POS administrators become Manager. POS users who are not administrators
        become Cashier. Owner is never assigned automatically.
        """
        manager = self.env.ref("avea_till.group_avea_manager", raise_if_not_found=False)
        cashier = self.env.ref("avea_till.group_avea_cashier", raise_if_not_found=False)
        pos_manager = self.env.ref(
            "point_of_sale.group_pos_manager", raise_if_not_found=False
        )
        pos_user = self.env.ref("point_of_sale.group_pos_user", raise_if_not_found=False)
        if not manager or not cashier:
            return
        if pos_manager:
            pos_manager.all_user_ids.filtered(
                lambda user: manager not in user.all_group_ids
            ).with_context(avea_skip_home_action=True).write(
                {"group_ids": [(4, manager.id)]}
            )
        if pos_user:
            pos_user.all_user_ids.filtered(
                lambda user: (
                    cashier not in user.all_group_ids
                    and (not pos_manager or pos_manager not in user.all_group_ids)
                )
            ).with_context(avea_skip_home_action=True).write(
                {"group_ids": [(4, cashier.id)]}
            )
        (manager.all_user_ids | cashier.all_user_ids)._avea_sync_home_action()
