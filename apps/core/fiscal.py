from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class FiscalBoundary:
    year_end: date
    fiscal_year: int
    fiscal_week: int


def month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def first_weekday_on_or_after(anchor: date, weekday: int) -> date:
    days = (weekday - anchor.weekday()) % 7
    return anchor + timedelta(days=days)


def last_weekday_on_or_before(anchor: date, weekday: int) -> date:
    days = (anchor.weekday() - weekday) % 7
    return anchor - timedelta(days=days)


def nearest_weekday_to(anchor: date, weekday: int) -> date:
    before = last_weekday_on_or_before(anchor, weekday)
    after = first_weekday_on_or_after(anchor, weekday)
    if (anchor - before) <= (after - anchor):
        return before
    return after


def boundary_date(year: int, month: int, weekday: int, rule: str) -> date:
    anchor = month_end(year, month)
    if rule == "first":
        return first_weekday_on_or_after(date(year, month, 1), weekday)
    if rule == "last":
        return last_weekday_on_or_before(anchor, weekday)
    if rule == "nearest":
        return nearest_weekday_to(anchor, weekday)
    raise ValueError(f"unknown boundary rule: {rule!r}")


def fiscal_year_for_day(day: date, *, month: int, weekday: int, rule: str) -> int:
    fiscal_year_end = boundary_date(day.year, month, weekday, rule)
    return day.year if day <= fiscal_year_end else day.year + 1


def fiscal_week_for_day(day: date, *, month: int, weekday: int, rule: str) -> int:
    fiscal_year = fiscal_year_for_day(day, month=month, weekday=weekday, rule=rule)
    prior_year_end = boundary_date(fiscal_year - 1, month, weekday, rule)
    fiscal_year_start = prior_year_end + timedelta(days=1)
    return ((day - fiscal_year_start).days // 7) + 1
