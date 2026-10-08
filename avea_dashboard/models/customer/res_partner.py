# -*- coding: utf-8 -*-
from odoo import api, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get("avea_customer_workspace"):
            for vals in vals_list:
                vals.setdefault("customer_rank", 1)
        return super().create(vals_list)

    def _avea_use_customer_workspace_form(self):
        self.ensure_one()
        return bool(self.customer_rank)

    def action_avea_open_customer(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
            "context": dict(self.env.context, avea_customer_workspace=True),
        }

    def get_formview_id(self, access_uid=None):
        user = self.env.user
        if access_uid:
            user = self.env["res.users"].browse(access_uid)
        if hasattr(user, "_avea_uses_product_shell") and user._avea_uses_product_shell():
            if len(self) == 1 and self._avea_use_customer_workspace_form():
                return self.env.ref("avea_till.view_avea_customer_form").id
        return super().get_formview_id(access_uid=access_uid)

    def get_formview_action(self, access_uid=None):
        action = super().get_formview_action(access_uid=access_uid)
        user = self.env.user
        if access_uid:
            user = self.env["res.users"].browse(access_uid)
        if hasattr(user, "_avea_uses_product_shell") and user._avea_uses_product_shell():
            if len(self) == 1 and self._avea_use_customer_workspace_form():
                view_id = self.env.ref("avea_till.view_avea_customer_form").id
                action["views"] = [(view_id, "form")]
                ctx = dict(action.get("context") or {})
                ctx["avea_customer_workspace"] = True
                action["context"] = ctx
        return action
