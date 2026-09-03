from __future__ import annotations

from collections.abc import Iterable

from .base import ReportModule

_REPORTS: dict[str, ReportModule] = {}
_REPORT_HISTORY: list[str] = []


def register(report: ReportModule) -> None:
    """Register a report module.

    The registry is intentionally small and explicit for the 0.0.x phase.
    """

    if not report.slug:
        raise ValueError("report slug is required")
    if report.slug in _REPORTS:
        raise ValueError(f"report module {report.slug!r} is already registered")
    _REPORTS[report.slug] = report
    _REPORT_HISTORY.append(report.slug)


def is_registered(slug: str) -> bool:
    return slug in _REPORTS


def get(slug: str) -> ReportModule:
    return _REPORTS[slug]


def all_reports() -> Iterable[ReportModule]:
    return tuple(_REPORTS.values())


def history() -> tuple[str, ...]:
    return tuple(_REPORT_HISTORY)


def clear() -> None:
    """Reset the registry for tests."""

    _REPORTS.clear()
    _REPORT_HISTORY.clear()
