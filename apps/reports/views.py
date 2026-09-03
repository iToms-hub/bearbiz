from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .dashboard import build_six_week_dashboard
from .fiscal import as_dict, calculate_fiscal_week
from .forms import ReportUploadForm
from .models import ReportUpload, WeeklySalesSummary
from .registry import get


def dashboard(request: HttpRequest) -> HttpResponse:
    """Render the dashboard from persisted weekly sales summaries."""

    week_filter = request.GET.get("weeks", "all")
    reports = list(_dashboard_reports())
    payload = build_six_week_dashboard(reports, selection=week_filter, reference_date=date.today())
    context = {
        "dashboard": payload,
        "selection": week_filter,
        "empty_state": "No persisted weekly reports have been wired in yet.",
        "uploads": ReportUpload.objects.order_by("-uploaded_at", "-id"),
    }
    if request.GET.get("format") == "json":
        return JsonResponse({
            "selection": week_filter,
            "dashboard": payload.to_dict(),
            "empty_state": context["empty_state"],
        })
    return render(request, "reports/dashboard.html", context)


def report_history(request: HttpRequest) -> HttpResponse:
    return report_upload(request)


def report_upload(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        return _render_upload_index(request, ReportUploadForm())

    form = ReportUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return _render_upload_index(request, form, status=400)

    upload = form.save()
    _parse_and_store_summary(upload)
    return redirect("reports:detail", pk=upload.pk)


def report_detail(request: HttpRequest, pk: int) -> HttpResponse:
    upload = get_object_or_404(ReportUpload.objects.select_related("weekly_sales_summary"), pk=pk)
    summary = getattr(upload, "weekly_sales_summary", None)
    return render(request, "reports/detail.html", {"upload": upload, "summary": summary})


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


def _render_upload_index(request: HttpRequest, form: ReportUploadForm, status: int = 200) -> HttpResponse:
    uploads = ReportUpload.objects.select_related("weekly_sales_summary").order_by("-uploaded_at", "id")
    return render(request, "reports/history.html", {"form": form, "uploads": uploads}, status=status)


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
