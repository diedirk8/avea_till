# -*- coding: utf-8 -*-
"""Avea product navigation structure (user-facing, not Odoo menu tree)."""

from odoo import models

# Role rank for filtering sections (higher includes lower).
_AVEA_ROLE_RANK = {
    "cashier": 1,
    "manager": 2,
    "owner": 3,
}


class AveaNavMixin(models.AbstractModel):
    _name = "avea.nav.mixin"
    _description = "Avea navigation structure"

    def _avea_nav_role(self):
        self.ensure_one()
        if self.has_group("avea_till.group_avea_owner"):
            return "owner"
        if self.has_group("avea_till.group_avea_manager"):
            return "manager"
        if self.has_group("avea_till.group_avea_cashier"):
            return "cashier"
        return False

    def _avea_nav_home_definition(self):
        """Standalone home destination (not grouped with Business)."""
        self.ensure_one()
        role = self._avea_nav_role()
        if role == "cashier":
            return {
                "label": "Today's Session",
                "menu_xmlid": "avea_till.menu_avea_session_dashboard",
            }
        return {
            "label": "Home",
            "menu_xmlid": "avea_till.menu_avea_business_overview",
            "min_role": "manager",
        }

    def _avea_nav_sections_definition(self):
        """Primary sidebar groups (settings is separate)."""
        return [
            {
                "id": "business",
                "label": "Business",
                "min_role": "manager",
                "items": [
                    {
                        "label": "Performance",
                        "menu_xmlid": "avea_till.menu_avea_business_performance",
                    },
                    {
                        "label": "Transactions",
                        "menu_xmlid": "avea_till.menu_avea_business_transactions",
                    },
                ],
            },
            {
                "id": "sessions",
                "label": "Sessions",
                "min_role": "manager",
                "items": [
                    {
                        "label": "Session Dashboard",
                        "menu_xmlid": "avea_till.menu_avea_session_dashboard",
                    },
                    {
                        "label": "Sales Ledger",
                        "menu_xmlid": "avea_till.menu_avea_sales_ledger",
                    },
                ],
            },
            {
                "id": "stock",
                "label": "Stock",
                "min_role": "manager",
                "items": [
                    {
                        "label": "Products",
                        "menu_xmlid": "avea_till.menu_avea_stock_products",
                    },
                    {
                        "label": "Receive Stock",
                        "menu_xmlid": "avea_till.menu_avea_stock_receive",
                    },
                    {
                        "label": "Stock Take",
                        "menu_xmlid": "avea_till.menu_avea_stock_count",
                    },
                    {
                        "label": "Return Stock",
                        "menu_xmlid": "avea_till.menu_avea_stock_return",
                    },
                ],
            },
            {
                "id": "customers",
                "label": "Customers",
                "min_role": "manager",
                "items": [
                    {
                        "label": "Promotions",
                        "menu_xmlid": "avea_till.menu_avea_promotion",
                    },
                    {
                        "id": "store_credit",
                        "label": "Store Credit",
                        "items": [
                            {
                                "label": "Credit Dashboard",
                                "menu_xmlid": "avea_till.menu_avea_credit_dashboard",
                            },
                            {
                                "label": "Customer Ledger",
                                "menu_xmlid": "avea_till.menu_avea_credit_ledger",
                            },
                            {
                                "label": "Issue Credit",
                                "menu_xmlid": "avea_till.menu_avea_credit_issue",
                            },
                        ],
                    },
                    {
                        "id": "credit_reports",
                        "label": "Reports",
                        "items": [
                            {
                                "label": "Statements",
                                "menu_xmlid": "avea_till.menu_avea_credit_report_statement",
                            },
                            {
                                "label": "Outstanding Credit",
                                "menu_xmlid": "avea_till.menu_avea_credit_report_outstanding",
                            },
                            {
                                "label": "Credit Activity",
                                "menu_xmlid": "avea_till.menu_avea_credit_report_activity",
                            },
                        ],
                    },
                ],
            },
            {
                "id": "money",
                "label": "Money",
                "min_role": "manager",
                "items": [
                    {
                        "label": "Cash Ups",
                        "menu_xmlid": "avea_till.menu_avea_cash_up",
                    },
                    {
                        "label": "Account Balances",
                        "menu_xmlid": "avea_till.menu_avea_operations_balances",
                    },
                    {
                        "id": "record",
                        "label": "Record",
                        "items": [
                            {
                                "label": "Add Expense",
                                "menu_xmlid": "avea_till.menu_avea_operations_expense",
                            },
                            {
                                "label": "Transfer Money",
                                "menu_xmlid": "avea_till.menu_avea_operations_transfer",
                            },
                            {
                                "label": "Withdraw Cash",
                                "menu_xmlid": "avea_till.menu_avea_operations_withdraw_cash",
                            },
                            {
                                "label": "Manual Entry",
                                "menu_xmlid": "avea_till.menu_avea_operations_manual_journal",
                            },
                        ],
                    },
                ],
            },
        ]

    def _avea_nav_settings_definition(self):
        return {
            "label": "Settings",
            "min_role": "manager",
            "items": [
                {
                    "label": "Email Receipts",
                    "menu_xmlid": "avea_till.menu_avea_settings_email",
                },
                {
                    "label": "Printed Receipts",
                    "menu_xmlid": "avea_till.menu_avea_settings_printed",
                },
            ],
        }

    def _avea_nav_sell_action(self):
        return {
            "label": "Sell",
            "menu_xmlid": "avea_till.menu_avea_pos_sell",
        }

    def _avea_nav_menu_visible(self, menu_xmlid):
        menu = self.env.ref(menu_xmlid, raise_if_not_found=False)
        if not menu or not menu.action:
            return False
        visible_ids = set(
            self.env["ir.ui.menu"]
            .with_user(self)
            ._visible_menu_ids(debug=False)
        )
        return menu.id in visible_ids

    def _avea_nav_filter_items(self, items, role_rank):
        filtered = []
        for item in items:
            item_rank = _AVEA_ROLE_RANK.get(item.get("min_role", "cashier"), 1)
            if role_rank < item_rank:
                continue
            nested = item.get("items")
            if nested:
                children = self._avea_nav_filter_items(nested, role_rank)
                if not children:
                    continue
                filtered.append(
                    {
                        "id": item.get("id"),
                        "label": item["label"],
                        "items": children,
                    }
                )
                continue
            if not self._avea_nav_menu_visible(item["menu_xmlid"]):
                continue
            filtered.append(
                {
                    "label": item["label"],
                    "menu_xmlid": item["menu_xmlid"],
                }
            )
        return filtered

    def _avea_nav_filter_home(self, role_rank):
        home = self._avea_nav_home_definition()
        home_rank = _AVEA_ROLE_RANK.get(home.get("min_role", "cashier"), 1)
        if role_rank < home_rank:
            return False
        if not self._avea_nav_menu_visible(home["menu_xmlid"]):
            return False
        return {"label": home["label"], "menu_xmlid": home["menu_xmlid"]}

    def _avea_nav_filter_settings(self, role_rank):
        settings = self._avea_nav_settings_definition()
        settings_rank = _AVEA_ROLE_RANK.get(settings.get("min_role", "cashier"), 1)
        if role_rank < settings_rank:
            return False
        items = self._avea_nav_filter_items(settings.get("items", []), role_rank)
        if not items:
            return False
        return {"label": settings["label"], "items": items}

    def _avea_nav_structure(self):
        """Navigation payload for the web client."""
        self.ensure_one()
        role = self._avea_nav_role()
        if not role:
            return False
        role_rank = _AVEA_ROLE_RANK[role]
        sections = []
        for section in self._avea_nav_sections_definition():
            section_rank = _AVEA_ROLE_RANK.get(section.get("min_role", "cashier"), 1)
            if role_rank < section_rank:
                continue
            items = self._avea_nav_filter_items(section.get("items", []), role_rank)
            if not items:
                continue
            sections.append(
                {
                    "id": section["id"],
                    "label": section["label"],
                    "items": items,
                }
            )
        sell = self._avea_nav_sell_action()
        if not self._avea_nav_menu_visible(sell["menu_xmlid"]):
            sell = False
        return {
            "role": role,
            "sell": sell,
            "home": self._avea_nav_filter_home(role_rank),
            "sections": sections,
            "settings": self._avea_nav_filter_settings(role_rank),
        }
