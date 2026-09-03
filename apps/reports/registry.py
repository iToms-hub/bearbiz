from __future__ import annotations

from collections.abc import Iterable

from .base import ReportModule

_REPORTS: dict[str, ReportModule] = {}


def register(report: ReportModule) -> None:
    """Register a report module.

    The registry is intentionally small and explicit for the 0.0.x phase.
    """

    if not report.slug:
        raise ValueError("report slug is required")
    if report.slug in _REPORTS:
        raise ValueError(f"report module {report.slug!r} is already registered")
    _REPORTS[report.slug] = report


def get(slug: str) -> ReportModule:
    return _REPORTS[slug]


def all_reports() -> Iterable[ReportModule]:
    return _REPORTS.values()


def clear() -> None:
    """Reset the registry for tests."""

    _REPORTS.clear()
