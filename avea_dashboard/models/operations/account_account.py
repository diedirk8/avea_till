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

AVEA_ASSET_TYPES = (
    "asset_receivable",
    "asset_cash",
    "asset_current",
    "asset_non_current",
    "asset_fixed",
    "asset_prepayments",
)

AVEA_ASSET_KIND_SELECTION = [
    ("asset_cash", "Cash"),
    ("asset_current", "Current asset"),
    ("asset_receivable", "Receivable"),
    ("asset_prepayments", "Prepayment"),
    ("asset_fixed", "Fixed asset"),
    ("asset_non_current", "Non-current asset"),
]

_AVEA_KIND_ALL = dict(AVEA_KIND_SELECTION + AVEA_ASSET_KIND_SELECTION)

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
        selection=AVEA_KIND_SELECTION + AVEA_ASSET_KIND_SELECTION,
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
    avea_balance = fields.Monetary(
        string="Balance",
        compute="_compute_avea_balance",
        currency_field="avea_currency_id",
        help="Current posted balance on the account.",
    )
    avea_is_asset_account = fields.Boolean(compute="_compute_avea_account_flags")
    avea_is_pnl_account = fields.Boolean(compute="_compute_avea_account_flags")

    @api.depends("account_type")
    def _compute_avea_kind(self):
        for account in self:
            account.avea_kind = (
                account.account_type if account.account_type in _AVEA_KIND_ALL else False
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

    @api.depends_context("company")
    def _compute_avea_balance(self):
        currency = self.env.company.currency_id
        for account in self:
            account.avea_currency_id = currency
            if not account.id:
                account.avea_balance = 0.0
                continue
            account.avea_balance = account.sudo().current_balance

    @api.depends("account_type")
    def _compute_avea_account_flags(self):
        for account in self:
            account.avea_is_asset_account = account.account_type in AVEA_ASSET_TYPES
            account.avea_is_pnl_account = account.account_type in AVEA_ACCOUNT_TYPES

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if not self.env.context.get("avea_account_workspace"):
            return values
        kind = (
            self.env.context.get("default_avea_kind")
            or values.get("avea_kind")
            or values.get("account_type")
            or "expense"
        )
        if kind in _AVEA_KIND_ALL:
            values.setdefault("avea_kind", kind)
            values.setdefault("account_type", kind)
        else:
            values.setdefault("account_type", "expense")
        want_code = not fields_list or "code" in fields_list
        if want_code and not values.get("code"):
            account_type = values.get("account_type") or kind
            if account_type in AVEA_ACCOUNT_TYPES or account_type in AVEA_ASSET_TYPES:
                values["code"] = self._avea_next_account_code(account_type)
        return values

    @api.onchange("avea_kind")
    def _onchange_avea_kind_suggest_code(self):
        if not self.avea_kind:
            return
        self.account_type = self.avea_kind
        if not self._origin.id:
            self.code = self._avea_next_account_code(self.avea_kind)

    @api.model
    def avea_suggest_account_code(self, account_type):
        """Return the next chart code for a kind (used by the Avea account form)."""
        if account_type not in _AVEA_KIND_ALL:
            return False
        return self._avea_next_account_code(account_type)

    @api.model
    def _avea_require_manager(self):
        if self.env.su:
            return
        if not self.env.user.has_group("avea_till.group_avea_manager"):
            raise AccessError(_("Only a manager can add or change accounts."))

    @api.model
    def _avea_is_non_advisor_manager(self):
        """Avea manager without Accounting/Advisor — P&L accounts only."""
        if self.env.su:
            return False
        user = self.env.user
        if user.has_group("account.group_account_manager"):
            return False
        return user.has_group("avea_till.group_avea_manager")

    def _avea_assert_pnl_records(self):
        if any(account.account_type not in AVEA_ACCOUNT_TYPES for account in self):
            raise AccessError(
                _(
                    "Cash, bank, and other bookkeeping accounts cannot be "
                    "changed here. Use Account Balances for those."
                )
            )

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
        if self.account_type in AVEA_ASSET_TYPES and self.env.context.get(
            "avea_asset_workspace"
        ):
            return True
        return bool(self.env.context.get("avea_account_workspace"))

    @api.model
    def _avea_should_prepare_vals(self):
        if self.env.context.get("avea_account_creating"):
            return False
        if self.env.context.get("avea_account_workspace"):
            return True
        return self._avea_is_non_advisor_manager()

    @api.model_create_multi
    def create(self, vals_list):
        if self._avea_should_prepare_vals():
            self._avea_require_manager()
            prepared = [self._avea_prepare_account_vals(dict(vals)) for vals in vals_list]
            creator = self.with_company(self.env.company).with_context(
                avea_account_creating=True
            )
            # OWL checks ir.model.access before this method. Avea managers get
            # that ACL, but Odoo's account create still expects Advisor internals.
            if self._avea_is_non_advisor_manager():
                creator = creator.sudo()
            return super(AccountAccount, creator).create(prepared)
        return super().create(vals_list)

    def write(self, vals):
        restricted = self._avea_is_non_advisor_manager()
        workspace = bool(self.env.context.get("avea_account_workspace"))
        if workspace or restricted:
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
            if restricted and user_keys:
                self._avea_assert_pnl_records()
            if "account_type" in vals:
                self._avea_validate_write(vals)
            if restricted and user_keys and not self.env.su:
                return super(AccountAccount, self.sudo()).write(vals)
        return super().write(vals)

    def unlink(self):
        restricted = self._avea_is_non_advisor_manager()
        if self.env.context.get("avea_account_workspace") or restricted:
            self._avea_require_manager()
            if restricted:
                self._avea_assert_pnl_records()
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
