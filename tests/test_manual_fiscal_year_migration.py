from __future__ import annotations

from datetime import date
from decimal import Decimal
from importlib import import_module

import pytest

from apps.core.models import FiscalYearSettings
from apps.reports.models import PartiesWeek, PayrollWeek


relabel_manual_fiscal_years = import_module(
    "apps.reports.migrations.0020_relabel_manual_fiscal_years"
).relabel_manual_fiscal_years
start_year_for_day = import_module(
    "apps.reports.migrations.0019_standardize_fiscal_year_labels"
)._start_year_for_day


@pytest.mark.django_db
def test_relabels_manual_weeks_to_configured_start_year_and_is_idempotent() -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))
    parties = PartiesWeek.objects.create(
        fiscal_year=2027,
        fiscal_month=8,
        fiscal_week=35,
        held_current=Decimal("12.34"),
    )
    payroll = PayrollWeek.objects.create(
        fiscal_year=2027,
        fiscal_month=8,
        fiscal_week=35,
        sales_plan=Decimal("567.89"),
    )

    from django.apps import apps

    relabel_manual_fiscal_years(apps, None)
    relabel_manual_fiscal_years(apps, None)

    parties.refresh_from_db()
    payroll.refresh_from_db()
    assert parties.fiscal_year == 2026
    assert parties.held_current == Decimal("12.34")
    assert payroll.fiscal_year == 2026
    assert payroll.sales_plan == Decimal("567.89")


@pytest.mark.django_db
def test_does_not_relabel_unrelated_manual_historical_years() -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))
    historical_parties = PartiesWeek.objects.create(
        fiscal_year=2025,
        fiscal_month=8,
        fiscal_week=35,
    )
    historical_payroll = PayrollWeek.objects.create(
        fiscal_year=2028,
        fiscal_month=8,
        fiscal_week=35,
    )

    from django.apps import apps

    relabel_manual_fiscal_years(apps, None)

    historical_parties.refresh_from_db()
    historical_payroll.refresh_from_db()
    assert historical_parties.fiscal_year == 2025
    assert historical_payroll.fiscal_year == 2028


@pytest.mark.django_db
def test_aborts_before_writes_when_manual_week_would_collide() -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))
    PartiesWeek.objects.create(fiscal_year=2026, fiscal_month=8, fiscal_week=35)
    legacy = PartiesWeek.objects.create(fiscal_year=2027, fiscal_month=8, fiscal_week=35)
    PayrollWeek.objects.create(fiscal_year=2027, fiscal_month=8, fiscal_week=35)

    from django.apps import apps

    with pytest.raises(RuntimeError, match="PartiesWeek"):
        relabel_manual_fiscal_years(apps, None)

    legacy.refresh_from_db()
    assert legacy.fiscal_year == 2027
    assert PayrollWeek.objects.get(fiscal_week=35).fiscal_year == 2027


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2024, 2, 28), 2023),
        (date(2024, 2, 29), 2024),
        (date(2025, 2, 28), 2025),
    ],
)
def test_standardize_migration_matches_february_29_runtime_anniversary(day: date, expected: int) -> None:
    assert start_year_for_day(day, date(2024, 2, 29)) == expected
