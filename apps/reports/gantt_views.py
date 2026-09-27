from __future__ import annotations

from datetime import date

from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.models import FiscalYearSettings
from apps.core.navigation import shell_context

from .forms import GanttUploadForm
from .gantts import parse_gantt_report
from .models import GanttImport, GanttReport, MissedOpportunityReport
from .segment_views import _opportunity_days


def _selected_report(request: HttpRequest) -> MissedOpportunityReport | None:
    try:
        week = int(request.GET.get("week") or request.POST.get("fiscal_week") or "")
    except ValueError:
        week = 0
    qs = MissedOpportunityReport.objects.order_by("-fiscal_year", "-fiscal_week")
    return (qs.filter(fiscal_week=week).first() if week else None) or qs.first()


def _floor_leader_rows(report: GanttReport | None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if not report:
        return rows
    for employee in report.employees or []:
        for assignment in employee.get("assignments", []):
            if assignment.get("label") != "Floor Leader":
                continue
            rows.append({
                "segment_time": assignment.get("start", ""),
                "floor_leader": str(employee.get("name", "")).lstrip("*"),
                "interval": f"{assignment.get('start', '')}–{assignment.get('end', '')}",
                "start_minutes": int(assignment.get("start_minutes", 0)),
                "end_minutes": int(assignment.get("end_minutes", 0)),
            })
    return sorted(rows, key=lambda row: (row["start_minutes"], row["end_minutes"], str(row["floor_leader"])))


def _context(request: HttpRequest, selected: MissedOpportunityReport | None, form: GanttUploadForm, **extra: object) -> dict:
    required_days = _opportunity_days(selected)
    gantts = {
        report.day_of_week: report
        for report in GanttReport.objects.filter(
            fiscal_year=selected.fiscal_year if selected else -1,
            fiscal_week=selected.fiscal_week if selected else -1,
        )
    }
    day_rows = []
    for day in required_days:
        day_report = next((item for item in (selected.days if selected else []) if str(item.get("day", "")).title() == day), {})
        day_rows.append({
            "day": day,
            "date": day_report.get("day_date", ""),
            "missed_store_sales": day_report.get("missed_store_sales", ""),
            "report": gantts.get(day),
            "floor_leader_rows": _floor_leader_rows(gantts.get(day)),
        })
    return shell_context(
        section="missed-ops",
        page_title="Gantts",
        eyebrow="Missed Ops",
        subtitle="Upload only the Gantt reports needed for this week's top opportunity days.",
        active_missed_ops_tab="gantts",
        gantt_upload_form=form,
        gantt_selected_report=selected,
        gantt_week_choices=list(MissedOpportunityReport.objects.order_by("-fiscal_year", "-fiscal_week")),
        gantt_required_days=day_rows,
        gantt_imports=GanttImport.objects.all()[:10],
        **extra,
    )


def index(request: HttpRequest) -> HttpResponse:
    selected = _selected_report(request)
    form = GanttUploadForm(request.POST or None, request.FILES or None)
    error = ""
    if request.method == "POST" and request.POST.get("action") == "delete":
        try:
            imported = GanttImport.objects.get(pk=int(request.POST.get("import_id", "")))
            with transaction.atomic():
                if imported.parse_status == "parsed":
                    GanttReport.objects.filter(
                        fiscal_year=imported.fiscal_year,
                        fiscal_week=imported.fiscal_week,
                        day_of_week=imported.day_of_week,
                    ).delete()
                imported.delete()
            return redirect(f"{reverse('missed-ops-gantts')}?deleted=1")
        except (TypeError, ValueError, GanttImport.DoesNotExist):
            error = "That Gantt upload could not be found."
    elif request.method == "POST":
        if not selected:
            error = "Upload the missed-opportunity report before adding Gantts."
        elif form.is_valid():
            required = set(_opportunity_days(selected))
            parsed_items = []
            errors = []
            for uploaded in form.cleaned_data["source_files"]:
                source_name = str(uploaded.name)
                try:
                    parsed = parse_gantt_report(uploaded.read(), source_name)
                    if parsed["day"] not in required:
                        raise ValueError(f"{parsed['day']} is not one of this week's required Gantt days.")
                    if date.fromisoformat(parsed["week_end"]) != selected.week_end:
                        raise ValueError("The Gantt week does not match the selected missed-opportunity week.")
                    parsed_items.append(parsed)
                except Exception as exc:
                    errors.append(f"{source_name}: {exc}")
            if errors:
                error = " ".join(errors)
            elif len({item["day"] for item in parsed_items}) != len(parsed_items):
                error = "Upload only one Gantt PDF per opportunity day."
            else:
                settings = FiscalYearSettings.current()
                with transaction.atomic():
                    for parsed in parsed_items:
                        day_date = date.fromisoformat(parsed["day_date"])
                        GanttImport.objects.create(
                            source_name=parsed["source_name"], parse_status="parsed",
                            fiscal_year=selected.fiscal_year, fiscal_week=selected.fiscal_week,
                            day_of_week=parsed["day"], day_date=day_date, parsed_at=timezone.now(),
                        )
                        GanttReport.objects.update_or_create(
                            fiscal_year=selected.fiscal_year, fiscal_week=selected.fiscal_week,
                            day_of_week=parsed["day"],
                            defaults={
                                "day_date": day_date, "week_end": selected.week_end,
                                "source_name": parsed["source_name"],
                                "time_slots": parsed["time_slots"], "employees": parsed["employees"],
                            },
                        )
                return redirect(f"{reverse('missed-ops-gantts')}?week={selected.fiscal_week}&uploaded=1")
        else:
            error = "Please choose one or more Gantt PDFs."
    return render(request, "missed_ops/gantts.html", _context(
        request, selected, form, gantt_error=error,
        gantt_message=("Uploaded the requested Gantt reports." if request.GET.get("uploaded") == "1" else ("Deleted the selected Gantt data." if request.GET.get("deleted") == "1" else "")),
    ))
