from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any


DateLike = date | datetime | str


@dataclass(frozen=True, slots=True)
class FiscalCalendarConfig:
    """Configuration for fiscal-year and fiscal-week calculations."""

    start_month: int = 1
    start_day: int = 1
    week_ending_weekday: int = 5

    def __post_init__(self) -> None:
        if not 1 <= self.start_month <= 12:
            raise ValueError("start_month must be between 1 and 12")
        if not 1 <= self.start_day <= 31:
            raise ValueError("start_day must be between 1 and 31")
        if not 0 <= self.week_ending_weekday <= 6:
            raise ValueError("week_ending_weekday must be between 0 and 6")


@dataclass(frozen=True, slots=True)
class FiscalWeek:
    """Normalized fiscal calendar details for a date range."""

    fiscal_year: int
    week_ending_date: date
    fiscal_week_number: int
    period_start: date
    period_end: date


def _coerce_date(value: DateLike) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"invalid ISO date: {value!r}") from exc
    raise TypeError(f"unsupported date value: {type(value)!r}")


def _month_day_for_year(year: int, month: int, day: int) -> date:
    if month == 2 and day == 29:
        if _is_leap_year(year):
            return date(year, month, day)
        return date(year, 2, 28)
    return date(year, month, day)


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _fiscal_year_start_for_week_end(week_end: date, config: FiscalCalendarConfig) -> tuple[int, date]:
    candidate_start = _month_day_for_year(week_end.year, config.start_month, config.start_day)
    if (config.start_month, config.start_day) == (1, 1):
        return week_end.year, candidate_start
    if week_end >= candidate_start:
        fiscal_year = week_end.year + 1
        start = candidate_start
    else:
        fiscal_year = week_end.year
        start = _month_day_for_year(week_end.year - 1, config.start_month, config.start_day)
    return fiscal_year, start


def _first_week_ending_on_or_after(start: date, week_ending_weekday: int) -> date:
    delta_days = (week_ending_weekday - start.weekday()) % 7
    return start + timedelta(days=delta_days)


def calculate_fiscal_week(
    period_start: DateLike,
    period_end: DateLike,
    *,
    config: FiscalCalendarConfig | None = None,
) -> FiscalWeek:
    """Calculate fiscal year details for a report date range.

    The week ending date is the normalized period end. Fiscal year names follow
    the convention used by retail calendars: the fiscal year is the year in
    which the fiscal period ends.
    """

    config = config or FiscalCalendarConfig()
    start = _coerce_date(period_start)
    end = _coerce_date(period_end)
    if start > end:
        raise ValueError("period_start must be on or before period_end")

    fiscal_year, fiscal_year_start = _fiscal_year_start_for_week_end(end, config)
    first_week_end = _first_week_ending_on_or_after(fiscal_year_start, config.week_ending_weekday)
    week_index = ((end - first_week_end).days // 7) + 1
    if week_index < 1:
        week_index = 1

    return FiscalWeek(
        fiscal_year=fiscal_year,
        week_ending_date=end,
        fiscal_week_number=week_index,
        period_start=start,
        period_end=end,
    )


def as_dict(fiscal_week: FiscalWeek) -> dict[str, Any]:
    """Serialize a fiscal week record with ISO date strings."""

    return {
        "fiscal_year": fiscal_week.fiscal_year,
        "week_ending_date": fiscal_week.week_ending_date.isoformat(),
        "fiscal_week_number": fiscal_week.fiscal_week_number,
        "period_start": fiscal_week.period_start.isoformat(),
        "period_end": fiscal_week.period_end.isoformat(),
    }
