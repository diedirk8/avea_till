# -*- coding: utf-8 -*-
from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError


AVEA_ACCOUNT_TYPES = (
    "income",
    "income_other",
    "expense",
    "expense_other",
    "expense_direct_cost",
)

AVEA_KIND_SELECTION = [
    ("expense", "Expense"),
    ("expense_other", "Other expense"),
    ("expense_direct_cost", "Cost of goods"),
    ("income", "Income"),
    ("income_other", "Other income"),
]

AVEA_INCOME_TYPES = ("income", "income_other")
AVEA_EXPENSE_TYPES = ("expense", "expense_other", "expense_direct_cost")

_AVEA_CODE_START = {
    "expense": "610080",
    "expense_other": "620080",
    "expense_direct_cost": "500080",
    "income": "400080",
    "income_other": "420080",
}

class AccountAccount(models.Model):
    _inherit = "account.account"

    avea_kind = fields.Selection(
        selection=AVEA_KIND_SELECTION,
        string="Kind",
        compute="_compute_avea_kind",
        inverse="_inverse_avea_kind",
        help="Expense is picked on Add Expense. Income is picked on Record Income.",
    )
    avea_currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        compute="_compute_avea_activity_stats",
    )
    avea_ytd_amount = fields.Monetary(
        string="This year",
        compute="_compute_avea_activity_stats",
        currency_field="avea_currency_id",
        help="Income earned or expenses recorded this year.",
    )
    avea_entry_count = fields.Integer(
        string="Entries",
        compute="_compute_avea_activity_stats",
    )
    avea_has_entries = fields.Boolean(
        string="Has entries",
        compute="_compute_avea_activity_stats",
    )

    @api.depends("account_type")
    def _compute_avea_kind(self):
        allowed = dict(AVEA_KIND_SELECTION)
        for account in self:
            account.avea_kind = (
                account.account_type if account.account_type in allowed else False
            )

    def _inverse_avea_kind(self):
        for account in self:
            if account.avea_kind:
                account.account_type = account.avea_kind

    def _avea_year_bounds(self):
        today = fields.Date.context_today(self)
        return today.replace(month=1, day=1), today

    def _compute_avea_activity_stats(self):
        currency = self.env.company.currency_id
        date_from, date_to = self._avea_year_bounds()
        counts = dict.fromkeys(self.ids, 0)
        totals = dict.fromkeys(self.ids, 0.0)
        all_counts = dict.fromkeys(self.ids, 0)
        if self.ids:
            MoveLine = self.env["account.move.line"].sudo()
            grouped = MoveLine._read_group(
                domain=[
                    ("account_id", "in", self.ids),
                    ("parent_state", "=", "posted"),
                    ("date", ">=", date_from),
                    ("date", "<=", date_to),
                ],
                groupby=["account_id"],
                aggregates=["__count", "balance:sum"],
            )
            for account, count, balance in grouped:
                account_id = account.id if isinstance(account, models.Model) else account
                counts[account_id] = count
                totals[account_id] = balance or 0.0
            posted = MoveLine._read_group(
                domain=[
                    ("account_id", "in", self.ids),
                    ("parent_state", "=", "posted"),
                ],
                groupby=["account_id"],
                aggregates=["__count"],
            )
            for account, count in posted:
                account_id = account.id if isinstance(account, models.Model) else account
                all_counts[account_id] = count
        for account in self:
            account.avea_currency_id = currency
            balance = totals.get(account.id, 0.0)
            if account.account_type in AVEA_INCOME_TYPES:
                account.avea_ytd_amount = -balance
            else:
                account.avea_ytd_amount = balance
            account.avea_entry_count = counts.get(account.id, 0)
            account.avea_has_entries = bool(all_counts.get(account.id, 0))

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if self.env.context.get("avea_account_workspace"):
            values.setdefault("account_type", "expense")
        return values

    @api.model
    def _avea_require_manager(self):
        if self.env.su:
            return
        if not self.env.user.has_group("avea_till.group_avea_manager"):
            raise AccessError(_("Only a manager can add or change accounts."))

    @api.model
    def _avea_next_account_code(self, account_type):
        Account = self.sudo().with_company(self.env.company)
        sample = Account.search(
            [
                ("account_type", "=", account_type),
                ("code", "!=", False),
            ],
            limit=1,
        )
        start = _AVEA_CODE_START.get(account_type, "999080")
        code = sample.code or ""
        if code[:1].isdigit():
            prefix = code[:4] if len(code) >= 4 else code[:3]
            digits = "".join(ch for ch in prefix if ch.isdigit()) or prefix
            start = f"{digits}80"
        return Account._search_new_account_code(start)

    @api.model
    def _avea_prepare_account_vals(self, vals):
        account_type = vals.get("account_type") or vals.get("avea_kind") or "expense"
        if account_type not in AVEA_ACCOUNT_TYPES:
            raise UserError(
                _(
                    "Pick Income or Expense. Bank, cash, and other bookkeeping "
                    "accounts are not added from here."
                )
            )
        name = vals.get("name")
        if isinstance(name, str):
            vals["name"] = name.strip()
            name = vals["name"]
        elif isinstance(name, dict):
            name = next((value for value in name.values() if value), "")
        if not name:
            raise UserError(
                _("Give the account a name, e.g. Electricity or Interest received.")
            )
        vals["account_type"] = account_type
        vals.pop("avea_kind", None)
        company = self.env.company
        if not vals.get("code"):
            vals["code"] = self._avea_next_account_code(account_type)
        vals["company_ids"] = [Command.set([company.id])]
        vals.setdefault("reconcile", False)
        vals.setdefault("active", True)
        return vals

    def _avea_validate_write(self, vals):
        if "account_type" in vals and vals["account_type"] not in AVEA_ACCOUNT_TYPES:
            raise UserError(
                _("Kind can only be Income, Other income, Expense, Other expense, or Cost of goods.")
            )
        if "account_type" in vals:
            locked = self.filtered("avea_has_entries").filtered(
                lambda account: account.account_type != vals["account_type"]
            )
            if locked:
                raise UserError(
                    _(
                        "This account already has entries. Leave the kind as it is, "
                        "or add a new account instead."
                    )
                )

    def _avea_use_workspace_form(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        if not hasattr(user, "_avea_uses_product_shell"):
            return False
        if not user._avea_uses_product_shell():
            return False
        if self.account_type in AVEA_ACCOUNT_TYPES or not self.account_type:
            return True
        return bool(self.env.context.get("avea_account_workspace"))

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get("avea_account_workspace") and not self.env.context.get(
            "avea_account_creating"
        ):
            self._avea_require_manager()
            prepared = [self._avea_prepare_account_vals(dict(vals)) for vals in vals_list]
            creator = self.with_company(self.env.company).with_context(
                avea_account_creating=True
            )
            if not self.env.su and not self.has_access("create"):
                creator = creator.sudo()
            return super(AccountAccount, creator).create(prepared)
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get("avea_account_workspace"):
            if "avea_kind" in vals and vals.get("avea_kind"):
                vals = dict(vals, account_type=vals["avea_kind"])
            vals.pop("avea_kind", None)
            user_keys = set(vals) - {
                "code",
                "code_store",
                "code_mapping_ids",
                "company_ids",
            }
            if user_keys and not self.env.su:
                self._avea_require_manager()
            if "account_type" in vals:
                self._avea_validate_write(vals)
        return super().write(vals)

    def unlink(self):
        if self.env.context.get("avea_account_workspace"):
            self._avea_require_manager()
            self.invalidate_recordset(["avea_has_entries"])
            used = self.filtered("avea_has_entries")
            if used:
                raise UserError(
                    _(
                        "Turn the account off instead of deleting it. It already has entries."
                    )
                )
        return super().unlink()

    def action_avea_view_activity(self):
        self.ensure_one()
        date_from, date_to = self._avea_year_bounds()
        return {
            "type": "ir.actions.act_window",
            "name": _("Activity"),
            "res_model": "account.move.line",
            "view_mode": "list",
            "views": [
                (self.env.ref("avea_till.view_avea_account_activity_list").id, "list")
            ],
            "search_view_id": self.env.ref(
                "avea_till.view_avea_account_activity_search"
            ).id,
            "domain": [
                ("account_id", "=", self.id),
                ("parent_state", "=", "posted"),
            ],
            "context": {
                "avea_account_workspace": True,
                "avea_account_id": self.id,
                "avea_account_name": self.display_name,
                "search_default_this_year": 1,
                "avea_activity_date_from": fields.Date.to_string(date_from),
                "avea_activity_date_to": fields.Date.to_string(date_to),
            },
            "target": "current",
        }

    @api.model
    def get_formview_id(self, access_uid=None):
        user = self.env.user
        if access_uid:
            user = self.env["res.users"].browse(access_uid)
        if (
            len(self) == 1
            and self.with_user(user)._avea_use_workspace_form(user)
        ):
            view = self.env.ref(
                "avea_till.view_avea_account_form", raise_if_not_found=False
            )
            if view:
                return view.id
        return super().get_formview_id(access_uid=access_uid)

    def get_formview_action(self, access_uid=None):
        action = super().get_formview_action(access_uid=access_uid)
        user = self.env.user
        if access_uid:
            user = self.env["res.users"].browse(access_uid)
        if len(self) == 1 and self.with_user(user)._avea_use_workspace_form(user):
            view = self.env.ref(
                "avea_till.view_avea_account_form", raise_if_not_found=False
            )
            if view:
                action["views"] = [(view.id, "form")]
                ctx = dict(action.get("context") or {})
                ctx["avea_account_workspace"] = True
                action["context"] = ctx
        return action
