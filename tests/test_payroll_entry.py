from importlib import import_module
from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.models import FiscalYearSettings, ReviewTemplate
from apps.reports.models import PayrollWeek
from apps.reports.payroll_views import FISCAL_MONTH_WEEK_COUNTS, _parse_decimal, payroll_dashboard_summary, payroll_fiscal_year_start, payroll_month_labels, payroll_month_layout, payroll_week_ending


@pytest.mark.django_db
def test_fiscal_payroll_layout_has_twelve_454_months_and_all_week_numbers() -> None:
    layout = payroll_month_layout()

    assert list(layout) == list(range(1, 13))
    assert [len(layout[month]) for month in layout] == list(FISCAL_MONTH_WEEK_COUNTS)
    assert [week for weeks in layout.values() for week in weeks] == list(range(1, 53))
    assert list(payroll_month_labels(2027).values()) == ["Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan"]
    assert payroll_week_ending(2027, 1).strftime("%m/%d/%y") == "02/07/26"


@pytest.mark.django_db
def test_payroll_week_calculates_actual_sales_hours_and_variance() -> None:
    row = PayrollWeek.objects.create(
        fiscal_year=2027,
        fiscal_month=2,
        fiscal_week=6,
        sales_plan=Decimal("34800.00"),
        trend_percent=Decimal("-23.00"),
        sun=Decimal("40.27"),
        mon=Decimal("35.42"),
        tue=Decimal("19.73"),
        wed=Decimal("52.00"),
        thu=Decimal("20.00"),
        fri=Decimal("28.00"),
        sat=Decimal("52.00"),
        labor_calculator_target_hours=Decimal("222.50"),
    )

    assert row.actual_sales == Decimal("26796.00")
    assert row.total_hours_actual_scheduled == Decimal("247.42")
    assert row.current_variance == Decimal("24.92")

    row.trend_percent = None
    assert row.actual_sales == Decimal("34800.00")


@pytest.mark.django_db
def test_payroll_page_has_month_tabs_and_saves_only_editable_fields(client: Client) -> None:
    response = client.post(
        reverse("payroll"),
        {
            "month": "2",
            "sales_plan_6": "34800",
            "trend_percent_6": "-23",
            "sun_6": "40.27",
            "mon_6": "35.42",
            "tue_6": "19.73",
            "wed_6": "52",
            "thu_6": "20",
            "fri_6": "28",
            "sat_6": "52",
            "labor_target_6": "222.5",
        },
    )

    assert response.status_code == 302
    row = PayrollWeek.objects.get(fiscal_year=2027, fiscal_week=6)
    assert row.sales_plan == Decimal("34800.00")
    assert row.actual_sales == Decimal("26796.00")
    assert row.total_hours_actual_scheduled == Decimal("247.42")
    assert row.current_variance == Decimal("24.92")

    html = client.get(reverse("payroll") + "?month=2").content.decode()
    assert html.count('data-payroll-month-tab=') == 12
    assert '>6<' in html
    assert '>Week 6<' not in html
    assert 'name="actual_sales_6"' not in html
    assert 'name="total_hours_6"' not in html
    assert 'name="current_variance_6"' not in html
    assert 'name="sales_plan_6"' in html
    assert html.count('name="sun_6"') == 1
    assert html.count('name="sat_6"') == 1
    assert '>Feb<' in html
    assert '>Week Ending<' in html
    assert 'data-calculation="actual-sales"' in html
    assert 'data-calculation="total-hours"' in html
    assert 'data-calculation="variance"' in html
    assert 'addEventListener(\'input\'' in html
    assert 'recalculate(row); recalculateSummary()' in html
    assert 'trend ?? 0' in html
    assert '>Total<' in html
    assert '>Current % to Target Hours<' in html
    assert '>Hours +/- to 101% Target<' in html
    assert '>Hours +/- to 95% Target<' in html
    assert '$26,796.00' in html
    assert '>247.42<' in html
    assert '>222.50<' in html
    assert '>24.92<' in html
    assert '>111.20%<' in html
    assert '>-22.70<' in html
    assert '>-36.05<' in html
    assert 'payroll-summary-row' in html
    assert 'payroll-save-button' in html
    assert 'payroll-total-row' in html
    assert 'payroll-percent-row' in html
    assert 'payroll-101-row' in html
    assert 'payroll-95-row' in html
    assert 'Current % to Target Hours' in html
    assert 'Hours +/- to 101% Target' in html
    assert 'Hours +/- to 95% Target' in html
    assert html.count('<td class="payroll-summary-value"') == 7
    assert '.payroll-table-wrap' in html
    assert 'width: 100%; min-width: 0; table-layout: fixed' in html
    assert 'min-width: 72rem' not in html
    assert 'overflow-wrap: anywhere' in html
    assert 'justify-content: center' in html
    assert '.payroll-save-button { margin-top: 1.25rem; }' in html


@pytest.mark.django_db
def test_payroll_page_clears_an_existing_week_when_all_inputs_are_blank(client: Client) -> None:
    PayrollWeek.objects.create(
        fiscal_year=2027,
        fiscal_month=1,
        fiscal_week=1,
        sales_plan=Decimal("1000.00"),
    )

    response = client.post(reverse("payroll"), {"month": "1"})

    assert response.status_code == 302
    assert not PayrollWeek.objects.filter(fiscal_year=2027, fiscal_week=1).exists()


def test_payroll_summary_removal_migration_is_explicitly_irreversible() -> None:
    migration = import_module("apps.reports.migrations.0010_remove_payrollsummary")
    operation = migration.Migration.operations[0]

    assert operation.reverse_sql is None


def test_payroll_rejects_non_finite_decimal_input() -> None:
    with pytest.raises(ValueError, match="valid number"):
        _parse_decimal("NaN")
    with pytest.raises(ValueError, match="valid number"):
        _parse_decimal("Infinity")


@pytest.mark.django_db
def test_payroll_calendar_normalizes_configured_start_and_supports_requested_year() -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 2))

    assert payroll_fiscal_year_start(2027) == date(2026, 2, 1)
    assert payroll_fiscal_year_start(2026) == date(2025, 2, 2)
    assert payroll_week_ending(2027, 1) == date(2026, 2, 7)


@pytest.mark.django_db
def test_payroll_is_available_on_dashboard_and_review_with_authoritative_week(client: Client) -> None:
    PayrollWeek.objects.create(
        fiscal_year=2027,
        fiscal_month=2,
        fiscal_week=6,
        sun=Decimal("40"),
        mon=Decimal("35"),
        labor_calculator_target_hours=Decimal("80"),
    )

    summary = payroll_dashboard_summary(2027)
    assert summary == {
        "week": "6", "week_ending": "03/14/26", "total_hours": "75.00",
        "target_hours": "80.00", "variance": "-5.00", "percent": "93.8%",
    }
    dashboard = client.get(reverse("dashboard"))
    assert dashboard.status_code == 200
    dashboard_html = dashboard.content.decode()
    assert "dashboard-card-payroll" in dashboard_html
    assert "75.00" in dashboard_html
    assert "-5.00" in dashboard_html
    assert "93.8%" in dashboard_html

    template = ReviewTemplate.objects.create(name="Payroll review", layout=[{"type": "payroll", "title": "Last Week Payroll"}])
    review = client.get(reverse("dashboard-review"), {"template": template.pk})
    assert review.status_code == 200
    review_html = review.content.decode()
    assert 'data-review-module="payroll"' in review_html
    assert "Actual Hours" in review_html
    assert "Percent to Target" in review_html
