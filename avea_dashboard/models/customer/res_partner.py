# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import timedelta
from statistics import median

from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    avea_pos_order_ids = fields.One2many(
        "pos.order",
        "partner_id",
        string="POS sales",
    )
    avea_pos_order_count = fields.Integer(
        string="POS sales count",
        compute="_compute_avea_customer_sales_stats",
        store=True,
    )
    avea_pos_sales_currency_id = fields.Many2one(
        "res.currency",
        string="Sales total currency",
        compute="_compute_avea_customer_sales_stats",
        store=True,
    )
    avea_pos_sales_total = fields.Monetary(
        string="POS sales total",
        compute="_compute_avea_customer_sales_stats",
        store=True,
        currency_field="avea_pos_sales_currency_id",
    )
    avea_last_visit = fields.Datetime(
        string="Last visit",
        compute="_compute_avea_customer_sales_stats",
        store=True,
        help="Date and time of the customer's most recent paid POS sale.",
    )
    avea_days_since_visit = fields.Integer(
        string="Days since visit",
        compute="_compute_avea_days_since_visit",
        store=True,
        help="Calendar days since the customer's last paid POS sale.",
    )
    avea_typical_visit_days = fields.Integer(
        string="Typical days between visits",
        compute="_compute_avea_visit_pattern",
        store=True,
        help="Median gap between paid POS visits in the recent history window.",
    )
    avea_visit_overdue_days = fields.Integer(
        string="Days past usual rhythm",
        compute="_compute_avea_visit_pattern",
        store=True,
        help="How many days beyond the customer's usual visit interval they are now.",
    )
    avea_visit_pattern_lapsed = fields.Boolean(
        string="Stopped usual visit pattern",
        compute="_compute_avea_visit_pattern",
        store=True,
        help="True when absence is much longer than this customer's normal visit rhythm.",
    )
    avea_visit_rhythm_label = fields.Char(
        string="Visit rhythm",
        compute="_compute_avea_visit_rhythm_label",
        store=False,
    )
    avea_usual_buys_category = fields.Char(
        string="Usually buys",
        compute="_compute_avea_usual_buys_category",
        store=True,
        help="Product category this customer purchases most often at POS (recent history).",
    )
    avea_usual_visit_spend = fields.Monetary(
        string="Usual spend per visit",
        compute="_compute_avea_usual_visit_spend",
        store=True,
        currency_field="avea_pos_sales_currency_id",
        help="Median amount spent on each paid POS visit in recent history.",
    )

    @api.depends(
        "company_id",
        "company_id.currency_id",
        "avea_pos_order_ids.amount_total",
        "avea_pos_order_ids.date_order",
        "avea_pos_order_ids.state",
    )
    def _compute_avea_customer_sales_stats(self):
        paid_states = self.env["pos.session"]._avea_paid_order_states()
        stats = {
            partner_id: {"count": 0, "total": 0.0, "last_visit": False}
            for partner_id in self.ids
        }
        if self.ids and paid_states:
            groups = self.env["pos.order"].read_group(
                [
                    ("partner_id", "in", self.ids),
                    ("state", "in", paid_states),
                ],
                ["amount_total:sum", "date_order:max"],
                ["partner_id"],
            )
            for row in groups:
                partner_id = row["partner_id"][0]
                stats[partner_id] = {
                    "count": row.get("partner_id_count", 0),
                    "total": row.get("amount_total", 0.0) or 0.0,
                    "last_visit": row.get("date_order") or False,
                }
        for partner in self:
            row = stats.get(
                partner.id, {"count": 0, "total": 0.0, "last_visit": False}
            )
            currency = partner.company_id.currency_id or self.env.company.currency_id
            partner.avea_pos_order_count = row["count"]
            partner.avea_pos_sales_total = row["total"]
            partner.avea_pos_sales_currency_id = currency
            partner.avea_last_visit = row["last_visit"]

    @api.depends("avea_typical_visit_days")
    def _compute_avea_visit_rhythm_label(self):
        for partner in self:
            partner.avea_visit_rhythm_label = partner._avea_format_visit_rhythm_days(
                partner.avea_typical_visit_days
            )

    @api.depends("avea_pos_order_count", "avea_last_visit")
    def _compute_avea_usual_visit_spend(self):
        paid_states = tuple(self.env["pos.session"]._avea_paid_order_states())
        settings = self._avea_visit_pattern_settings()
        lookback_start = fields.Datetime.now() - timedelta(
            days=settings["lookback_months"] * 31
        )
        spend_by_partner = {partner_id: 0.0 for partner_id in self.ids}
        if self.ids and paid_states:
            rows = self.env["pos.order"].search_read(
                [
                    ("partner_id", "in", self.ids),
                    ("state", "in", paid_states),
                    ("date_order", ">=", lookback_start),
                ],
                ["partner_id", "amount_total"],
            )
            amounts = defaultdict(list)
            for row in rows:
                amounts[row["partner_id"][0]].append(row["amount_total"] or 0.0)
            for partner_id, values in amounts.items():
                if values:
                    spend_by_partner[partner_id] = float(median(values))
        for partner in self:
            partner.avea_usual_visit_spend = spend_by_partner.get(partner.id, 0.0)

    @api.depends("avea_pos_order_count", "avea_last_visit")
    def _compute_avea_usual_buys_category(self):
        paid_states = tuple(self.env["pos.session"]._avea_paid_order_states())
        settings = self._avea_visit_pattern_settings()
        lookback_start = fields.Datetime.now() - timedelta(
            days=settings["lookback_months"] * 31
        )
        category_by_partner = {partner_id: "" for partner_id in self.ids}
        if self.ids and paid_states:
            self.env.cr.execute(
                """
                SELECT
                    po.partner_id,
                    pt.categ_id,
                    SUM(pol.qty) AS total_qty
                FROM pos_order_line pol
                INNER JOIN pos_order po ON po.id = pol.order_id
                INNER JOIN product_product pp ON pp.id = pol.product_id
                INNER JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE po.partner_id IN %s
                  AND po.state IN %s
                  AND po.date_order >= %s
                  AND pol.qty > 0
                GROUP BY po.partner_id, pt.categ_id
                """,
                (tuple(self.ids), paid_states, lookback_start),
            )
            best = {}
            for partner_id, categ_id, total_qty in self.env.cr.fetchall():
                current = best.get(partner_id)
                if not current or total_qty > current[0]:
                    best[partner_id] = (total_qty, categ_id)
            categ_ids = [row[1] for row in best.values() if row[1]]
            categ_names = {
                categ.id: categ.display_name
                for categ in self.env["product.category"].browse(categ_ids)
            }
            for partner_id, (total_qty, categ_id) in best.items():
                if categ_id and categ_names.get(categ_id):
                    category_by_partner[partner_id] = categ_names[categ_id]
                elif categ_id:
                    category_by_partner[partner_id] = _("Uncategorised")
        for partner in self:
            partner.avea_usual_buys_category = category_by_partner.get(partner.id, "")

    @api.depends("avea_last_visit")
    def _compute_avea_days_since_visit(self):
        today = fields.Date.context_today(self)
        for partner in self:
            if not partner.avea_last_visit:
                partner.avea_days_since_visit = 0
                continue
            last_day = fields.Datetime.to_datetime(partner.avea_last_visit).date()
            partner.avea_days_since_visit = (today - last_day).days

    @api.model
    def _avea_visit_pattern_settings(self):
        icp = self.env["ir.config_parameter"].sudo()

        def _int_param(key, default):
            return max(int(icp.get_param(key, str(default))), 1)

        return {
            "min_orders": max(
                _int_param("avea_till.customer_pattern_min_orders", 3), 3
            ),
            "overdue_factor": max(
                float(icp.get_param("avea_till.customer_pattern_overdue_factor", "2.5")),
                1.1,
            ),
            "min_absence_days": _int_param(
                "avea_till.customer_pattern_min_absence_days", 14
            ),
            "lookback_months": max(
                _int_param("avea_till.customer_pattern_lookback_months", 18), 6
            ),
            "min_gap_days": max(
                _int_param("avea_till.customer_pattern_min_gap_days", 10), 3
            ),
            "max_gaps": 8,
            "min_rhythm_gaps": 2,
        }

    @api.model
    def _avea_meaningful_visit_gaps(self, visit_dates, settings):
        """Gaps between visit days, ignoring short returns (same shopping burst)."""
        dates = sorted(set(visit_dates))
        if len(dates) < 2:
            return []
        gaps = [
            (dates[index + 1] - dates[index]).days
            for index in range(len(dates) - 1)
        ]
        min_gap = settings["min_gap_days"]
        meaningful = [gap for gap in gaps if gap >= min_gap]
        if len(meaningful) >= settings["min_rhythm_gaps"]:
            return meaningful[-settings["max_gaps"] :]
        return []

    @api.model
    def _avea_format_visit_rhythm_days(self, days):
        """Human-readable rhythm; omit noisy sub-two-week patterns."""
        if not days or days < 14:
            return ""
        if days >= 75:
            months = max(1, int(round(days / 30.0)))
            return _("About every %(count)s months", count=months)
        weeks = max(2, int(round(days / 7.0)))
        return _("About every %(count)s weeks", count=weeks)

    @api.depends(
        "avea_pos_order_count",
        "avea_last_visit",
        "avea_days_since_visit",
    )
    def _compute_avea_visit_pattern(self):
        settings = self._avea_visit_pattern_settings()
        paid_states = self.env["pos.session"]._avea_paid_order_states()
        visit_dates = defaultdict(list)
        if self.ids and paid_states:
            lookback_start = fields.Datetime.now() - timedelta(
                days=settings["lookback_months"] * 31
            )
            rows = self.env["pos.order"].search_read(
                [
                    ("partner_id", "in", self.ids),
                    ("state", "in", paid_states),
                    ("date_order", ">=", lookback_start),
                ],
                ["partner_id", "date_order"],
                order="date_order asc",
            )
            for row in rows:
                partner_id = row["partner_id"][0]
                visit_day = fields.Datetime.to_datetime(row["date_order"]).date()
                visit_dates[partner_id].append(visit_day)

        for partner in self:
            partner.avea_typical_visit_days = 0
            partner.avea_visit_overdue_days = 0
            partner.avea_visit_pattern_lapsed = False

            dates = visit_dates.get(partner.id, [])
            if len(set(dates)) < settings["min_orders"]:
                continue

            recent_gaps = partner._avea_meaningful_visit_gaps(dates, settings)
            if not recent_gaps:
                continue

            typical = int(median(recent_gaps))
            if typical < settings["min_gap_days"]:
                continue
            partner.avea_typical_visit_days = typical

            absence = partner.avea_days_since_visit
            if absence < settings["min_absence_days"]:
                continue

            overdue_limit = typical * settings["overdue_factor"]
            if absence > overdue_limit:
                partner.avea_visit_pattern_lapsed = True
                partner.avea_visit_overdue_days = max(absence - typical, 0)

    @api.model
    def avea_customer_lapsed_domain(self):
        """Customers to follow up — overdue compared to their own visit rhythm."""
        return [("avea_visit_pattern_lapsed", "=", True)]

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get("avea_customer_workspace"):
            for vals in vals_list:
                vals.setdefault("customer_rank", 1)
        return super().create(vals_list)

    def _avea_use_customer_workspace_form(self):
        self.ensure_one()
        return bool(self.customer_rank)

    def _avea_paid_pos_order_domain(self):
        self.ensure_one()
        return [
            ("partner_id", "=", self.id),
            ("state", "in", self.env["pos.session"]._avea_paid_order_states()),
        ]

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

    def action_avea_open_sales_history(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Sales history"),
            "res_model": "pos.order",
            "view_mode": "list,form",
            "views": [
                (
                    self.env.ref("avea_till.view_avea_customer_pos_order_list").id,
                    "list",
                ),
                (False, "form"),
            ],
            "domain": self._avea_paid_pos_order_domain(),
            "context": {"default_partner_id": self.id},
            "target": "current",
        }

    def action_avea_open_credit_dashboard(self):
        return self.env["avea.credit.dashboard"].action_open_credit_dashboard()

    def action_avea_open_credit_statement(self):
        self.ensure_one()
        action = self.env["avea.credit.statement.wizard"].action_open_wizard()
        action["context"] = dict(
            action.get("context") or {},
            default_partner_id=self.id,
        )
        return action

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
