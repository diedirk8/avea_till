"""Shared reporting-period helpers for Avea dashboards and drill-down reports."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.tools.misc import format_date

from .reporting_period import (
    PERIOD_CUSTOM,
    PERIOD_TODAY,
    normalize_period_key,
    resolve_reporting_period,
)


class AveaReportingWorkspaceMixin(models.AbstractModel):
    _name = "avea.reporting.workspace.mixin"
    _description = "Avea Reporting Workspace Helpers"

    def _reporting_timezone(self):
        tzname = self.env.user.tz or self.env.context.get("tz") or "UTC"
        try:
            return ZoneInfo(tzname)
        except Exception:
            return ZoneInfo("UTC")

    def _reporting_utc_bounds(self, day_from, day_to):
        tz = self._reporting_timezone()
        start_local = datetime.combine(day_from, time.min, tzinfo=tz)
        end_local = datetime.combine(
            day_to,
            time.max.replace(microsecond=0),
            tzinfo=tz,
        )
        return (
            start_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
            end_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
        )

    @api.model
    def _reporting_normalize_custom_dates(self, date_from=None, date_to=None):
        today = fields.Date.context_today(self)
        start = date_from or today.replace(day=1)
        end = date_to or today
        if start > end:
            start, end = end, start
        return start, end

    def _reporting_period_windows(self, period, date_from=None, date_to=None):
        reporting = resolve_reporting_period(
            period=period,
            today=fields.Date.context_today(self),
            custom_from=date_from,
            custom_to=date_to,
        )
        current = reporting.current
        previous = reporting.comparison
        return {
            "display_current": current,
            "data_current": current,
            "display_previous": previous,
            "data_previous": previous,
            "labels": (_(reporting.label), _(reporting.comparison_label)),
            "show_through_today": False,
            "today": reporting.today,
            "elapsed_days": reporting.elapsed_days,
            "key": reporting.key,
            "period_label": reporting.label,
            "comparison_label": reporting.comparison_label,
        }

    def _reporting_format_day_range(self, day_from, day_to):
        if day_from == day_to:
            return format_date(self.env, day_from, date_format="d MMMM y")
        end = format_date(self.env, day_to, date_format="d MMMM y")
        same_month = day_from.month == day_to.month and day_from.year == day_to.year
        if same_month:
            start_day = format_date(self.env, day_from, date_format="d")
            return f"{start_day}–{end}"
        if day_from.year == day_to.year:
            start = format_date(self.env, day_from, date_format="d MMMM")
            return f"{start}–{end}"
        start = format_date(self.env, day_from, date_format="d MMMM y")
        return f"{start}–{end}"

    def _reporting_paid_orders_between(self, day_from, day_to):
        start, end = self._reporting_utc_bounds(day_from, day_to)
        Session = self.env["pos.session"]
        return self.env["pos.order"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("state", "in", Session._avea_paid_order_states()),
                ("date_order", ">=", start),
                ("date_order", "<=", end),
            ]
        )

    def _reporting_paid_orders_for_period(self, period=None, date_from=None, date_to=None):
        period = normalize_period_key(period or PERIOD_TODAY)
        custom_from = date_from
        custom_to = date_to
        if period != PERIOD_CUSTOM:
            custom_from = custom_to = None
        elif date_from is None and date_to is None and hasattr(self, "date_from"):
            custom_from = self.date_from
            custom_to = self.date_to
        windows = self._reporting_period_windows(
            period,
            date_from=custom_from,
            date_to=custom_to,
        )
        return self._reporting_paid_orders_between(*windows["data_current"])

    def _reporting_financial_summary_for_period(
        self, period=None, date_from=None, date_to=None, orders=None
    ):
        if orders is None:
            orders = self._reporting_paid_orders_for_period(
                period=period,
                date_from=date_from,
                date_to=date_to,
            )
        return self.env["pos.session"]._avea_financial_summary_from_orders(orders)

    def _reporting_period_context(self, period=None, date_from=None, date_to=None):
        period = normalize_period_key(period or PERIOD_TODAY)
        custom_from = date_from
        custom_to = date_to
        if period != PERIOD_CUSTOM:
            custom_from = custom_to = None
        elif date_from is None and date_to is None and hasattr(self, "date_from"):
            custom_from = self.date_from
            custom_to = self.date_to
        windows = self._reporting_period_windows(
            period,
            date_from=custom_from,
            date_to=custom_to,
        )
        orders = self._reporting_paid_orders_between(*windows["data_current"])
        financial = self._reporting_financial_summary_for_period(orders=orders)
        return {
            "period": period,
            "date_from": custom_from,
            "date_to": custom_to,
            "windows": windows,
            "orders": orders,
            "financial": financial,
        }
