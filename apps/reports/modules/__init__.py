from __future__ import annotations

from ..registry import is_registered, register
from .weekly_sales import WeeklySalesReport

BUILTIN_REPORTS: tuple[WeeklySalesReport, ...] = (WeeklySalesReport(),)


def load_builtin_reports() -> tuple[str, ...]:
    loaded: list[str] = []
    for report in BUILTIN_REPORTS:
        if not is_registered(report.slug):
            register(report)
            loaded.append(report.slug)
    return tuple(loaded)


load_builtin_reports()
