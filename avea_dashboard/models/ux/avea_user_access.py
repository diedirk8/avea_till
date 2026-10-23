# -*- coding: utf-8 -*-
"""Avea user roles and Lightspeed-style capability toggles on res.users."""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.safe_eval import safe_eval

_AVEA_ROLE_XMLIDS = (
    "avea_till.group_avea_cashier",
    "avea_till.group_avea_manager",
    "avea_till.group_avea_owner",
)

# Optional capabilities (additive groups beyond the base role).
_AVEA_CAPABILITY_FIELDS = (
    {
        "field": "avea_perm_pos_manager",
        "label": "POS manager at till",
        "help": "Refunds, discounts, and other POS manager actions.",
        "group_xmlid": "point_of_sale.group_pos_manager",
        "section": "sell",
    },
    {
        "field": "avea_perm_correct_payment",
        "label": "Correct payment method",
        "help": "Fix card/cash on open POS orders.",
        "group_xmlid": "avea_till.group_avea_correct_payment",
        "section": "sell",
    },
    {
        "field": "avea_perm_cash_up_all",
        "label": "Cash up any till",
        "help": "Cash up and review tills for all cashiers.",
        "group_xmlid": "avea_till.group_avea_cash_up_manager",
        "section": "sell",
    },
    {
        "field": "avea_perm_store_credit",
        "label": "Issue store credit",
        "help": "Create and adjust customer store credit.",
        "group_xmlid": "avea_till.group_avea_credit_manager",
        "section": "customers",
    },
    {
        "field": "avea_perm_money",
        "label": "Money & bank",
        "help": "Expenses, transfers, bank reconciliation, and balances.",
        "group_xmlid": "avea_till.group_avea_manager",
        "section": "money",
        "role_only": True,
    },
    {
        "field": "avea_perm_stock",
        "label": "Stock workspace",
        "help": "Receive stock, stock take, pricing, and catalogue tools.",
        "group_xmlid": "avea_till.group_avea_manager",
        "section": "stock",
        "role_only": True,
    },
    {
        "field": "avea_perm_promotions",
        "label": "Promotions",
        "help": "Create and edit Avea promotions and combos.",
        "group_xmlid": "avea_till.group_avea_manager",
        "section": "marketing",
        "role_only": True,
    },
    {
        "field": "avea_perm_overview",
        "label": "Business overview",
        "help": "Full dashboard and business reporting (manager home).",
        "group_xmlid": "avea_till.group_avea_manager",
        "section": "insights",
        "role_only": True,
    },
)


class ResUsersAveaAccess(models.Model):
    _inherit = "res.users"

    avea_access_role = fields.Selection(
        selection=[
            ("none", "No Avea access"),
            ("cashier", "Cashier"),
            ("manager", "Manager"),
            ("owner", "Owner"),
        ],
        string="Avea role",
        compute="_compute_avea_access_role",
        inverse="_inverse_avea_access_role",
        store=True,
        help="Primary job profile. Cashiers sell; managers run the business; owners have full Avea access.",
    )
    avea_access_role_label = fields.Char(
        string="Role label",
        compute="_compute_avea_access_role_label",
    )
    avea_is_odoo_administrator = fields.Boolean(
        string="Odoo administrator",
        compute="_compute_avea_access_role_label",
    )
    avea_perm_pos_manager = fields.Boolean(
        string="POS manager at till",
        compute="_compute_avea_permissions",
        inverse="_inverse_avea_permissions",
    )
    avea_perm_correct_payment = fields.Boolean(
        string="Correct payment method",
        compute="_compute_avea_permissions",
        inverse="_inverse_avea_permissions",
    )
    avea_perm_cash_up_all = fields.Boolean(
        string="Cash up any till",
        compute="_compute_avea_permissions",
        inverse="_inverse_avea_permissions",
    )
    avea_perm_store_credit = fields.Boolean(
        string="Issue store credit",
        compute="_compute_avea_permissions",
        inverse="_inverse_avea_permissions",
    )
    avea_perm_money = fields.Boolean(
        string="Money & bank",
        compute="_compute_avea_permissions",
        inverse="_inverse_avea_permissions",
    )
    avea_perm_stock = fields.Boolean(
        string="Stock workspace",
        compute="_compute_avea_permissions",
        inverse="_inverse_avea_permissions",
    )
    avea_perm_promotions = fields.Boolean(
        string="Promotions",
        compute="_compute_avea_permissions",
        inverse="_inverse_avea_permissions",
    )
    avea_perm_overview = fields.Boolean(
        string="Business overview",
        compute="_compute_avea_permissions",
        inverse="_inverse_avea_permissions",
    )
    avea_password = fields.Char(
        string="Password",
        copy=False,
        help="Set or reset the login password. Leave blank to keep the current password.",
    )

    @api.model
    def _avea_role_rank(self, user=None):
        user = user or self.env.user
        if user.has_group("avea_till.group_avea_owner"):
            return 3
        if user.has_group("avea_till.group_avea_manager"):
            return 2
        if user.has_group("avea_till.group_avea_cashier"):
            return 1
        return 0

    @api.model
    def _avea_can_manage_users(self):
        user = self.env.user
        return user.has_group("base.group_system") or user.has_group(
            "avea_till.group_avea_user_admin"
        )

    @api.model
    def _avea_users_action_context(self, extra=None):
        ctx = {
            "avea_users_workspace": True,
            "default_avea_access_role": "cashier",
            "default_company_ids": [(6, 0, self.env.company.ids)],
            "default_company_id": self.env.company.id,
        }
        if extra:
            ctx.update(extra)
        return ctx

    @api.model
    def _avea_merge_action_context(self, action, extra=None):
        ctx = action.get("context") or {}
        if isinstance(ctx, str):
            ctx = safe_eval(ctx, ctx={}) or {}
        if not isinstance(ctx, dict):
            ctx = {}
        ctx.update(self._avea_users_action_context(extra))
        return ctx

    @api.model
    def _avea_group(self, xmlid):
        return self.env.ref(xmlid, raise_if_not_found=False)

    def _avea_has_group(self, user, xmlid):
        group = self._avea_group(xmlid)
        return bool(group and group in user.all_group_ids)

    def _avea_is_role_group(self, group):
        for xmlid in _AVEA_ROLE_XMLIDS:
            ref = self._avea_group(xmlid)
            if ref and ref.id == group.id:
                return True
        return False

    @api.depends("all_group_ids", "avea_access_role")
    def _compute_avea_access_role_label(self):
        role_names = dict(self._fields["avea_access_role"].selection)
        for user in self:
            user.avea_is_odoo_administrator = user._avea_has_group(
                user, "base.group_system"
            )
            if user.avea_is_odoo_administrator:
                user.avea_access_role_label = _("Odoo administrator")
            else:
                user.avea_access_role_label = role_names.get(
                    user.avea_access_role, _("No Avea access")
                )

    @api.depends("all_group_ids")
    def _compute_avea_access_role(self):
        for user in self:
            if user._avea_has_group(user, "avea_till.group_avea_owner"):
                user.avea_access_role = "owner"
            elif user._avea_has_group(user, "avea_till.group_avea_manager"):
                user.avea_access_role = "manager"
            elif user._avea_has_group(user, "avea_till.group_avea_cashier"):
                user.avea_access_role = "cashier"
            else:
                user.avea_access_role = "none"

    def _inverse_avea_access_role(self):
        for user in self:
            user._avea_check_manage_target()
            role = user.avea_access_role or "none"
            if role == "owner" and not self.env.user.has_group("base.group_system"):
                if not self.env.user.has_group("avea_till.group_avea_owner"):
                    raise UserError(_("Only an owner or administrator can assign the Owner role."))
            user._avea_apply_role_groups(role)
            user._avea_sync_home_action()

    @api.depends("all_group_ids", "avea_access_role")
    def _compute_avea_permissions(self):
        for user in self:
            for spec in _AVEA_CAPABILITY_FIELDS:
                group = user._avea_group(spec["group_xmlid"])
                value = bool(group and group in user.all_group_ids)
                if spec.get("role_only"):
                    value = user.avea_access_role in ("manager", "owner")
                user[spec["field"]] = value

    def _inverse_avea_permissions(self):
        for user in self:
            user._avea_check_manage_target()
            for spec in _AVEA_CAPABILITY_FIELDS:
                if spec.get("role_only"):
                    continue
                group = user._avea_group(spec["group_xmlid"])
                if not group:
                    continue
                enabled = bool(user[spec["field"]])
                user._avea_set_group_membership(group, enabled)
            user._avea_sync_home_action()

    def _avea_apply_role_groups(self, role):
        self.ensure_one()
        role_groups = [self._avea_group(xmlid) for xmlid in _AVEA_ROLE_XMLIDS]
        role_groups = [group for group in role_groups if group]
        commands = [(3, group.id) for group in role_groups]
        target = False
        if role == "cashier":
            target = self._avea_group("avea_till.group_avea_cashier")
        elif role == "manager":
            target = self._avea_group("avea_till.group_avea_manager")
        elif role == "owner":
            target = self._avea_group("avea_till.group_avea_owner")
        if target:
            commands.append((4, target.id))
        self.with_context(avea_skip_home_action=True).write({"group_ids": commands})
        if role in ("manager", "owner"):
            self._avea_apply_manager_defaults()
        elif role == "cashier":
            self._avea_apply_cashier_defaults()

    def _avea_apply_manager_defaults(self):
        self.ensure_one()
        for spec in _AVEA_CAPABILITY_FIELDS:
            group = self._avea_group(spec["group_xmlid"])
            if group:
                self._avea_set_group_membership(group, True)

    def _avea_apply_cashier_defaults(self):
        self.ensure_one()
        for spec in _AVEA_CAPABILITY_FIELDS:
            if spec.get("role_only"):
                continue
            group = self._avea_group(spec["group_xmlid"])
            if not group:
                continue
            if spec["field"] in ("avea_perm_pos_manager", "avea_perm_cash_up_all"):
                self._avea_set_group_membership(group, False)
            elif spec["field"] == "avea_perm_correct_payment":
                self._avea_set_group_membership(group, False)

    def _avea_set_group_membership(self, group, enabled):
        self.ensure_one()
        if enabled and group not in self.group_ids:
            self.with_context(avea_skip_home_action=True).write(
                {"group_ids": [(4, group.id)]}
            )
        elif not enabled and group in self.group_ids:
            if self._avea_is_role_group(group):
                return
            self.with_context(avea_skip_home_action=True).write(
                {"group_ids": [(3, group.id)]}
            )

    def _avea_check_manage_target(self):
        self.ensure_one()
        if not self._avea_can_manage_users():
            raise AccessError(_("You do not have permission to manage Avea users."))
        actor_rank = self._avea_role_rank()
        target_rank = self._avea_role_rank(self)
        if self.env.user.id != self.id and target_rank > actor_rank:
            raise AccessError(
                _("You cannot change a user with a higher Avea role than your own.")
            )
        if self.has_group("base.group_system") and not self.env.user.has_group(
            "base.group_system"
        ):
            raise AccessError(_("Only an Odoo administrator can edit this user."))

    def write(self, vals):
        avea_fields = {"avea_access_role"} | {spec["field"] for spec in _AVEA_CAPABILITY_FIELDS}
        if avea_fields.intersection(vals.keys()):
            for user in self:
                user._avea_check_manage_target()
        if "group_ids" in vals and not self.env.context.get("avea_skip_home_action"):
            for user in self:
                if not self._avea_can_manage_users() and not self.env.su:
                    raise AccessError(_("Use Avea Users to change roles and permissions."))
        return super().write(vals)

    def _avea_use_users_workspace_form(self):
        """Use the Avea Users workspace form (survives browser refresh)."""
        self.ensure_one()
        actor = self.env.user
        if not actor._avea_uses_product_shell() or not self._avea_can_manage_users():
            return False
        if self.env.context.get("avea_users_workspace"):
            return True
        return bool(self.filtered_domain(self._avea_users_domain()))

    @api.model
    def get_formview_id(self, access_uid=None):
        user = self.env.user
        if access_uid:
            user = self.env["res.users"].browse(access_uid)
        if (
            len(self) == 1
            and self.with_user(user)._avea_use_users_workspace_form()
        ):
            view = self.env.ref(
                "avea_till.view_avea_users_form", raise_if_not_found=False
            )
            if view:
                return view.id
        return super().get_formview_id(access_uid=access_uid)

    def get_formview_action(self, access_uid=None):
        self.ensure_one()
        action = super().get_formview_action(access_uid=access_uid)
        user = self.env.user
        if access_uid:
            user = self.env["res.users"].browse(access_uid)
        if self.with_user(user)._avea_use_users_workspace_form():
            view_id = self.env.ref("avea_till.view_avea_users_form").id
            action["views"] = [(view_id, "form")]
            action["context"] = self._avea_merge_action_context(action)
        return action

    @api.model
    def _avea_users_domain(self):
        company_ids = self.env.companies.ids
        avea_groups = [
            self.env.ref("avea_till.group_avea_cashier").id,
            self.env.ref("avea_till.group_avea_manager").id,
            self.env.ref("avea_till.group_avea_owner").id,
        ]
        domain = [
            ("share", "=", False),
            "|",
            "|",
            "|",
            ("company_ids", "in", company_ids),
            ("company_id", "in", company_ids),
            ("group_ids", "in", avea_groups),
            ("company_id", "=", False),
        ]
        if not self.env.user.has_group("base.group_system"):
            domain.append(("id", "not in", self._avea_system_user_ids()))
        return domain

    @api.model
    def action_open_avea_users(self):
        if not self._avea_can_manage_users():
            raise AccessError(_("You do not have permission to manage Avea users."))
        window = self.env.ref("avea_till.action_avea_users_window")
        action = window._get_action_dict()
        action["domain"] = self._avea_users_domain()
        action["context"] = self._avea_users_action_context()
        return action

    @api.model
    def action_avea_new_user(self):
        if not self._avea_can_manage_users():
            raise AccessError(_("You do not have permission to manage Avea users."))
        action = self.action_open_avea_users()
        action.update(
            {
                "name": _("New Avea user"),
                "view_mode": "form",
                "views": [
                    (self.env.ref("avea_till.view_avea_users_form").id, "form")
                ],
                "res_id": False,
            }
        )
        return action

    @api.model
    def _avea_system_user_ids(self):
        system_group = self.env.ref("base.group_system", raise_if_not_found=False)
        if not system_group:
            return []
        return system_group.all_user_ids.ids

    def _avea_set_password(self, password):
        self.ensure_one()
        if not password:
            return
        self.sudo().with_context(no_reset_password=True).write({"password": password})

    def action_avea_cancel_user(self):
        return self.env["res.users"].action_open_avea_users()

    def action_avea_save_user(self):
        self.ensure_one()
        self._avea_check_manage_target()
        password = (self.avea_password or "").strip()
        if password:
            self._avea_set_password(password)
            self.avea_password = False
        self._avea_sync_home_action()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("User saved"),
                "message": _(
                    "%(name)s has been saved.",
                    name=self.display_name,
                ),
                "type": "success",
                "sticky": False,
            },
        }
