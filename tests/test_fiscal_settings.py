from __future__ import annotations

from datetime import date

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from apps.core.admin import FiscalYearSettingsAdmin
from apps.core.forms import FiscalYearSettingsForm
from apps.core.models import BoundaryRule, FiscalYearSettings, Weekday


@pytest.mark.django_db
def test_fiscal_year_boundary_uses_nearest_saturday_to_january_end() -> None:
    settings = FiscalYearSettings.objects.create()

    assert settings.fiscal_year_end(2025) == date(2025, 2, 1)
    assert settings.fiscal_year_for_date(date(2025, 2, 1)) == 2025
    assert settings.fiscal_year_for_date(date(2025, 2, 2)) == 2026
    assert settings.fiscal_week_for_date(date(2025, 2, 2)) == 1


@pytest.mark.django_db
def test_fiscal_year_boundary_supports_last_weekday_rule() -> None:
    settings = FiscalYearSettings.objects.create(
        boundary_rule=BoundaryRule.LAST,
        boundary_month=1,
        boundary_weekday=Weekday.SATURDAY,
    )

    assert settings.fiscal_year_end(2025) == date(2025, 1, 25)
    assert settings.fiscal_year_for_date(date(2025, 1, 25)) == 2025
    assert settings.fiscal_year_for_date(date(2025, 1, 26)) == 2026


@pytest.mark.django_db
def test_admin_hides_add_after_single_settings_row_exists() -> None:
    admin = FiscalYearSettingsAdmin(FiscalYearSettings, AdminSite())
    request = RequestFactory().get("/admin/")

    assert admin.has_add_permission(request)

    FiscalYearSettings.objects.create()

    assert not admin.has_add_permission(request)


def test_admin_form_exposes_retail_calendar_controls() -> None:
    form = FiscalYearSettingsForm(
        data={
            "calendar_pattern": "454",
            "boundary_rule": BoundaryRule.NEAREST,
            "boundary_month": 1,
            "boundary_weekday": Weekday.SATURDAY,
        }
    )

    assert form.is_valid(), form.errors
