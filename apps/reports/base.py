from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ParsedReport:
    """Normalized output from a report parser.

    Each report module should translate its input PDF/text into a predictable
    payload that the dashboards and export layer can consume.
    """

    report_type: str
    source_name: str
    period_start: str | None = None
    period_end: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    raw_rows: list[dict[str, Any]] = field(default_factory=list)


class ReportModule(Protocol):
    """Contract for a fixed weekly report type."""

    slug: str
    display_name: str

    def parse(self, raw_text: str) -> ParsedReport:
        """Turn raw text extracted from a report into normalized data."""
        ...
