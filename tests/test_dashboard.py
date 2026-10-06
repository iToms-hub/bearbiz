from __future__ import annotations

from datetime import date
from importlib import import_module
from typing import cast

import pytest
from django.test import Client
from django.urls import reverse

from apps.reports.base import ParsedReport
from apps.core.models import FiscalYearSettings, ReviewTemplate
from apps.reports.models import GanttImport, GanttReport, RankingSummary, ReportUpload
from apps.reports.dashboard import build_six_week_dashboard, iso_week_key, week_windows
from apps.reports.views import _dashboard_period_for_week, _dashboard_ranking_summaries, _dashboard_target_period

standardize_fiscal_year_labels = import_module(
    "apps.reports.migrations.0019_standardize_fiscal_year_labels"
).standardize_fiscal_year_labels


def make_report(day: date, **metrics: float) -> ParsedReport:
    week_key = iso_week_key(day)
    return ParsedReport(
        report_type="weekly_sales",
        source_name=f"weekly-sales-{week_key}.pdf",
        period_start=day.isoformat(),
        period_end=day.isoformat(),
        payload={"week": week_key, **metrics},
        raw_rows=[metrics],
    )


def test_dashboard_blanks_stale_data_and_identifies_missing_target_week(db) -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))

    response = Client().get(reverse("dashboard"))

    html = response.content.decode()
    assert "214 Temecula: Week 35" in html
    assert "Last week performance for 09/27/26 to 10/03/26" in html
    assert "Missing reports for Fiscal Week 35: 09/27/26 to 10/03/26." in html
    assert "No Payroll data available." in html


def test_dashboard_review_defaults_to_actual_week_and_shows_missing_note(db) -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))
    template = ReviewTemplate.objects.create(name="Weekly review", layout=[])

    response = Client().get(reverse("dashboard-review"), {"template": template.pk})

    html = response.content.decode()
    assert "review-week-select" in html
    assert "Fiscal Week 35 · 09/27/26 to 10/03/26" in html
    assert "Missing reports for Fiscal Week 35: 09/27/26 to 10/03/26." in html


def test_dashboard_target_period_is_last_completed_fiscal_week(db) -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))

    target = _dashboard_target_period(reference_date=date(2026, 9, 28))

    assert target == {
        "fiscal_year": 2026,
        "fiscal_week": 34,
        "period_start": date(2026, 9, 20),
        "period_end": date(2026, 9, 26),
    }


def test_dashboard_target_period_does_not_follow_uploaded_data(db) -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))

    target = _dashboard_target_period(reference_date=date(2026, 10, 5))

    assert target["fiscal_week"] == 35
    assert target["period_start"] == date(2026, 9, 27)
    assert target["period_end"] == date(2026, 10, 3)


def test_dashboard_week_period_uses_calendar_year_boundaries_across_53rd_week(db) -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))
    reference = {
        "fiscal_year": 2027,
        "fiscal_week": 1,
        "period_start": date(2027, 2, 1),
        "period_end": date(2027, 2, 7),
    }

    period = _dashboard_period_for_week(2026, 53, reference)

    assert period["period_start"] == date(2027, 1, 31)
    assert period["period_end"] == date(2027, 2, 6)


def test_repair_relabels_existing_ranking_data_and_dashboard_finds_it(db) -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))
    upload = ReportUpload.objects.create(source_name="ranking.pdf", report_type="ranking", source_file="ranking.pdf")
    RankingSummary.objects.create(
        report_upload=upload,
        fiscal_year=2027,
        fiscal_week=35,
        fiscal_period_start=date(2026, 9, 27),
        fiscal_period_end=date(2026, 10, 3),
        raw_json={"fiscal": {"fiscal_year": 2027}, "store_rows": [{"store_number": "214", "store_name": "Temecula", "metrics": {}}]},
    )

    from django.apps import apps

    standardize_fiscal_year_labels(apps, None)
    standardize_fiscal_year_labels(apps, None)

    target = _dashboard_target_period(reference_date=date(2026, 10, 5))
    assert target["fiscal_year"] == 2026
    assert target["fiscal_week"] == 35
    repaired = _dashboard_ranking_summaries(target_period=target)[0]
    assert repaired.fiscal_year == 2026
    repaired_raw = cast(dict[str, object], repaired.raw_json)
    assert cast(dict[str, object], repaired_raw["fiscal"])["fiscal_year"] == 2026


def test_standardize_fiscal_year_labels_handles_february_29_start_date(db) -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2024, 2, 29))

    start_year_for_day = import_module(
        "apps.reports.migrations.0019_standardize_fiscal_year_labels"
    )._start_year_for_day

    assert start_year_for_day(date(2025, 2, 27), date(2024, 2, 29)) == 2024
    assert start_year_for_day(date(2025, 2, 28), date(2024, 2, 29)) == 2025


def test_repair_allows_multiple_gantt_import_rows_for_same_week(db) -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))
    GanttImport.objects.create(
        source_name="gantt-mon.pdf",
        fiscal_year=2027,
        fiscal_week=35,
        day_date=date(2026, 9, 28),
    )
    GanttImport.objects.create(
        source_name="gantt-tue.pdf",
        fiscal_year=2027,
        fiscal_week=35,
        day_date=date(2026, 9, 29),
    )

    from django.apps import apps

    standardize_fiscal_year_labels(apps, None)

    assert list(GanttImport.objects.values_list("fiscal_year", flat=True)) == [2026, 2026]


def test_repair_allows_distinct_gantt_report_days_for_same_week(db) -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))
    for day, name in [("Monday", "gantt-mon.pdf"), ("Tuesday", "gantt-tue.pdf")]:
        GanttReport.objects.create(
            source_name=name,
            fiscal_year=2027,
            fiscal_week=35,
            day_of_week=day,
            day_date=date(2026, 9, 28) if day == "Monday" else date(2026, 9, 29),
            week_end=date(2026, 10, 3),
        )

    from django.apps import apps

    standardize_fiscal_year_labels(apps, None)

    assert set(GanttReport.objects.values_list("fiscal_year", flat=True)) == {2026}


def test_repair_aborts_on_actual_summary_uniqueness_collision(db) -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))
    existing_upload = ReportUpload.objects.create(source_name="existing.pdf", report_type="ranking", source_file="existing.pdf")
    stale_upload = ReportUpload.objects.create(source_name="stale.pdf", report_type="ranking", source_file="stale.pdf")
    RankingSummary.objects.create(
        report_upload=existing_upload,
        fiscal_year=2026,
        fiscal_week=35,
        fiscal_period_end=date(2026, 10, 3),
    )
    RankingSummary.objects.create(
        report_upload=stale_upload,
        fiscal_year=2027,
        fiscal_week=35,
        fiscal_period_end=date(2026, 10, 3),
    )

    from django.apps import apps

    with pytest.raises(RuntimeError, match=r"RankingSummary pk=.*FY2026/W35 already exists"):
        standardize_fiscal_year_labels(apps, None)


def test_parsed_report_defaults_raw_rows_to_empty_list() -> None:
    report = ParsedReport(report_type="weekly_sales", source_name="sample.pdf")
    assert report.raw_rows == []



def test_parsed_report_keeps_raw_rows_intact() -> None:
    raw_rows = [{"week": "2026-W35", "sales": 42}]
    report = ParsedReport(
        report_type="weekly_sales",
        source_name="weekly_sales.pdf",
        raw_rows=raw_rows,
    )
    assert report.raw_rows == raw_rows


def test_week_windows_show_current_week_and_previous_five_weeks() -> None:
    weeks = week_windows(reference_date=date(2026, 9, 3))
    assert len(weeks) == 6
    assert weeks[-1].is_current is True
    assert weeks[-1].key == "2026-W36"
    assert [week.key for week in weeks] == [
        "2026-W31",
        "2026-W32",
        "2026-W33",
        "2026-W34",
        "2026-W35",
        "2026-W36",
    ]


def test_dashboard_filters_selected_weeks_and_builds_six_week_trends() -> None:
    reports = [
        make_report(date(2026, 8, 3), sales=10, orders=2),
        make_report(date(2026, 8, 10), sales=20, orders=4),
        make_report(date(2026, 8, 24), sales=40, orders=8),
        make_report(date(2026, 8, 31), sales=80, orders=16),
    ]

    dashboard = build_six_week_dashboard(
        reports,
        selection=["2026-W32", "2026-W33", "2026-W35"],
        reference_date=date(2026, 9, 1),
    )

    assert dashboard.selected_week_keys == ("2026-W32", "2026-W33", "2026-W35")
    assert [report.week_key for report in dashboard.reports] == ["2026-W32", "2026-W33", "2026-W35"]
    assert dashboard.metric_totals == {"sales": 70.0, "orders": 14.0}

    sales_trend = dashboard.trends["sales"]
    assert [point.value for point in sales_trend.points] == [0.0, 10.0, 20.0, 0.0, 40.0, 0.0]
    orders_trend = dashboard.trends["orders"]
    assert [point.value for point in orders_trend.points] == [0.0, 2.0, 4.0, 0.0, 8.0, 0.0]
