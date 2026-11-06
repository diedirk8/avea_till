from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def _visible_menu_ids(self, debug=False):
        """Hide non-Avea menus from normal Avea users.

        Records stay active so operators and direct URLs still reach the
        underlying Odoo screens. Only the navigation is suppressed.
        """
        visible_ids = super()._visible_menu_ids(debug=debug)
        if not self.env.user._avea_uses_product_shell():
            return visible_ids
        avea_root = self.env.ref("avea_till.menu_avea_root", raise_if_not_found=False)
        if not avea_root:
            return visible_ids
        allowed_ids = set(self.search([("id", "child_of", avea_root.id)]).ids)
        return frozenset(menu_id for menu_id in visible_ids if menu_id in allowed_ids)
