from __future__ import annotations

from datetime import date

from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.models import FiscalYearSettings
from apps.core.navigation import shell_context

from .forms import MissedOpportunityUploadForm
from .missed_opportunities import parse_missed_opportunity_report
from .models import MissedOpportunityImport, MissedOpportunityReport

METRIC_HEADERS = (
    "Day", "Store Sales", "Traffic", "STAR", "Trans", "Conversion", "DPT", "UPT",
    "Missed Customers", "Missed Store Sales",
)


def _settings() -> FiscalYearSettings:
    return FiscalYearSettings.current()


def _current_fiscal_year_week() -> tuple[int, int]:
    settings = _settings()
    today = timezone.localdate()
    return settings.fiscal_year_for_date(today), settings.fiscal_week_for_date(today)


def _display_row(row: dict) -> dict:
    return {
        "values": [
            row.get("day", row.get("label", "")), row.get("store_sales", ""), row.get("traffic", ""),
            row.get("star", ""), row.get("trans", ""), row.get("conversion", ""), row.get("dpt", ""),
            row.get("upt", ""), row.get("missed_customers", ""), row.get("missed_store_sales", ""),
        ],
        "highlight": bool(row.get("has_missed_opportunity")),
    }


def _display_summary(label: str, row: dict) -> dict:
    shaped = _display_row({**row, "label": label})
    shaped["values"][0] = label
    return shaped


def _context(request: HttpRequest, selected_week: int, fiscal_year: int, form=None, message="", error="") -> dict:
    reports = list(MissedOpportunityReport.objects.filter(fiscal_year=fiscal_year).order_by("-fiscal_week"))
    selected = next((report for report in reports if report.fiscal_week == selected_week), None)
    choices = [
        {"fiscal_week": report.fiscal_week, "week_end": report.week_end.strftime("%-m/%-d/%Y"), "selected": report.fiscal_week == selected_week}
        for report in reports
    ]
    data = {
        "headers": METRIC_HEADERS,
        "days": [_display_row(row) for row in selected.days] if selected else [],
        "total": _display_summary("Total", selected.total) if selected else None,
        "target": _display_summary("Target", selected.target) if selected else None,
        "selected_report": selected,
        "mo_week_choices": choices,
        "selected_mo_week": selected_week,
        "mo_fiscal_year": fiscal_year,
        "mo_upload_form": form or MissedOpportunityUploadForm(),
        "mo_message": message,
        "mo_error": error,
        "mo_imports": MissedOpportunityImport.objects.all()[:10],
    }
    return shell_context(
        section="missed-ops",
        page_title="MO Reports",
        subtitle="Missed opportunity performance by fiscal week.",
        active_missed_ops_tab="mo-reports",
        **data,
    )


def index(request: HttpRequest) -> HttpResponse:
    fiscal_year, current_week = _current_fiscal_year_week()
    try:
        requested_week = int(request.GET.get("week") or "")
    except ValueError:
        requested_week = 0

    reports = MissedOpportunityReport.objects.filter(fiscal_year=fiscal_year)
    latest_week = reports.order_by("-fiscal_week").values_list("fiscal_week", flat=True).first()
    selected_week = requested_week if requested_week > 0 else min(current_week - 1, latest_week or current_week - 1)
    if not reports.filter(fiscal_week=selected_week).exists() and latest_week:
        selected_week = latest_week

    if request.method == "POST":
        if request.POST.get("action") == "delete":
            try:
                imported = MissedOpportunityImport.objects.get(pk=int(request.POST.get("import_id", "")))
                with transaction.atomic():
                    if imported.parse_status == "parsed" and imported.parsed_at:
                        newer = MissedOpportunityImport.objects.filter(
                            parse_status="parsed",
                            fiscal_year=imported.fiscal_year,
                            fiscal_week=imported.fiscal_week,
                            uploaded_at__gt=imported.uploaded_at,
                        ).exists()
                        if not newer:
                            MissedOpportunityReport.objects.filter(
                            fiscal_year=imported.fiscal_year,
                            fiscal_week=imported.fiscal_week,
                            source_name=imported.source_name,
                            ).delete()
                    imported.delete()
                return redirect(f"{reverse('missed-ops-mo-reports')}?deleted=1")
            except (TypeError, ValueError, MissedOpportunityImport.DoesNotExist):
                return render(request, "missed_ops/mo_reports.html", _context(request, selected_week, fiscal_year, error="That MO report upload could not be found."))
        form = MissedOpportunityUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = form.cleaned_data["source_file"]
            source_name = uploaded.name
            try:
                parsed = parse_missed_opportunity_report(uploaded.read(), source_name=source_name)
                week_end = date.fromisoformat(parsed["week_end"])
                settings = _settings()
                parsed_year = settings.fiscal_year_for_date(week_end)
                parsed_week = int(parsed["fiscal_week"])
                with transaction.atomic():
                    MissedOpportunityImport.objects.create(
                        source_name=source_name,
                        parse_status="parsed",
                        fiscal_year=parsed_year,
                        fiscal_week=parsed_week,
                        week_end=week_end,
                        parsed_at=timezone.now(),
                    )
                    MissedOpportunityReport.objects.update_or_create(
                        fiscal_year=parsed_year,
                        fiscal_week=parsed_week,
                        defaults={
                            "week_end": week_end,
                            "source_name": source_name,
                            "days": parsed["days"],
                            "total": parsed["total"],
                            "target": parsed["target"],
                        },
                    )
                return redirect(f"{reverse('missed-ops-mo-reports')}?week={parsed_week}")
            except Exception as exc:
                MissedOpportunityImport.objects.create(source_name=source_name, parse_status="failed", parse_error=str(exc))
                error = str(exc)
            return render(request, "missed_ops/mo_reports.html", _context(request, selected_week, fiscal_year, form=form, error=error))
        return render(request, "missed_ops/mo_reports.html", _context(request, selected_week, fiscal_year, form=form, error="Please choose a PDF report."))

    message = "Deleted the selected MO report data." if request.GET.get("deleted") == "1" else ""
    return render(request, "missed_ops/mo_reports.html", _context(request, selected_week, fiscal_year, message=message))
