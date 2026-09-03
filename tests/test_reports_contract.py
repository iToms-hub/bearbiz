from __future__ import annotations

import pytest

from apps.reports.base import ParsedReport
from apps.reports.modules import load_builtin_reports
from apps.reports.modules.weekly_sales import WeeklySalesReport
from apps.reports.registry import all_reports, clear, get, history, register


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


def test_parsed_report_defaults_raw_rows_to_empty_list() -> None:
    report = ParsedReport(report_type="weekly_sales", source_name="sample.pdf")
    assert report.raw_rows == []


def test_weekly_sales_parser_uses_top_table_only() -> None:
    report = WeeklySalesReport().parse(
        """Weekly Sales Summary
Net Sales    1200
Orders    48
Week Ending    2026-09-06

Lower summary table
Net Sales    9999
Orders    1
"""
    )

    assert report.report_type == "weekly_sales"
    assert report.period_end == "2026-09-06"
    assert report.payload["summary_kpis"] == {
        "net_sales": 1200,
        "orders": 48,
        "period_end": "2026-09-06",
    }
    assert [row["value"] for row in report.raw_rows] == ["1200", "48", "2026-09-06"]


def test_weekly_sales_parser_reads_date_range_from_title_line() -> None:
    report = WeeklySalesReport().parse(
        """Statistics 2/1/2026 - 2/7/2026 1214 The Promenade in Temecula

Weekly Sales Summary
Net Sales    20366
Orders    410
"""
    )

    assert report.period_start == "2026-02-01"
    assert report.period_end == "2026-02-07"
    assert report.payload["fiscal"] is not None


def test_registry_rejects_duplicate_slugs() -> None:
    clear()
    register(DummyReport())
    with pytest.raises(ValueError, match="already registered"):
        register(DummyReport())


def test_builtin_weekly_sales_report_registers_once_and_tracks_history() -> None:
    clear()
    loaded = load_builtin_reports()

    assert loaded == ("weekly_sales",)
    assert tuple(report.slug for report in all_reports()) == ("weekly_sales",)
    assert get("weekly_sales").display_name == "Weekly Sales"
    assert history() == ("weekly_sales",)

    assert load_builtin_reports() == ()
    assert history() == ("weekly_sales",)
