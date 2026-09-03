from __future__ import annotations

import io
from datetime import date
from pathlib import Path

from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.navigation import dashboard_tabs, report_tabs, shell_context

from .dashboard import build_six_week_dashboard
from .fiscal import as_dict, calculate_fiscal_week
from .forms import ReportUploadForm
from .models import ReportUpload, WeeklySalesSummary
from .registry import get

REPORTS = {
    1: {
        "label": "Report 1",
        "title": "Report 1: Weekly Sales Summary",
        "subtitle": "Weekly sales uploads, parsed rows, and the live report history.",
        "upload_supported": True,
    },
    2: {"label": "Report 2", "title": "Report 2", "subtitle": "Coming soon.", "upload_supported": False},
    3: {"label": "Report 3", "title": "Report 3", "subtitle": "Coming soon.", "upload_supported": False},
    4: {"label": "Report 4", "title": "Report 4", "subtitle": "Coming soon.", "upload_supported": False},
    5: {"label": "Report 5", "title": "Report 5", "subtitle": "Coming soon.", "upload_supported": False},
    6: {"label": "Report 6", "title": "Report 6", "subtitle": "Coming soon.", "upload_supported": False},
}


def dashboard(request: HttpRequest) -> HttpResponse:
    """Render the dashboard from persisted weekly sales summaries."""

    week_filter = str(request.GET.get("weeks", "all"))
    reports = list(_dashboard_reports())
    payload = build_six_week_dashboard(reports, selection=week_filter, reference_date=date.today())
    uploads = list(ReportUpload.objects.order_by("-uploaded_at", "-id")[:5])
    context = shell_context(
        section="dashboard",
        page_title="Dashboard",
        subtitle="Current week plus the previous five weeks.",
        top_tabs=dashboard_tabs("overview"),
        primary_action={"label": "Open Report 1", "url": reverse("reports:index")},
        dashboard=payload,
        selection=week_filter,
        uploads=uploads,
        empty_state="No persisted weekly reports have been wired in yet.",
    )
    if request.GET.get("format") == "json":
        return JsonResponse(
            {
                "selection": week_filter,
                "dashboard": payload.to_dict(),
                "empty_state": context["empty_state"],
            }
        )
    return render(request, "reports/dashboard.html", context)


def report_section(request: HttpRequest, number: int = 1) -> HttpResponse:
    report = REPORTS.get(number)
    if report is None:
        raise Http404("Unknown report type.")

    uploads = list(ReportUpload.objects.select_related("weekly_sales_summary").order_by("-uploaded_at", "-id")[:5])
    context = shell_context(
        section="reports",
        page_title=report["title"],
        subtitle=report["subtitle"],
        top_tabs=report_tabs(number),
        primary_action={"label": "Open upload form", "url": reverse("reports:history")} if number == 1 else None,
        report=report,
        report_number=number,
        uploads=uploads,
        upload_supported=report["upload_supported"],
    )
    return render(request, "reports/report_section.html", context)


def report_history(request: HttpRequest) -> HttpResponse:
    uploads = ReportUpload.objects.select_related("weekly_sales_summary").order_by("-uploaded_at", "id")
    context = shell_context(
        section="reports",
        page_title="Weekly sales report uploads",
        subtitle="Upload a weekly sales PDF, then open its detail page to download the original file again.",
        top_tabs=report_tabs(1),
        primary_action={"label": "Report 1 overview", "url": reverse("reports:index")},
        form=ReportUploadForm(),
        uploads=uploads,
    )
    return render(request, "reports/history.html", context)


def report_upload(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        return redirect("reports:history")

    form = ReportUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        uploads = ReportUpload.objects.select_related("weekly_sales_summary").order_by("-uploaded_at", "id")
        context = shell_context(
            section="reports",
            page_title="Weekly sales report uploads",
            subtitle="Upload a weekly sales PDF, then open its detail page to download the original file again.",
            top_tabs=report_tabs(1),
            primary_action={"label": "Report 1 overview", "url": reverse("reports:index")},
            form=form,
            uploads=uploads,
        )
        return render(request, "reports/history.html", context, status=400)

    upload = form.save()
    _parse_and_store_summary(upload)
    return redirect("reports:detail", pk=upload.pk)


def report_detail(request: HttpRequest, pk: int) -> HttpResponse:
    upload = get_object_or_404(ReportUpload.objects.select_related("weekly_sales_summary"), pk=pk)
    summary = getattr(upload, "weekly_sales_summary", None)
    context = shell_context(
        section="reports",
        page_title=upload.source_name,
        subtitle="Upload detail and parsed summary.",
        top_tabs=report_tabs(1),
        primary_action={"label": "Upload another PDF", "url": reverse("reports:history")},
        upload=upload,
        summary=summary,
    )
    return render(request, "reports/detail.html", context)


def report_download(request: HttpRequest, pk: int) -> FileResponse:
    upload = get_object_or_404(ReportUpload, pk=pk)
    if not upload.source_file:
        raise Http404("Report upload has no source file.")
    source_path = Path(upload.source_file.path)
    if not source_path.exists():
        raise Http404("Source PDF is missing.")
    response = FileResponse(upload.source_file.open("rb"), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{Path(upload.source_name).name}"'
    return response


def _dashboard_reports():
    for summary in WeeklySalesSummary.objects.select_related("report_upload").order_by("-fiscal_year", "-fiscal_week", "-id"):
        raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        yield {
            "report_type": "weekly_sales",
            "source_name": summary.report_upload.source_name,
            "period_start": summary.fiscal_period_start.isoformat() if summary.fiscal_period_start else None,
            "period_end": summary.fiscal_period_end.isoformat() if summary.fiscal_period_end else None,
            "payload": raw_json,
            "raw_rows": raw_json.get("summary_rows", []),
        }


def _parse_and_store_summary(upload: ReportUpload) -> None:
    try:
        raw_text = _extract_pdf_text(upload.source_file.path)
        report = get("weekly_sales").parse(raw_text)
        fiscal = report.payload.get("fiscal") if isinstance(report.payload, dict) else None
        if not isinstance(fiscal, dict):
            fiscal = _fiscal_from_report(report)
        fiscal_week = fiscal.get("fiscal_week_number", fiscal.get("fiscal_week"))
        WeeklySalesSummary.objects.update_or_create(
            report_upload=upload,
            defaults={
                "fiscal_year": int(fiscal["fiscal_year"]),
                "fiscal_week": int(fiscal_week),
                "fiscal_period_start": _parse_date(report.period_start),
                "fiscal_period_end": _parse_date(report.period_end),
                "raw_json": report.payload,
            },
        )
        upload.parse_status = "parsed"
        upload.parse_error = ""
        upload.parsed_at = timezone.now()
        upload.source_name = Path(upload.source_name).name
        upload.save(update_fields=["source_name", "parse_status", "parse_error", "parsed_at"])
        return None
    except Exception as exc:  # pragma: no cover - exercised through user-facing failure path
        upload.parse_status = "failed"
        upload.parse_error = str(exc)
        upload.parsed_at = timezone.now()
        upload.save(update_fields=["parse_status", "parse_error", "parsed_at"])


def _fiscal_from_report(report) -> dict[str, object]:
    if report.period_start and report.period_end:
        return as_dict(calculate_fiscal_week(report.period_start, report.period_end))
    raise ValueError("Weekly sales report is missing period dates.")


def _extract_pdf_text(path: str) -> str:
    data = Path(path).read_bytes()
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            table_text = _extract_primary_table_text(pdf)
            extracted = "\n\n".join((page.extract_text() or "").strip() for page in pdf.pages).strip()
            if table_text and extracted:
                return f"{table_text}\n\n{extracted}"
            if table_text:
                return table_text
            if extracted:
                return extracted
    except Exception:
        pass

    decoded = data.decode("latin1", errors="ignore").replace("\x00", "")
    if decoded.strip():
        return decoded

    raise ValueError("Unable to extract text from the uploaded PDF.")


def _extract_primary_table_text(pdf) -> str:
    for page in pdf.pages:
        tables = page.extract_tables() or []
        best_table: list[list[str | None]] | None = None
        best_width = 0
        for table in tables:
            if len(table) < 2:
                continue
            width = max((len(row) for row in table if row), default=0)
            if width > best_width:
                best_width = width
                best_table = table
        if best_table and len(best_table) >= 2:
            lines: list[str] = []
            header = _clean_pdf_cells(best_table[0])
            data = _clean_pdf_cells(best_table[1])
            for label, value in zip(header, data):
                if not label or not value:
                    continue
                lines.append(f"{label}: {value}")
            if lines:
                return "\n".join(lines)
    return ""


def _clean_pdf_cells(row) -> list[str]:
    cleaned: list[str] = []
    for cell in row or []:
        if cell is None:
            cleaned.append("")
            continue
        text = " ".join(str(cell).split())
        cleaned.append(text.strip())
    return cleaned


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
