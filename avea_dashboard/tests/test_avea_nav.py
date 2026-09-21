# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaNav(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = cls._create_user("owner", "avea_till.group_avea_owner")
        cls.manager = cls._create_user("manager", "avea_till.group_avea_manager")
        cls.cashier = cls._create_user("cashier", "avea_till.group_avea_cashier")

    @classmethod
    def _create_user(cls, role, xmlid):
        return cls.env["res.users"].create(
            {
                "name": "Avea Nav %s" % role.title(),
                "login": "avea_nav_%s@dev.local" % role,
                "email": "avea_nav_%s@dev.local" % role,
                "company_id": cls.env.company.id,
                "company_ids": [Command.set([cls.env.company.id])],
                "group_ids": [Command.set([cls.env.ref(xmlid).id])],
            }
        )

    def _section_ids(self, user):
        nav = user._avea_nav_structure()
        self.assertTrue(nav)
        return [section["id"] for section in nav["sections"]]

    def test_cashier_nav_is_minimal(self):
        nav = self.cashier._avea_nav_structure()
        self.assertEqual(nav["role"], "cashier")
        self.assertEqual(nav["sections"], [])
        self.assertTrue(nav["home"])
        self.assertEqual(nav["home"]["label"], "Today's Session")
        self.assertTrue(nav["sell"])
        self.assertFalse(nav["settings"])

    def test_manager_sees_operational_sections_without_settings(self):
        sections = self._section_ids(self.manager)
        self.assertEqual(
            sections,
            ["business", "sessions", "stock", "customers", "money"],
        )
        nav = self.manager._avea_nav_structure()
        self.assertTrue(nav["home"])
        self.assertEqual(nav["home"]["label"], "Home")
        self.assertTrue(nav["settings"])
        self.assertEqual(nav["settings"]["label"], "Settings")

    def test_owner_matches_manager_nav(self):
        owner_nav = self.owner._avea_nav_structure()
        manager_nav = self.manager._avea_nav_structure()
        self.assertEqual(
            self._section_ids(self.owner),
            self._section_ids(self.manager),
        )
        self.assertEqual(owner_nav["home"], manager_nav["home"])
        self.assertEqual(owner_nav["settings"], manager_nav["settings"])

    def test_business_section_excludes_overview(self):
        nav = self.manager._avea_nav_structure()
        business = next(s for s in nav["sections"] if s["id"] == "business")
        labels = {item["label"] for item in business["items"]}
        self.assertEqual(labels, {"Performance", "Transactions"})

    def test_customers_and_money_use_nested_groups(self):
        nav = self.manager._avea_nav_structure()
        customers = next(s for s in nav["sections"] if s["id"] == "customers")
        self.assertEqual(customers["items"][0]["label"], "Promotions")
        store_credit = customers["items"][1]
        self.assertEqual(store_credit["label"], "Store Credit")
        self.assertIn("items", store_credit)

        money = next(s for s in nav["sections"] if s["id"] == "money")
        record_group = money["items"][-1]
        self.assertEqual(record_group["label"], "Record")
        record_labels = {item["label"] for item in record_group["items"]}
        self.assertIn("Manual Entry", record_labels)
        self.assertIn("Add Expense", record_labels)
