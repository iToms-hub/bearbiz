from __future__ import annotations

from datetime import date

from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.models import FiscalYearSettings
from apps.core.navigation import shell_context

from .forms import SegmentUploadForm
from .missed_opportunities import _clean_number as clean_mo_value
from .models import MissedOpportunityReport, SegmentReport, SegmentReportImport
from .segments import DISPLAY_FIELDS, display_rows, parse_segment_report


DISPLAY_HEADERS = [label for label, _ in DISPLAY_FIELDS]
DAY_NAMES = {"Sun": "Sunday", "Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday"}


def _selected_mo(week: int | None = None) -> MissedOpportunityReport | None:
    qs = MissedOpportunityReport.objects.all()
    if week is not None:
        report = qs.filter(fiscal_week=week).first()
        if report:
            return report
    return qs.first()


def _opportunity_days(report: MissedOpportunityReport | None) -> list[str]:
    if not report:
        return []
    flagged = [day for day in report.days if day.get("has_missed_opportunity")]
    flagged.sort(key=lambda day: float(clean_mo_value(day.get("missed_store_sales", "$0")).replace("$", "").replace(",", "") or 0), reverse=True)
    return [DAY_NAMES.get(str(day.get("day", "")).title(), str(day.get("day", "")).title()) for day in flagged[:3]]


def _context(request: HttpRequest, selected: MissedOpportunityReport | None, form: SegmentUploadForm, **extra: object) -> dict:
    reports = list(MissedOpportunityReport.objects.order_by("-fiscal_year", "-fiscal_week"))
    choices = [{"fiscal_week": report.fiscal_week, "week_end": report.week_end, "selected": selected and report.pk == selected.pk} for report in reports]
    segments = []
    uploaded_days = set()
    if selected:
        selected_segments = SegmentReport.objects.filter(fiscal_year=selected.fiscal_year, fiscal_week=selected.fiscal_week).order_by("day_date")
        uploaded_days = {report.day_of_week for report in selected_segments}
        for report in selected_segments:
            segments.append({"day": report.day_of_week, "day_date": report.day_date, "rows": display_rows({"rows": report.rows})})
    segment_imports = list(SegmentReportImport.objects.all()[:10])
    if not segment_imports:
        segment_imports = [
            {
                "id": report.pk,
                "legacy_segment_id": report.pk,
                "source_name": report.source_name,
                "fiscal_year": report.fiscal_year,
                "fiscal_week": report.fiscal_week,
                "day_of_week": report.day_of_week,
                "uploaded_at": report.imported_at,
                "parse_status": "parsed",
            }
            for report in SegmentReport.objects.order_by("-imported_at", "-id")[:10]
        ]
    data = shell_context(section="missed-ops", page_title="Segments", subtitle="Hourly sales performance for missed-opportunity days.", active_missed_ops_tab="segments")
    data.update({
        "segment_upload_form": form,
        "segment_week_choices": choices,
        "segment_selected_report": selected,
        "segment_opportunity_days": [day for day in _opportunity_days(selected) if day not in uploaded_days],
        "segment_reports": segments,
        "segment_headers": DISPLAY_HEADERS,
        "segment_imports": segment_imports,
    })
    data.update(extra)
    return data


def index(request: HttpRequest) -> HttpResponse:
    requested_week = request.GET.get("week") or request.POST.get("fiscal_week")
    try:
        requested_week_int = int(requested_week) if requested_week else None
    except (TypeError, ValueError):
        requested_week_int = None
    selected = _selected_mo(requested_week_int)
    form = SegmentUploadForm(request.POST or None, request.FILES or None, initial={"fiscal_week": selected.fiscal_week if selected else ""})

    if request.method == "POST":
        if request.POST.get("action") == "delete":
            try:
                import_id = int(request.POST.get("import_id", ""))
                imported = SegmentReportImport.objects.get(pk=import_id)
                with transaction.atomic():
                    if imported.parse_status == "parsed" and imported.parsed_at:
                        newer = SegmentReportImport.objects.filter(
                            parse_status="parsed",
                            fiscal_year=imported.fiscal_year,
                            fiscal_week=imported.fiscal_week,
                            day_of_week=imported.day_of_week,
                            uploaded_at__gt=imported.uploaded_at,
                        ).exists()
                        if not newer:
                            SegmentReport.objects.filter(
                            fiscal_year=imported.fiscal_year,
                            fiscal_week=imported.fiscal_week,
                            day_of_week=imported.day_of_week,
                            source_name=imported.source_name,
                            ).delete()
                    imported.delete()
                return redirect(f"{reverse('missed-ops-segments')}?week={requested_week_int or ''}&deleted=1")
            except (TypeError, ValueError, SegmentReportImport.DoesNotExist):
                return render(request, "missed_ops/segments.html", _context(request, selected, form, segment_error="That segment upload could not be found."))
        if request.POST.get("action") == "delete_legacy":
            try:
                SegmentReport.objects.get(pk=int(request.POST.get("segment_id", ""))).delete()
                return redirect(f"{reverse('missed-ops-segments')}?week={requested_week_int or ''}&deleted=1")
            except (TypeError, ValueError, SegmentReport.DoesNotExist):
                return render(request, "missed_ops/segments.html", _context(request, selected, form, segment_error="That segment report could not be found."))
        if not selected:
            return render(request, "missed_ops/segments.html", _context(request, selected, form, segment_error="Upload the missed-opportunity report before adding segment reports."))
        if form.is_valid():
            required_days = set(_opportunity_days(selected))
            files = form.cleaned_data["source_files"]
            if len(files) > 3:
                return render(request, "missed_ops/segments.html", _context(request, selected, form, segment_error="Upload no more than three segment PDFs."))
            parsed_reports = []
            errors = []
            for uploaded in files:
                try:
                    parsed = parse_segment_report(uploaded.read(), uploaded.name)
                    if parsed["day"] not in required_days:
                        raise ValueError(f"{parsed['day']} is not one of this week's opportunity days: {', '.join(_opportunity_days(selected))}.")
                    if date.fromisoformat(parsed["week_end"]) != selected.week_end:
                        raise ValueError("The segment report week does not match the selected missed-opportunity week.")
                    parsed_reports.append((uploaded.name, parsed))
                except Exception as exc:
                    errors.append(f"{uploaded.name}: {exc}")
            parsed_days = {parsed["day"] for _, parsed in parsed_reports}
            missing = required_days - parsed_days
            if missing:
                errors.append(f"Missing required opportunity-day report(s): {', '.join(sorted(missing))}.")
            if len(parsed_days) != len(parsed_reports):
                errors.append("Upload only one PDF per opportunity day.")
            if errors:
                return render(request, "missed_ops/segments.html", _context(request, selected, form, segment_error=" ".join(errors)))
            settings = FiscalYearSettings.current()
            with transaction.atomic():
                SegmentReport.objects.filter(fiscal_year=selected.fiscal_year, fiscal_week=selected.fiscal_week).delete()
                for source_name, parsed in parsed_reports:
                    day_date = date.fromisoformat(parsed["day_date"])
                    SegmentReport.objects.create(
                        fiscal_year=selected.fiscal_year,
                        fiscal_week=selected.fiscal_week,
                        day_of_week=parsed["day"],
                        day_date=day_date,
                        week_end=selected.week_end,
                        source_name=source_name,
                        headers=parsed["headers"],
                        rows=parsed["rows"],
                    )
                    SegmentReportImport.objects.create(
                        source_name=source_name,
                        parse_status="parsed",
                        fiscal_year=selected.fiscal_year,
                        fiscal_week=selected.fiscal_week,
                        day_of_week=parsed["day"],
                        parsed_at=timezone.now(),
                    )
            return redirect(f"{reverse('missed-ops-segments')}?week={selected.fiscal_week}")

    return render(request, "missed_ops/segments.html", _context(request, selected, form, segment_message="Deleted the selected segment data." if request.GET.get("deleted") == "1" else ""))
