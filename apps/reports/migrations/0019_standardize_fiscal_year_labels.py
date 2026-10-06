from __future__ import annotations

from datetime import date
from typing import cast

from django.db import migrations


# Every persisted report table that has a date identifying its fiscal period.
# Tables containing manually entered fiscal buckets (PartiesWeek/PayrollWeek)
# intentionally are not rewritten: they have no date from which to derive a
# label safely.
REPORT_METADATA = {
    "WeeklySalesSummary": ("fiscal_period_end", True),
    "RankingSummary": ("fiscal_period_end", True),
    "GiftCardsSummary": ("fiscal_period_end", True),
    "BonusClubSummary": ("fiscal_period_end", True),
    "SegmentsSummary": ("fiscal_period_end", True),
    "ProductReport": ("period_end", False),
    "GanttImport": ("day_date", False),
    "GanttReport": ("week_end", False),
    "MissedOpportunityImport": ("week_end", False),
    "MissedOpportunityReport": ("week_end", False),
    "SegmentReport": ("week_end", False),
}


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _anniversary_for_year(year: int, start_date: date) -> date:
    if start_date.month == 2 and start_date.day == 29:
        return date(year, 2, 29 if _is_leap_year(year) else 28)
    return date(year, start_date.month, start_date.day)


def _start_year_for_day(day: date, start_date: date) -> int:
    anniversary = _anniversary_for_year(day.year, start_date)
    return day.year if day >= anniversary else day.year - 1


def _unique_field_sets(model) -> tuple[tuple[str, ...], ...]:
    field_sets = {
        tuple(constraint.fields)
        for constraint in model._meta.total_unique_constraints
        if getattr(constraint, "fields", None)
    }
    unique_together = model._meta.unique_together
    if isinstance(unique_together, str):
        unique_together = (unique_together,)
    if unique_together:
        field_sets.update(tuple(fields) for fields in unique_together)
    field_sets.update((field.name,) for field in model._meta.fields if field.unique)
    return tuple(field_sets)


def _has_uniqueness_collision(model, row, corrected_year: int) -> bool:
    for unique_fields in _unique_field_sets(model):
        if "fiscal_year" not in unique_fields:
            continue
        lookup = {
            field: corrected_year if field == "fiscal_year" else getattr(row, field)
            for field in unique_fields
        }
        # Database uniqueness constraints do not treat NULL values as equal.
        if any(value is None for value in lookup.values()):
            continue
        if model.objects.exclude(pk=row.pk).filter(**lookup).exists():
            return True
    return False


def standardize_fiscal_year_labels(apps, schema_editor) -> None:
    settings = apps.get_model("core", "FiscalYearSettings").objects.order_by("pk").first()
    start_date = getattr(settings, "fiscal_year_start_date", None) if settings else None
    if not start_date:
        return

    for model_name, (date_field, has_raw_json) in REPORT_METADATA.items():
        model = apps.get_model("reports", model_name)
        for row in model.objects.exclude(**{f"{date_field}__isnull": True}).iterator():
            period_end = getattr(row, date_field)
            corrected_year = _start_year_for_day(period_end, start_date)
            raw_json = getattr(row, "raw_json", None)
            raw_json_dict = cast(dict[str, object], raw_json) if isinstance(raw_json, dict) else {}
            raw_fiscal_obj = raw_json_dict.get("fiscal")
            raw_fiscal = cast(dict[str, object], raw_fiscal_obj) if isinstance(raw_fiscal_obj, dict) else None
            raw_needs_update = isinstance(raw_fiscal, dict) and raw_fiscal.get("fiscal_year") != corrected_year
            if row.fiscal_year == corrected_year and not raw_needs_update:
                continue
            if row.fiscal_year != corrected_year and _has_uniqueness_collision(model, row, corrected_year):
                raise RuntimeError(
                    f"Cannot safely relabel {model_name} pk={row.pk}: "
                    f"FY{corrected_year}/W{row.fiscal_week:02d} already exists"
                )
            updates: dict[str, object] = {"fiscal_year": corrected_year}
            if has_raw_json and raw_needs_update:
                updated_raw_json = dict(raw_json_dict)
                updated_raw_json["fiscal"] = {**cast(dict[str, object], raw_fiscal), "fiscal_year": corrected_year}
                updates["raw_json"] = updated_raw_json
            model.objects.filter(pk=row.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_reviewtemplate_subtitle"),
        ("reports", "0018_reportgoalsettings"),
    ]

    operations = [
        migrations.RunPython(standardize_fiscal_year_labels, migrations.RunPython.noop),
    ]
