from __future__ import annotations

from datetime import date

from django.test import Client
from django.urls import reverse

from apps.reports.base import ParsedReport
from apps.core.models import FiscalYearSettings, ReviewTemplate
from apps.reports.dashboard import build_six_week_dashboard, iso_week_key, week_windows
from apps.reports.views import _dashboard_target_period


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
    assert "214 Temecula: Week 34" in html
    assert "Last week performance for 09/20/26 to 09/26/26" in html
    assert "Missing reports for Fiscal Week 34: 09/20/26 to 09/26/26." in html
    assert "No Payroll data available." in html


def test_dashboard_review_defaults_to_actual_week_and_shows_missing_note(db) -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))
    template = ReviewTemplate.objects.create(name="Weekly review", layout=[])

    response = Client().get(reverse("dashboard-review"), {"template": template.pk})

    html = response.content.decode()
    assert "review-week-select" in html
    assert "Fiscal Week 34 · 09/20/26 to 09/26/26" in html
    assert "Missing reports for Fiscal Week 34: 09/20/26 to 09/26/26." in html


def test_dashboard_target_period_is_last_completed_fiscal_week(db) -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))

    target = _dashboard_target_period(reference_date=date(2026, 9, 28))

    assert target == {
        "fiscal_year": 2027,
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
