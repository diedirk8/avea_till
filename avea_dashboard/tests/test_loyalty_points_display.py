# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.avea_till.models.till.loyalty_display import format_loyalty_points_display


@tagged("post_install", "-at_install", "avea_till")
class TestLoyaltyPointsDisplay(TransactionCase):
    def test_whole_numbers_drop_decimals(self):
        self.assertEqual(format_loyalty_points_display(120.0), "120")
        self.assertEqual(format_loyalty_points_display(120), "120")

    def test_float_artifacts_round_to_two_decimals(self):
        self.assertEqual(format_loyalty_points_display(38.44488877001), "38.44")
        self.assertEqual(format_loyalty_points_display(38.445), "38.45")

    def test_zero_and_invalid(self):
        self.assertEqual(format_loyalty_points_display(0), "0")
        self.assertEqual(format_loyalty_points_display(None), "0")
        self.assertEqual(format_loyalty_points_display("not-a-number"), "0")

    def test_receipt_email_uses_native_card_formatter(self):
        program = self.env["loyalty.program"].create(
            {
                "name": "Display Test",
                "program_type": "loyalty",
                "trigger": "auto",
                "applies_on": "both",
            }
        )
        card = self.env["loyalty.card"].create(
            {
                "program_id": program.id,
                "partner_id": self.env["res.partner"].create({"name": "Loyalty Display"}).id,
                "points": 38.44488877001,
            }
        )
        self.assertIn("38.44", card._format_points(card.points))
