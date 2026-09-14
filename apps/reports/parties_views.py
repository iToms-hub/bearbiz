from __future__ import annotations

import io
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.navigation import shell_context
from apps.core.models import FiscalYearSettings
from .forms import ReportUploadForm
from .models import PartiesSummary, ReportUpload
from .modules.parties import PartiesReport


HEADERS = ["Week", "Week Date", "TTL Parties Held TY", "TTL Parties Held LY", "Held +/-", "TTL Parties Booked TY", "TTL Parties Booked LY", "Booked +/-"]


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
    summary = PartiesSummary.objects.order_by("-fiscal_year", "-fiscal_week", "-id").first()
    context = shell_context(section="parties", page_title="Parties", subtitle="Weekly parties held and booked by fiscal month.", parties_headers=HEADERS, parties_rows=_rows(summary) if summary else [], parties_summary=summary, upload_page_url="/parties/uploads/")
    return render(request, "parties/index.html", context)


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
