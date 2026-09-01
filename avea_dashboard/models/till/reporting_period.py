"""Business Overview reporting periods.

One source of truth for the selected period, its comparison window, elapsed
days, and display labels. Standard periods never extend past ``today``.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

PERIOD_TODAY = "today"
PERIOD_WTD = "wtd"
PERIOD_MTD = "mtd"
PERIOD_LAST_7 = "last_7"
PERIOD_LAST_30 = "last_30"
PERIOD_YTD = "ytd"
PERIOD_CUSTOM = "custom"

PERIOD_KEYS = (
    PERIOD_TODAY,
    PERIOD_WTD,
    PERIOD_MTD,
    PERIOD_LAST_7,
    PERIOD_LAST_30,
    PERIOD_YTD,
    PERIOD_CUSTOM,
)

LEGACY_PERIODS = {
    "week": PERIOD_WTD,
    "month": PERIOD_MTD,
}

PERIOD_LABELS = {
    PERIOD_TODAY: "Today",
    PERIOD_WTD: "Week to Date",
    PERIOD_MTD: "Month to Date",
    PERIOD_LAST_7: "Last 7 Days",
    PERIOD_LAST_30: "Last 30 Days",
    PERIOD_YTD: "Year to Date",
    PERIOD_CUSTOM: "Custom Period",
}

COMPARISON_LABELS = {
    PERIOD_TODAY: "Yesterday",
    PERIOD_WTD: "Previous week to date",
    PERIOD_MTD: "Previous month to date",
    PERIOD_LAST_7: "Previous 7 days",
    PERIOD_LAST_30: "Previous 30 days",
    PERIOD_YTD: "Previous year to date",
    PERIOD_CUSTOM: "Previous period",
}

# ISO week: Monday is the first day. Matches the WTD examples (Tue 1 Sep 2026
# is 31 Aug–1 Sep, so the week started on Monday 31 Aug).
WEEK_START_WEEKDAY = 0


@dataclass(frozen=True)
class ReportingPeriod:
    key: str
    label: str
    comparison_label: str
    current_start: date
    current_end: date
    comparison_start: date
    comparison_end: date
    elapsed_days: int
    today: date

    @property
    def current(self):
        return self.current_start, self.current_end

    @property
    def comparison(self):
        return self.comparison_start, self.comparison_end

    def includes_future_dates(self):
        return self.current_end > self.today


def normalize_period_key(period):
    if period in LEGACY_PERIODS:
        return LEGACY_PERIODS[period]
    if period in PERIOD_KEYS:
        return period
    return PERIOD_TODAY


def _inclusive_days(start, end):
    return (end - start).days + 1


def _preceding_window(start, elapsed_days):
    """The ``elapsed_days`` calendar days immediately before ``start``."""
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=elapsed_days - 1)
    return prev_start, prev_end


def _week_start(day):
    return day - timedelta(days=(day.weekday() - WEEK_START_WEEKDAY) % 7)


def _previous_month_start(day):
    month_start = day.replace(day=1)
    if month_start.month == 1:
        return month_start.replace(year=month_start.year - 1, month=12)
    return month_start.replace(month=month_start.month - 1)


def _same_calendar_day_previous_year(day):
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        # 29 Feb in a leap year has no counterpart in a non-leap year.
        return day.replace(year=day.year - 1, day=28)


def _rolling_window(today, days):
    current_end = today
    current_start = today - timedelta(days=days - 1)
    elapsed = days
    comparison_start, comparison_end = _preceding_window(current_start, elapsed)
    return current_start, current_end, comparison_start, comparison_end, elapsed


def _custom_window(today, date_from, date_to):
    start = date_from or today.replace(day=1)
    end = date_to or today
    if start > end:
        start, end = end, start
    elapsed = _inclusive_days(start, end)
    comparison_start, comparison_end = _preceding_window(start, elapsed)
    return start, end, comparison_start, comparison_end, elapsed


def resolve_reporting_period(period, today, custom_from=None, custom_to=None):
    """Return the reporting window and equivalent comparison window.

    ``today`` is the dashboard's local calendar day. Standard periods never
    include dates after it. Custom periods keep the user's chosen range.
    """
    key = normalize_period_key(period)
    if key == PERIOD_TODAY:
        current_start = current_end = today
        comparison_start = comparison_end = today - timedelta(days=1)
        elapsed = 1
    elif key == PERIOD_WTD:
        current_start = _week_start(today)
        current_end = today
        elapsed = _inclusive_days(current_start, current_end)
        prev_week_start = current_start - timedelta(days=7)
        comparison_start = prev_week_start
        comparison_end = prev_week_start + timedelta(days=elapsed - 1)
    elif key == PERIOD_MTD:
        current_start = today.replace(day=1)
        current_end = today
        elapsed = _inclusive_days(current_start, current_end)
        comparison_start = _previous_month_start(today)
        prev_last = monthrange(comparison_start.year, comparison_start.month)[1]
        comparison_end = comparison_start.replace(day=min(today.day, prev_last))
    elif key == PERIOD_LAST_7:
        current_start, current_end, comparison_start, comparison_end, elapsed = (
            _rolling_window(today, 7)
        )
    elif key == PERIOD_LAST_30:
        current_start, current_end, comparison_start, comparison_end, elapsed = (
            _rolling_window(today, 30)
        )
    elif key == PERIOD_YTD:
        current_start = date(today.year, 1, 1)
        current_end = today
        elapsed = _inclusive_days(current_start, current_end)
        comparison_start = date(today.year - 1, 1, 1)
        comparison_end = _same_calendar_day_previous_year(today)
    else:
        current_start, current_end, comparison_start, comparison_end, elapsed = (
            _custom_window(today, custom_from, custom_to)
        )

    return ReportingPeriod(
        key=key,
        label=PERIOD_LABELS[key],
        comparison_label=COMPARISON_LABELS[key],
        current_start=current_start,
        current_end=current_end,
        comparison_start=comparison_start,
        comparison_end=comparison_end,
        elapsed_days=elapsed,
        today=today,
    )
