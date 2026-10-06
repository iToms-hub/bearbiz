from __future__ import annotations

from datetime import date
from importlib import import_module

import pytest

from apps.core.models import FiscalYearSettings
from apps.reports.models import SegmentReportImport


relabel_segment_report_import_fiscal_years = import_module(
    "apps.reports.migrations.0021_relabel_segment_report_import_fiscal_years"
).relabel_segment_report_import_fiscal_years


@pytest.mark.django_db
def test_relabels_only_legacy_segment_import_year_and_is_idempotent() -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))
    legacy = SegmentReportImport.objects.create(
        source_name="week-35-monday.pdf",
        parse_status="parsed",
        fiscal_year=2027,
        fiscal_week=35,
        day_of_week="Monday",
    )
    historical = SegmentReportImport.objects.create(
        source_name="week-35-monday-old.pdf",
        parse_status="parsed",
        fiscal_year=2025,
        fiscal_week=35,
        day_of_week="Monday",
    )

    from django.apps import apps

    relabel_segment_report_import_fiscal_years(apps, None)
    relabel_segment_report_import_fiscal_years(apps, None)

    legacy.refresh_from_db()
    historical.refresh_from_db()
    assert legacy.fiscal_year == 2026
    assert legacy.fiscal_week == 35
    assert legacy.day_of_week == "Monday"
    assert historical.fiscal_year == 2025
