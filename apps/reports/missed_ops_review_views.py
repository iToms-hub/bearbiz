from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from weasyprint import HTML

from apps.core.navigation import shell_context
from apps.reports.models import MissedOpportunityReport
from apps.reports.missed_ops_review import DEFAULT_REVIEW_CRITERIA, build_review_rows

REVIEW_HEADERS = ["Date", "Day", "Segment", "Floor Leader", "Leverage", "DPT", "Conversion", "STAR"]
CRITERIA_FIELDS = (("leverage_below", "Leverage below"), ("dpt_below", "DPT below $"), ("conversion_below", "Conversion below %"), ("star_above", "STAR above"))


def _selected(request: HttpRequest) -> MissedOpportunityReport | None:
    try:
        week = int(request.GET.get("week") or "")
    except ValueError:
        week = 0
    qs = MissedOpportunityReport.objects.order_by("-fiscal_year", "-fiscal_week")
    return (qs.filter(fiscal_week=week).first() if week else None) or qs.first()


def _criteria(request: HttpRequest) -> dict[str, Decimal]:
    values: dict[str, Decimal] = {}
    for key, _label in CRITERIA_FIELDS:
        raw = request.GET.get(key)
        try:
            values[key] = Decimal(str(raw)) if raw not in (None, "") else DEFAULT_REVIEW_CRITERIA[key]
        except (InvalidOperation, ValueError):
            values[key] = DEFAULT_REVIEW_CRITERIA[key]
    return values


def _context(request: HttpRequest) -> dict[str, object]:
    selected = _selected(request)
    criteria = _criteria(request)
    query = request.GET.copy()
    query.pop("week", None)
    criteria_query = query.urlencode()
    return shell_context(
        section="missed-ops", page_title="Review", eyebrow="Missed Ops",
        subtitle="Top missed-opportunity segments joined to their Gantt Floor Leader assignments.",
        active_missed_ops_tab="review",
        missed_ops_review_selected=selected,
        missed_ops_review_weeks=list(MissedOpportunityReport.objects.order_by("-fiscal_year", "-fiscal_week")),
        missed_ops_review_headers=REVIEW_HEADERS,
        missed_ops_review_rows=build_review_rows(selected, criteria),
        missed_ops_review_criteria=criteria,
        missed_ops_review_criteria_fields=CRITERIA_FIELDS,
        missed_ops_review_criteria_query=criteria_query,
    )


def index(request: HttpRequest) -> HttpResponse:
    return render(request, "missed_ops/review.html", _context(request))


def pdf(request: HttpRequest) -> HttpResponse:
    context = _context(request)
    selected = context["missed_ops_review_selected"]
    context.update({
        "report_pdf_title": f"Missed Ops Review: Week {selected.fiscal_week:02d}" if selected else "Missed Ops Review",
        "report_pdf_subtitle": "Top opportunity segments and Floor Leader assignments",
        "report_pdf_logo_url": (Path(settings.STATICFILES_DIRS[0]) / "images" / "bearbiz-banner.png").as_uri(),
    })
    html = render(request, "missed_ops/review_pdf.html", context).content.decode("utf-8")
    output = HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()
    response = HttpResponse(output, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="Missed Ops Review.pdf"'
    return response
