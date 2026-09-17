from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date, timedelta
from typing import Any

from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.core.models import FiscalYearSettings
from apps.core.navigation import shell_context

from .models import PayrollWeek

FISCAL_MONTH_WEEK_COUNTS = (4, 5, 4) * 4
EDITABLE_FIELDS = {
    "sales_plan": "sales_plan",
    "trend_percent": "trend_percent",
    "sun": "sun",
    "mon": "mon",
    "tue": "tue",
    "wed": "wed",
    "thu": "thu",
    "fri": "fri",
    "sat": "sat",
    "labor_target": "labor_calculator_target_hours",
}


def payroll_month_layout() -> dict[int, list[int]]:
    """Return the 12 fiscal months mapped to their 4-5-4 week numbers."""
    layout: dict[int, list[int]] = {}
    week = 1
    for month, count in enumerate(FISCAL_MONTH_WEEK_COUNTS, start=1):
        layout[month] = list(range(week, week + count))
        week += count
    return layout


def payroll_fiscal_year_start(fiscal_year: int) -> date:
    """Return the Sunday starting the requested fixed 52-week fiscal year."""
    settings = FiscalYearSettings.current()
    if settings.fiscal_year_start_date:
        configured_start = date(
            settings.fiscal_year_start_date.year,
            settings.fiscal_year_start_date.month,
            settings.fiscal_year_start_date.day,
        )
        reference_fiscal_year = configured_start.year + 1
        start = configured_start - timedelta(days=(configured_start.weekday() + 1) % 7)
        return start + timedelta(days=(fiscal_year - reference_fiscal_year) * 52 * 7)
    return settings.fiscal_year_end(fiscal_year - 1) + timedelta(days=1)


def payroll_month_labels(fiscal_year: int) -> dict[int, str]:
    """Name fiscal months from their calendar start month (Feb, Mar, ...)."""
    start = payroll_fiscal_year_start(fiscal_year)
    return {
        month: date(start.year + (start.month - 1 + month - 1) // 12, (start.month - 1 + month - 1) % 12 + 1, 1).strftime("%b")
        for month in range(1, 13)
    }


def payroll_tabs(fiscal_year: int) -> list[dict[str, int | str]]:
    labels = payroll_month_labels(fiscal_year)
    return [{"number": month, "label": labels[month]} for month in range(1, 13)]


def payroll_week_ending(fiscal_year: int, week: int) -> date:
    """Return the Saturday ending a fiscal week."""
    return payroll_fiscal_year_start(fiscal_year) + timedelta(days=week * 7 - 1)


def _selected_month(request: HttpRequest) -> int:
    try:
        month = int(request.POST.get("month") or request.GET.get("month") or "1")
    except ValueError:
        month = 1
    return month if 1 <= month <= 12 else 1


def _fiscal_year() -> int:
    settings = FiscalYearSettings.current()
    return settings.fiscal_year_for_date(timezone.localdate())


def _parse_decimal(value: str) -> Decimal | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
        if not parsed.is_finite():
            raise ValueError("Enter a valid number.")
        return parsed.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("Enter a valid number.") from exc


def _display_number(value: Decimal | None, *, money: bool = False, percent: bool = False) -> str:
    if value is None:
        return ""
    value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if money:
        return f"${value:,.2f}"
    if percent:
        return f"{value:,.2f}%"
    return f"{value:,.2f}"


def _row_context(row: PayrollWeek, fiscal_year: int, week: int) -> dict[str, Any]:
    def value_or_empty(value: Decimal | None) -> Decimal | str:
        return value if value is not None else ""

    return {
        "week": week,
        "week_ending": payroll_week_ending(fiscal_year, week).strftime("%m/%d/%y"),
        "sales_plan": value_or_empty(row.sales_plan),
        "trend_percent": value_or_empty(row.trend_percent),
        "sun": value_or_empty(row.sun),
        "mon": value_or_empty(row.mon),
        "tue": value_or_empty(row.tue),
        "wed": value_or_empty(row.wed),
        "thu": value_or_empty(row.thu),
        "fri": value_or_empty(row.fri),
        "sat": value_or_empty(row.sat),
        "days": [(day, value_or_empty(getattr(row, day.lower()))) for day in ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")],
        "labor_target": value_or_empty(row.labor_calculator_target_hours),
        "actual_sales": _display_number(row.actual_sales, money=True),
        "total_hours": _display_number(row.total_hours_actual_scheduled),
        "current_variance": _display_number(row.current_variance),
    }


def _summary_context(rows: list[PayrollWeek]) -> dict[str, str]:
    actual_sales = sum((row.actual_sales for row in rows if row.actual_sales is not None), Decimal("0"))
    total_hours = sum((row.total_hours_actual_scheduled for row in rows), Decimal("0"))
    target_hours = sum((row.labor_calculator_target_hours for row in rows if row.labor_calculator_target_hours is not None), Decimal("0"))
    return {
        "actual_sales": _display_number(actual_sales, money=True),
        "total_hours": _display_number(total_hours),
        "target_hours": _display_number(target_hours),
        "variance": _display_number(total_hours - target_hours),
        "current_percent": _display_number((total_hours / target_hours * Decimal("100")).quantize(Decimal("0.01")), percent=True) if target_hours else "",
        "variance_101": _display_number(target_hours * Decimal("1.01") - total_hours),
        "variance_95": _display_number(target_hours * Decimal("0.95") - total_hours),
    }


def payroll_dashboard_summary(fiscal_year: int | None = None) -> dict[str, str] | None:
    """Return the latest saved Payroll week for dashboard surfaces."""
    fiscal_year = fiscal_year or _fiscal_year()
    row = PayrollWeek.objects.filter(fiscal_year=fiscal_year).order_by("-fiscal_week").first()
    if row is None or row.labor_calculator_target_hours is None:
        return None
    total_hours = row.total_hours_actual_scheduled
    target = row.labor_calculator_target_hours
    return {
        "week": str(row.fiscal_week),
        "week_ending": payroll_week_ending(fiscal_year, row.fiscal_week).strftime("%m/%d/%y"),
        "total_hours": _display_number(total_hours),
        "target_hours": _display_number(target),
        "variance": _display_number(row.current_variance),
        "percent": f"{(total_hours / target * Decimal('100')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):,.1f}%" if target else "",
    }


def index(request: HttpRequest) -> HttpResponse:
    month = _selected_month(request)
    fiscal_year = _fiscal_year()
    layout = payroll_month_layout()
    errors: list[str] = []

    if request.method == "POST":
        try:
            with transaction.atomic():
                for week in layout[month]:
                    values: dict[str, Decimal | None] = {}
                    for input_name, field_name in EDITABLE_FIELDS.items():
                        values[field_name] = _parse_decimal(request.POST.get(f"{input_name}_{week}", ""))
                    if not any(value is not None for value in values.values()):
                        PayrollWeek.objects.filter(fiscal_year=fiscal_year, fiscal_week=week).delete()
                        continue
                    PayrollWeek.objects.update_or_create(
                        fiscal_year=fiscal_year,
                        fiscal_week=week,
                        defaults={"fiscal_month": month, **values},
                    )
        except ValueError as exc:
            errors.append(str(exc))
        else:
            return redirect(f"/payroll/?month={month}")

    stored = {
        row.fiscal_week: row
        for row in PayrollWeek.objects.filter(fiscal_year=fiscal_year, fiscal_month=month)
    }
    rows = [_row_context(stored.get(week, PayrollWeek()), fiscal_year, week) for week in layout[month]]
    summary_rows = [stored[week] for week in layout[month] if week in stored]
    context = shell_context(
        section="payroll",
        page_title="Payroll",
        subtitle="Enter and save weekly payroll data by fiscal month.",
        payroll_tabs=payroll_tabs(fiscal_year),
        selected_payroll_month=month,
        payroll_rows=rows,
        payroll_summary=_summary_context(summary_rows),
        payroll_errors=errors,
    )
    return render(request, "payroll/index.html", context, status=400 if errors else 200)
