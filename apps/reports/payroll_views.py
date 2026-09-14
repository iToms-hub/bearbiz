from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from typing import Any

from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.navigation import shell_context
from apps.reports.fiscal import calculate_fiscal_week

from .forms import ReportUploadForm
from .models import PayrollSummary, ReportUpload
from .modules.payroll import PayrollReport


def _extract(upload: ReportUpload) -> str:
    import pdfplumber

    with upload.source_file.open("rb") as source:
        data = source.read()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def _parse(upload: ReportUpload) -> PayrollSummary:
    parsed = PayrollReport().parse(_extract(upload))
    payload = parsed.payload
    source_date = date.fromisoformat(parsed.period_start) if parsed.period_start else None
    rows = payload.get("rows", [])
    summary = PayrollSummary.objects.create(
        report_upload=upload,
        source_date=source_date,
        source_month=source_date.month if source_date else None,
        source_week=_int(payload.get("source_week")),
        current_week=not bool(source_date),
        rows=rows if isinstance(rows, list) else [],
        monthly_summary=payload.get("monthly_summary", {}),
        raw_json=payload,
        parse_version=int(payload.get("parse_version", 1)),
    )
    upload.parse_status = "parsed"
    upload.parse_error = ""
    upload.parsed_at = timezone.now()
    upload.save(update_fields=["parse_status", "parse_error", "parsed_at"])
    return summary


def _int(value: object) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _refresh_stale_summary(summary: PayrollSummary) -> None:
    if summary.parse_version >= PayrollReport.parse_version or not summary.report_upload.source_file:
        return
    parsed = PayrollReport().parse(_extract(summary.report_upload))
    payload = parsed.payload
    source_date = date.fromisoformat(parsed.period_start) if parsed.period_start else None
    summary.source_date = source_date
    summary.source_month = source_date.month if source_date else None
    summary.source_week = _int(payload.get("source_week"))
    summary.current_week = not bool(source_date)
    summary.rows = payload.get("rows", []) if isinstance(payload.get("rows"), list) else []
    summary.monthly_summary = payload.get("monthly_summary", {})
    summary.raw_json = payload
    summary.parse_version = int(payload.get("parse_version", PayrollReport.parse_version))
    summary.save(update_fields=["source_date", "source_month", "source_week", "current_week", "rows", "monthly_summary", "raw_json", "parse_version", "updated_at"])


def _latest() -> list[PayrollSummary]:
    latest: dict[tuple[object, object], PayrollSummary] = {}
    for summary in PayrollSummary.objects.select_related("report_upload").order_by("-created_at", "-id"):
        _refresh_stale_summary(summary)
        key = (summary.source_date, summary.source_week) if summary.source_date else (None, summary.id)
        latest.setdefault(key, summary)
    return list(sorted(latest.values(), key=lambda item: (item.source_date or date.min, item.id), reverse=True))


def _week_ending_date(value: object) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return date.fromisoformat(text) if fmt == "%Y-%m-%d" else datetime.strptime(text, fmt).date()
        except (ValueError, TypeError):
            pass
    return None


def _display_value(column: str, value: object) -> object:
    if value in (None, ""):
        return ""
    if column in {"Sales Plan", "Actual Sales"} and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"${value:,.0f}"
    if column == "Trend" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.1f}%"
    if column == "Current +/-" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.2f}"
    return value


def _display_row(row: dict[str, Any]) -> list[object]:
    week_ending = _week_ending_date(row.get("NOTES"))
    fiscal_week = calculate_fiscal_week(week_ending - timedelta(days=6), week_ending).fiscal_week_number if week_ending else row.get("Week")
    values = []
    for column, source_column in zip(PayrollReport.display_columns, PayrollReport.display_source_columns):
        value = fiscal_week if column == "Week" else row.get(source_column)
        values.append(_display_value(column, value))
    return values


def _summary_store_totals(summary: PayrollSummary) -> tuple[float, float]:
    total_hours = 0.0
    current_variance = 0.0
    for row in summary.rows:
        hours = row.get("Total Hours Actual + Scheduled")
        variance = row.get("Current +/-")
        if isinstance(hours, (int, float)) and not isinstance(hours, bool):
            total_hours += hours
        if isinstance(variance, (int, float)) and not isinstance(variance, bool):
            current_variance += variance
    return total_hours, current_variance


def _numeric_summary_value(summary: PayrollSummary, field: str) -> float:
    value = summary.monthly_summary.get(field) if isinstance(summary.monthly_summary, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return sum(
        float(row.get(field))
        for row in summary.rows
        if isinstance(row.get(field), (int, float)) and not isinstance(row.get(field), bool)
    )


def _timeframe_totals(summaries: list[PayrollSummary]) -> dict[str, float]:
    fields = ("Sales Plan", "Actual Sales", "Total Hours Actual + Scheduled", "Labor Calculator Target Hours", "Current +/-")
    totals = {field: 0.0 for field in fields}
    for summary in summaries:
        totals["Sales Plan"] += _numeric_summary_value(summary, "Sales Plan")
        totals["Actual Sales"] += _numeric_summary_value(summary, "Actual Sales")
        hours, variance = _summary_store_totals(summary)
        totals["Total Hours Actual + Scheduled"] += hours
        totals["Labor Calculator Target Hours"] += _numeric_summary_value(summary, "Labor Calculator Target Hours")
        totals["Current +/-"] += variance
    return totals


def _percentage_class(value: float) -> str:
    if 90 <= value < 95:
        return "payroll-percent-green"
    if 95 <= value <= 101:
        return "payroll-percent-blue"
    return "payroll-percent-red"


def index(request: HttpRequest) -> HttpResponse:
    form = ReportUploadForm()
    summaries = _latest()
    month = request.GET.get("month", "")
    quarter = request.GET.get("quarter", "")
    year = request.GET.get("year", "")
    if year.isdigit():
        summaries = [item for item in summaries if item.source_date and item.source_date.year == int(year)]
    if month.isdigit():
        summaries = [item for item in summaries if item.source_date and item.source_date.month == int(month)]
    if quarter.isdigit():
        q = int(quarter)
        summaries = [item for item in summaries if item.source_date and ((item.source_date.month - 1) // 3 + 1) == q]
    display_rows = []
    for summary in summaries:
        for row in summary.rows:
            display_rows.append({"values": _display_row(row), "summary": summary})
    if summaries:
        totals = _timeframe_totals(summaries)
        trend = ((totals["Actual Sales"] - totals["Sales Plan"]) / totals["Sales Plan"] * 100) if totals["Sales Plan"] else None
        month_row = {
            "Week": "Month Totals",
            "Sales Plan": totals["Sales Plan"],
            "Trend % from Bearnet": trend,
            "Actual Sales": totals["Actual Sales"],
            "Total Hours Actual + Scheduled": totals["Total Hours Actual + Scheduled"],
            "Labor Calculator Target Hours": totals["Labor Calculator Target Hours"],
            "Current +/-": totals["Current +/-"],
        }
        display_rows.append({"values": _display_row(month_row), "row_class": "report-summary-row report-store-total-row"})
        actual_vs_earned = (totals["Total Hours Actual + Scheduled"] / totals["Labor Calculator Target Hours"] * 100) if totals["Labor Calculator Target Hours"] else None
        earned_values = [""] * len(PayrollReport.display_columns)
        earned_values[0] = "Actual vs Earned"
        earned_values[PayrollReport.display_columns.index("Current +/-")] = f"{actual_vs_earned:.1f}%" if actual_vs_earned is not None else ""
        display_rows.append({
            "values": earned_values,
            "row_class": "report-summary-row report-earned-row",
            "current_percent_class": _percentage_class(actual_vs_earned) if actual_vs_earned is not None else "",
        })
    context = shell_context(
        section="payroll", page_title="Payroll", subtitle="Weekly payroll tracker and source-faithful monthly labor planning.",
        upload_page_url="/payroll/uploads/", summaries=summaries, payroll_columns=PayrollReport.display_columns,
        payroll_current_index=PayrollReport.display_columns.index("Current +/-"),
        payroll_rows=display_rows, selected_month=month, selected_quarter=quarter, selected_year=year,
    )
    return render(request, "payroll/index.html", context)


def upload_page(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ReportUploadForm(request.POST, request.FILES)
        if form.is_valid():
            upload = form.save(report_type="payroll")
            try:
                _parse(upload)
            except Exception as exc:
                upload.parse_status = "failed"
                upload.parse_error = str(exc)
                upload.save(update_fields=["parse_status", "parse_error"])
            return redirect("payroll-uploads")
    else:
        form = ReportUploadForm()
    context = shell_context(
        section="payroll", page_title="Payroll uploads", subtitle="Upload and manage Payroll PDFs.",
        form=form, uploads=ReportUpload.objects.filter(report_type="payroll"), upload_url=request.path,
        payroll_page_url="/payroll/",
    )
    return render(request, "payroll/uploads.html", context, status=400 if request.method == "POST" and not form.is_valid() else 200)


@require_POST
def delete(request: HttpRequest, pk: int) -> HttpResponse:
    upload = get_object_or_404(ReportUpload, pk=pk, report_type="payroll")
    if upload.source_file and upload.source_file.name:
        upload.source_file.delete(save=False)
    upload.delete()
    return redirect("payroll-uploads")


def download(request: HttpRequest, pk: int) -> FileResponse:
    upload = get_object_or_404(ReportUpload, pk=pk, report_type="payroll")
    if not upload.source_file:
        raise Http404("Payroll PDF is missing.")
    return FileResponse(upload.source_file.open("rb"), content_type="application/pdf")
