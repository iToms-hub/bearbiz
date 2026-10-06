from __future__ import annotations

from django.db import migrations



def relabel_segment_report_import_fiscal_years(apps, schema_editor) -> None:
    """Relabel only legacy current-year SegmentReportImport metadata rows.

    SegmentReportImport has no date or uniqueness constraint, so its legacy
    current-year label is the only safe scope available. Labels outside that
    configured legacy year are historical data and remain unchanged.
    """
    settings_model = apps.get_model("core", "FiscalYearSettings")
    settings = settings_model.objects.order_by("pk").first()
    start_date = getattr(settings, "fiscal_year_start_date", None) if settings else None
    if not start_date:
        return

    target_year = start_date.year
    legacy_year = target_year + 1
    apps.get_model("reports", "SegmentReportImport").objects.filter(
        fiscal_year=legacy_year
    ).update(fiscal_year=target_year)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_reviewtemplate_subtitle"),
        ("reports", "0020_relabel_manual_fiscal_years"),
    ]

    operations = [
        migrations.RunPython(
            relabel_segment_report_import_fiscal_years,
            migrations.RunPython.noop,
        ),
    ]
