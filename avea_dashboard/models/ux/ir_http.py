from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        result = super().session_info()
        user = self.env.user
        uses_shell = user._avea_uses_product_shell()
        result["avea_product_shell"] = uses_shell
        if uses_shell:
            nav = user._avea_nav_structure()
            if nav:
                result["avea_nav"] = nav
                result["avea_role"] = nav["role"]
            action = user._avea_home_action()
            if action:
                result["home_action_id"] = action.id
            if user.has_group("base.group_system"):
                settings_action_id = user._avea_odoo_settings_action_id()
                if settings_action_id:
                    result["avea_odoo_settings_action_id"] = settings_action_id
                result["avea_odoo_settings_url"] = "/odoo/settings"
        return result

    def webclient_rendering_context(self):
        result = super().webclient_rendering_context()
        result.setdefault("title", "Avea")
        return result
