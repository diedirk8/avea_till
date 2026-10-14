# -*- coding: utf-8 -*-
from datetime import date

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_till")
class TestAveaPromotionSchedule(TransactionCase):
    def _promotion(self, **kwargs):
        values = {
            "name": "Schedule test",
            "deal_type": "percent_off",
            "discount_percent": 10.0,
        }
        values.update(kwargs)
        return self.env["avea.promotion"].create(values)

    def test_schedule_status_expired_when_past_end_date(self):
        promo = self._promotion(
            active=True,
            date_from="2026-09-01",
            date_to="2026-09-30",
        )
        self.assertEqual(promo._avea_schedule_status_for_date(date(2026, 10, 6)), "expired")

    def test_schedule_status_running_inside_window(self):
        promo = self._promotion(
            active=True,
            date_from="2026-09-01",
            date_to="2026-10-30",
        )
        self.assertEqual(promo._avea_schedule_status_for_date(date(2026, 10, 6)), "running")

    def test_schedule_status_scheduled_before_start(self):
        promo = self._promotion(
            active=True,
            date_from="2026-11-01",
            date_to="2026-11-30",
        )
        self.assertEqual(promo._avea_schedule_status_for_date(date(2026, 10, 6)), "scheduled")

    def test_schedule_status_inactive_when_disabled(self):
        promo = self._promotion(
            active=False,
            date_from="2026-09-01",
            date_to="2026-10-30",
        )
        self.assertEqual(promo.schedule_status, "inactive")
