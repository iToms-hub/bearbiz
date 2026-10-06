from __future__ import annotations

from django.db import migrations


MANUAL_WEEK_MODELS = ("PartiesWeek", "PayrollWeek")


def relabel_manual_fiscal_years(apps, schema_editor) -> None:
    """Move only legacy current-year manual rows to Settings' start-year label.

    These tables have no date field, so the only safe legacy scope is the
    configured start year plus one: the end-year convention previously used
    by the manual entry forms. Historical labels outside that pair are left
    untouched. Collision checks happen for every affected model before any
    update so a failed migration cannot partially relabel its rows.
    """
    settings_model = apps.get_model("core", "FiscalYearSettings")
    settings = settings_model.objects.order_by("pk").first()
    start_date = getattr(settings, "fiscal_year_start_date", None) if settings else None
    if not start_date:
        return

    target_year = start_date.year
    legacy_year = target_year + 1
    models = [apps.get_model("reports", name) for name in MANUAL_WEEK_MODELS]

    # Preflight all models before changing either table. Both models enforce
    # (fiscal_year, fiscal_week) uniqueness.
    for model in models:
        legacy_weeks = set(
            model.objects.filter(fiscal_year=legacy_year).values_list("fiscal_week", flat=True)
        )
        if not legacy_weeks:
            continue
        collisions = set(
            model.objects.filter(fiscal_year=target_year, fiscal_week__in=legacy_weeks).values_list(
                "fiscal_week", flat=True
            )
        )
        if collisions:
            weeks = ", ".join(str(week) for week in sorted(collisions))
            raise RuntimeError(
                f"Cannot safely relabel {model.__name__}: "
                f"FY{target_year}/W{weeks} already exists"
            )

    for model in models:
        model.objects.filter(fiscal_year=legacy_year).update(fiscal_year=target_year)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_reviewtemplate_subtitle"),
        ("reports", "0019_standardize_fiscal_year_labels"),
    ]

    operations = [
        migrations.RunPython(relabel_manual_fiscal_years, migrations.RunPython.noop),
    ]
