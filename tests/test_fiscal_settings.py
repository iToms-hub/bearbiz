from __future__ import annotations

from datetime import date

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from apps.core.admin import FiscalYearSettingsAdmin
from apps.core.forms import FiscalYearSettingsForm
from apps.core.models import FiscalYearSettings
from apps.reports.modules.weekly_sales import WeeklySalesReport


@pytest.mark.django_db
def test_fiscal_year_start_date_drives_week_calculation() -> None:
    settings = FiscalYearSettings.objects.create(fiscal_year_start_date=date(2025, 2, 2))

    assert settings.fiscal_year_for_date(date(2025, 2, 1)) == 2025
    assert settings.fiscal_year_for_date(date(2025, 2, 2)) == 2026
    assert settings.fiscal_week_for_date(date(2025, 2, 2)) == 1


@pytest.mark.django_db
def test_weekly_sales_parser_uses_saved_fiscal_year_start_date() -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))

    report = WeeklySalesReport().parse(
        """Weekly Sales Summary
Period Start    2026-02-01
Period End    2026-02-07
Net Sales    20366
Orders    410
"""
    )

    assert report.payload["fiscal"]["fiscal_week_number"] == 1
    assert report.payload["fiscal"]["fiscal_year"] == 2027


@pytest.mark.django_db
def test_admin_hides_add_after_single_settings_row_exists() -> None:
    admin = FiscalYearSettingsAdmin(FiscalYearSettings, AdminSite())
    request = RequestFactory().get("/admin/")

    assert admin.has_add_permission(request)

    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2025, 2, 2))

    assert not admin.has_add_permission(request)


def test_admin_form_exposes_fiscal_year_start_date_only() -> None:
    form = FiscalYearSettingsForm(
        data={
            "fiscal_year_start_date": "2025-02-02",
        }
    )

    assert form.is_valid(), form.errors
    assert list(form.fields) == ["fiscal_year_start_date"]
