from collections.abc import Iterable

from .base import ReportModule

_REPORTS: dict[str, ReportModule] = {}


def register(report: ReportModule) -> None:
    if not report.slug:
        raise ValueError("report slug is required")
    _REPORTS[report.slug] = report


def get(slug: str) -> ReportModule:
    return _REPORTS[slug]


def all_reports() -> Iterable[ReportModule]:
    return _REPORTS.values()
