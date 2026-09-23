from __future__ import annotations

import io
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from django.db import transaction
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.navigation import shell_context
from apps.core.models import FiscalYearSettings
from .forms import ReportUploadForm
from .models import PartiesSummary, PartiesWeek, ReportUpload
from .modules.parties import PartiesReport
from .payroll_views import _fiscal_year as payroll_fiscal_year
from .payroll_views import current_payroll_month, payroll_month_labels, payroll_month_layout, payroll_week_ending


HEADERS = ["Week", "Week Date", "TTL Parties Held TY", "TTL Parties Held LY", "Held +/-", "TTL Parties Booked TY", "TTL Parties Booked LY", "Booked +/-"]
DIRECT_EDITABLE_FIELDS = {
    "held_current": "held_current",
    "held_previous": "held_previous",
    "booked_current": "booked_current",
    "booked_previous": "booked_previous",
}


def _direct_decimal(value: str) -> Decimal | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        parsed = Decimal(text)
        if not parsed.is_finite():
            raise ValueError("Enter a valid number.")
        return parsed.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("Enter a valid number.") from exc


def _direct_display(value: Decimal | None) -> str:
    return "" if value is None else f"{value:,.2f}"


def _direct_total(rows: list[PartiesWeek]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in (*DIRECT_EDITABLE_FIELDS.values(), "held_variance", "booked_variance"):
        values = [getattr(row, field) for row in rows if getattr(row, field) is not None]
        result[field] = _direct_display(sum(values, Decimal("0"))) if values else ""
    return result


def _direct_totals(fiscal_year: int, month: int) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    rows = list(PartiesWeek.objects.filter(fiscal_year=fiscal_year, fiscal_month__lte=month))
    month_rows = [row for row in rows if row.fiscal_month == month]
    quarter_start = ((month - 1) // 3) * 3 + 1
    quarter_rows = [row for row in rows if quarter_start <= row.fiscal_month <= month]
    return _direct_total(month_rows), _direct_total(quarter_rows), _direct_total(rows)


def parties_dashboard_summary() -> dict[str, object] | None:
    fiscal_year = payroll_fiscal_year()
    latest = PartiesWeek.objects.filter(fiscal_year=fiscal_year).order_by("-fiscal_week").first()
    if latest is None:
        return None
    month_total, quarter_total, year_total = _direct_totals(fiscal_year, latest.fiscal_month)
    headers = ["Period", "Held Current Year", "Held Previous Year", "Held +/-", "Booked Current Year", "Booked Previous Year", "Booked +/-"]
    rows = [
        {"values": ["Last Fiscal Week", _direct_display(latest.held_current), _direct_display(latest.held_previous), _direct_display(latest.held_variance), _direct_display(latest.booked_current), _direct_display(latest.booked_previous), _direct_display(latest.booked_variance)], "row_class": "review-parties-latest"},
        {"values": ["Current Month", month_total["held_current"], month_total["held_previous"], month_total["held_variance"], month_total["booked_current"], month_total["booked_previous"], month_total["booked_variance"]], "row_class": "review-parties-period"},
        {"values": ["Current Quarter", quarter_total["held_current"], quarter_total["held_previous"], quarter_total["held_variance"], quarter_total["booked_current"], quarter_total["booked_previous"], quarter_total["booked_variance"]], "row_class": "review-parties-period"},
        {"values": ["Current Year", year_total["held_current"], year_total["held_previous"], year_total["held_variance"], year_total["booked_current"], year_total["booked_previous"], year_total["booked_variance"]], "row_class": "review-parties-year"},
    ]
    return {"headers": headers, "rows": rows, "latest_month": latest.fiscal_month, "latest_week": latest.fiscal_week}


def _direct_context(fiscal_year: int, month: int, submitted: Mapping[str, str] | None = None) -> tuple[list[dict[str, str | int]], dict[str, str], dict[str, str], dict[str, str]]:
    stored = {
        row.fiscal_week: row
        for row in PartiesWeek.objects.filter(fiscal_year=fiscal_year, fiscal_month=month)
    }
    rows: list[dict[str, str | int]] = []
    for week in payroll_month_layout()[month]:
        row = stored.get(week)
        rows.append({
            "week": week,
            "week_ending": payroll_week_ending(fiscal_year, week).strftime("%m/%d/%y"),
            "held_current": submitted.get(f"held_current_{week}", _direct_display(row.held_current if row else None)) if submitted is not None else _direct_display(row.held_current if row else None),
            "held_previous": submitted.get(f"held_previous_{week}", _direct_display(row.held_previous if row else None)) if submitted is not None else _direct_display(row.held_previous if row else None),
            "held_variance": _direct_display(row.held_variance if row else None),
            "booked_current": submitted.get(f"booked_current_{week}", _direct_display(row.booked_current if row else None)) if submitted is not None else _direct_display(row.booked_current if row else None),
            "booked_previous": submitted.get(f"booked_previous_{week}", _direct_display(row.booked_previous if row else None)) if submitted is not None else _direct_display(row.booked_previous if row else None),
            "booked_variance": _direct_display(row.booked_variance if row else None),
        })
    return rows, *_direct_totals(fiscal_year, month)


def _extract(upload: ReportUpload) -> str:
    import pdfplumber
    with upload.source_file.open("rb") as source:
        data = source.read()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _parse(upload: ReportUpload) -> PartiesSummary:
    parsed = PartiesReport().parse(_extract(upload))
    fiscal = parsed.payload["fiscal"]
    if not fiscal.get("fiscal_year") or not fiscal.get("fiscal_week_number"):
        raise ValueError("Unable to determine fiscal year/week from report.")
    incoming_rows = list(parsed.raw_rows)
    historical_rows: dict[int, dict[str, Any]] = {}
    conflicts: list[int] = []
    for prior in PartiesSummary.objects.filter(fiscal_year=fiscal["fiscal_year"]):
        for row in prior.rows if isinstance(prior.rows, list) else []:
            if not isinstance(row, dict) or not row.get("week_number"):
                continue
            week_number = int(row["week_number"])
            if week_number in historical_rows and historical_rows[week_number] != row:
                continue
            historical_rows[week_number] = row
    merged_rows: dict[int, dict[str, Any]] = dict(historical_rows)
    for row in incoming_rows:
        week_number = int(row.get("week_number") or 0)
        if week_number in historical_rows:
            if historical_rows[week_number] != row:
                conflicts.append(week_number)
            continue
        if week_number:
            merged_rows[week_number] = row
    rows = [merged_rows[week] for week in sorted(merged_rows)]
    payload = dict(parsed.payload)
    payload["rows"] = rows
    summary = PartiesSummary.objects.create(report_upload=upload, fiscal_year=fiscal["fiscal_year"], fiscal_week=fiscal["fiscal_week_number"], rows=rows, raw_json=payload, parse_version=PartiesReport.parse_version)
    upload.parse_status = "conflict" if conflicts else "parsed"
    upload.parse_error = (
        "Historical Parties conflict for week(s): " + ", ".join(str(week) for week in sorted(set(conflicts)))
        if conflicts else ""
    )
    upload.parsed_at = timezone.now()
    upload.save(update_fields=["parse_status", "parse_error", "parsed_at"])
    return summary


def _value(value: object) -> str:
    return "" if value is None else str(value)


def _rows(summary: PartiesSummary) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    month_totals: dict[int, list[dict[str, Any]]] = defaultdict(list)
    source_rows = summary.rows if isinstance(summary.rows, list) else []
    settings = FiscalYearSettings.current()
    pattern = str(settings.calendar_pattern or "454")
    month_lengths = [int(value) for _ in range(4) for value in pattern]

    def fiscal_month_for_week(week_number: int) -> int:
        remaining = max(week_number - 1, 0)
        for month, length in enumerate(month_lengths, start=1):
            if remaining < length:
                return month
            remaining -= length
        return 12

    def emit_month(month: int) -> None:
        result.append(_total_row(f"Month Totals (Fiscal Month {month})", month_totals[month], "report-summary-row report-month-total"))
        if month in (3, 6, 9, 12):
            quarter = month // 3
            quarter_rows = [item for fiscal_month, items in month_totals.items() if month - 2 <= fiscal_month <= month for item in items]
            result.append(_total_row(f"Quarter Totals (Q{quarter})", quarter_rows, "report-summary-row report-quarter-total"))

    current_month: int | None = None
    for position, row in enumerate(source_rows, start=1):
        if not isinstance(row, dict):
            continue
        week_number = int(row.get("week_number") or position)
        month = fiscal_month_for_week(week_number)
        if current_month is not None and month != current_month:
            emit_month(current_month)
        current_month = month
        month_totals[month].append(row)
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        held = metrics.get("ttl_held", {})
        booked = metrics.get("ttl_booked", {})
        week_date = row.get("week_date") or ""
        if not week_date and settings.fiscal_year_start_date:
            week_date = (settings.fiscal_year_start_date + timedelta(weeks=week_number - 1)).isoformat()
        try:
            week_date = date.fromisoformat(str(week_date)).strftime("%m/%d/%y")
        except (TypeError, ValueError):
            week_date = ""
        result.append({"values": [f"Week {week_number}", week_date, _value(held.get("current")), _value(held.get("previous")), _value(held.get("variance")), _value(booked.get("current")), _value(booked.get("previous")), _value(booked.get("variance"))], "row_class": "report-week-row"})
    if current_month is not None:
        emit_month(current_month)
    result.append(_total_row("Fiscal Year Total", [item for rows in month_totals.values() for item in rows], "report-summary-row report-year-total"))
    return result


def _total_row(label: str, rows: list[dict[str, Any]], row_class: str) -> dict[str, Any]:
    totals: list[str] = []
    for group in ("ttl_held", "ttl_booked", "comp_held"):
        for field in ("current", "previous", "variance"):
            values = []
            for row in rows:
                metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
                metric = metrics.get(group) if isinstance(metrics.get(group), dict) else {}
                if isinstance(metric.get(field), (int, float)):
                    values.append(metric[field])
            totals.extend([str(sum(values)) if values else ""])
    return {"values": [label, "", totals[0], totals[1], totals[2], totals[3], totals[4], totals[5]], "row_class": row_class}


def index(request: HttpRequest) -> HttpResponse:
    default_month = current_payroll_month()
    month = default_month
    raw_month = request.POST.get("month") or request.GET.get("month")
    try:
        month = int(str(raw_month)) if raw_month is not None else default_month
    except ValueError:
        month = default_month
    month = month if 1 <= month <= 12 else default_month
    fiscal_year = payroll_fiscal_year()
    errors: list[str] = []

    if request.method == "POST":
        try:
            with transaction.atomic():
                for week in payroll_month_layout()[month]:
                    values = {
                        field: _direct_decimal(request.POST.get(f"{input_name}_{week}", ""))
                        for input_name, field in DIRECT_EDITABLE_FIELDS.items()
                    }
                    if not any(value is not None for value in values.values()):
                        PartiesWeek.objects.filter(fiscal_year=fiscal_year, fiscal_week=week).delete()
                        continue
                    PartiesWeek.objects.update_or_create(
                        fiscal_year=fiscal_year,
                        fiscal_week=week,
                        defaults={"fiscal_month": month, **values},
                    )
        except ValueError as exc:
            errors.append(str(exc))
        else:
            return redirect(f"/parties/?month={month}")

    parties_rows, parties_total, parties_quarter_total, parties_year_total = _direct_context(fiscal_year, month, request.POST if errors else None)
    context = shell_context(
        section="parties",
        page_title="Parties",
        subtitle="Enter weekly parties held and booked by fiscal month.",
        parties_tabs=[{"number": number, "label": label} for number, label in payroll_month_labels(fiscal_year).items()],
        selected_parties_month=month,
        parties_rows=parties_rows,
        parties_total=parties_total,
        parties_quarter_total=parties_quarter_total,
        parties_year_total=parties_year_total,
        parties_errors=errors,
    )
    return render(request, "parties/index.html", context, status=400 if errors else 200)


def upload_page(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ReportUploadForm(request.POST, request.FILES)
        if form.is_valid():
            upload = form.save(report_type="parties")
            try:
                _parse(upload)
            except Exception as exc:
                upload.parse_status = "failed"
                upload.parse_error = str(exc)
                upload.save(update_fields=["parse_status", "parse_error"])
            return redirect("parties-uploads")
    else:
        form = ReportUploadForm()
    context = shell_context(section="parties", page_title="Parties uploads", subtitle="Upload and manage Parties PDFs.", form=form, uploads=ReportUpload.objects.filter(report_type="parties"), upload_url=request.path, parties_page_url="/parties/")
    return render(request, "parties/uploads.html", context, status=400 if request.method == "POST" and not form.is_valid() else 200)


@require_POST
def delete(request: HttpRequest, pk: int) -> HttpResponse:
    upload = get_object_or_404(ReportUpload, pk=pk, report_type="parties")
    if upload.source_file and upload.source_file.name:
        upload.source_file.delete(save=False)
    upload.delete()
    return redirect("parties-uploads")


def download(request: HttpRequest, pk: int) -> FileResponse:
    upload = get_object_or_404(ReportUpload, pk=pk, report_type="parties")
    if not upload.source_file:
        raise Http404("Parties PDF is missing.")
    return FileResponse(upload.source_file.open("rb"), content_type="application/pdf")
