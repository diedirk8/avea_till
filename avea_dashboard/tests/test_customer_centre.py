# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaCustomerCentre(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Avea Customer Manager",
                "login": "avea_customer_mgr@dev.local",
                "email": "avea_customer_mgr@dev.local",
                "company_id": cls.env.company.id,
                "company_ids": [Command.set([cls.env.company.id])],
                "group_ids": [
                    Command.set([cls.env.ref("avea_till.group_avea_manager").id])
                ],
            }
        )

    def test_create_from_workspace_sets_customer_rank(self):
        partner = (
            self.env["res.partner"]
            .with_context(avea_customer_workspace=True)
            .create({"name": "Avea Centre Customer"})
        )
        self.assertGreater(partner.customer_rank, 0)

    def test_sales_history_action_filters_partner(self):
        partner = self.env["res.partner"].create(
            {"name": "Sales History Customer", "customer_rank": 1}
        )
        action = partner.action_avea_open_sales_history()
        self.assertEqual(action["res_model"], "pos.order")
        self.assertIn(("partner_id", "=", partner.id), action["domain"])

    def test_sales_total_is_stored_for_list_sort(self):
        partner = self.env["res.partner"].create(
            {"name": "Sortable Customer", "customer_rank": 1}
        )
        field = self.env["res.partner"]._fields["avea_pos_sales_total"]
        self.assertTrue(field.store)
        self.assertEqual(partner.avea_pos_sales_total, 0.0)
        self.assertTrue(self.env["res.partner"]._fields["avea_last_visit"].store)
        self.assertFalse(partner.avea_last_visit)

    def test_lapsed_domain_uses_visit_pattern(self):
        domain = self.env["res.partner"].avea_customer_lapsed_domain()
        self.assertEqual(domain, [("avea_visit_pattern_lapsed", "=", True)])

    def test_visit_rhythm_label_uses_weeks(self):
        partner = self.env["res.partner"].new({"avea_typical_visit_days": 21})
        partner._compute_avea_visit_rhythm_label()
        self.assertIn("3", partner.avea_visit_rhythm_label)

    def test_visit_rhythm_label_hides_short_patterns(self):
        partner = self.env["res.partner"].new({"avea_typical_visit_days": 7})
        partner._compute_avea_visit_rhythm_label()
        self.assertFalse(partner.avea_visit_rhythm_label)

    def test_meaningful_visit_gaps_ignore_short_returns(self):
        Partner = self.env["res.partner"]
        settings = Partner._avea_visit_pattern_settings()
        from datetime import date, timedelta

        base = date(2026, 1, 1)
        burst_dates = [
            base,
            base + timedelta(days=1),
            base + timedelta(days=35),
            base + timedelta(days=70),
        ]
        gaps = Partner._avea_meaningful_visit_gaps(burst_dates, settings)
        self.assertEqual(gaps, [34, 35])

    def test_visit_pattern_needs_enough_history(self):
        partner = self.env["res.partner"].create(
            {"name": "Sparse Shopper", "customer_rank": 1}
        )
        partner._compute_avea_visit_pattern()
        self.assertFalse(partner.avea_visit_pattern_lapsed)
        self.assertEqual(partner.avea_typical_visit_days, 0)

    def test_duplicate_candidates_share_email(self):
        first = self.env["res.partner"].create(
            {
                "name": "Dupe Alpha",
                "customer_rank": 1,
                "email": "dupe.shared@example.com",
            }
        )
        second = self.env["res.partner"].create(
            {
                "name": "Dupe Beta",
                "customer_rank": 1,
                "email": "dupe.shared@example.com",
            }
        )
        lone = self.env["res.partner"].create(
            {"name": "Unique Shopper", "customer_rank": 1, "email": "solo@example.com"}
        )
        ids = self.env["res.partner"]._avea_duplicate_customer_candidate_ids()
        self.assertIn(first.id, ids)
        self.assertIn(second.id, ids)
        self.assertNotIn(lone.id, ids)

    def test_merge_action_opens_wizard(self):
        partners = self.env["res.partner"].create(
            [
                {"name": "Merge A", "customer_rank": 1},
                {"name": "Merge B", "customer_rank": 1},
            ]
        )
        action = partners.action_avea_merge_customers()
        self.assertEqual(
            action["res_model"], "base.partner.merge.automatic.wizard"
        )
        self.assertEqual(
            set(action["context"]["active_ids"]), set(partners.ids)
        )

    def test_product_shell_uses_avea_customer_form(self):
        partner = self.env["res.partner"].create(
            {"name": "Shell Customer", "customer_rank": 1}
        )
        view_id = partner.with_user(self.manager).get_formview_id()
        expected = self.env.ref("avea_till.view_avea_customer_form").id
        self.assertEqual(view_id, expected)
