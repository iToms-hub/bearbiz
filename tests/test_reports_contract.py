from __future__ import annotations

import pytest

from apps.reports.base import ParsedReport
from apps.reports.registry import clear, register


class DummyReport:
    slug = "weekly_sales"
    display_name = "Weekly Sales"

    def parse(self, raw_text: str) -> ParsedReport:
        return ParsedReport(
            report_type=self.slug,
            source_name="weekly_sales.pdf",
            payload={"raw_text": raw_text},
        )


def test_parsed_report_defaults_payload_to_empty_dict() -> None:
    report = ParsedReport(report_type="weekly_sales", source_name="sample.pdf")
    assert report.payload == {}


def test_registry_rejects_duplicate_slugs() -> None:
    clear()
    register(DummyReport())
    with pytest.raises(ValueError, match="already registered"):
        register(DummyReport())
