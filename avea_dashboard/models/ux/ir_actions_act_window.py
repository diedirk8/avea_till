# -*- coding: utf-8 -*-
from odoo import models


class IrActionsActWindow(models.Model):
    _inherit = "ir.actions.act_window"

    def _get_action_dict(self):
        """Resolve Avea Users domain on the server (safe for the web client)."""
        result = super()._get_action_dict()
        avea_users = self.env.ref(
            "avea_till.action_avea_users_window", raise_if_not_found=False
        )
        if avea_users and self.id == avea_users.id:
            result["domain"] = self.env["res.users"]._avea_users_domain()
        return result
