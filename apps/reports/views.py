from __future__ import annotations

import io
import json
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from pathlib import Path
from typing import Any, cast

from django.conf import settings
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST
from weasyprint import HTML

from apps.core.ai import summarize_weekly_sales_report
from apps.core.models import ReviewTemplate
from apps.core.views import sanitize_rich_text
from apps.core.navigation import report_date_tabs, report_tabs, shell_context

from .catalog import report_config, report_label, report_relation, report_slug
from .fiscal import as_dict, calculate_fiscal_week
from .forms import ReportUploadForm
from .models import BonusClubSummary, GiftCardsSummary, RankingSummary, ReportUpload, SegmentsSummary, WeeklySalesSummary
from .modules.bonus_club import BonusClubReport
from .modules.gift_cards import GiftCardsReport
from .modules.ranking import RankingReport
from .modules.segments import SegmentsReport
from .modules.weekly_sales import WeeklySalesReport
from .registry import get
from .payroll_views import payroll_dashboard_summary
from .parties_views import parties_dashboard_summary
from .product_views import product_dashboard_summary

REPORTS = {number: config for number in range(1, 7) if (config := report_config(number))}


def dashboard(request: HttpRequest) -> HttpResponse:
    """Render the dashboard from persisted weekly sales summaries."""

    bonus_club_summary = _dashboard_latest_summary(BonusClubSummary)
    bonus_club_value = _dashboard_store_percentage(bonus_club_summary, "capture_rate")
    gift_cards_summary = _dashboard_latest_summary(GiftCardsSummary)
    gift_cards_value = _dashboard_store_percentage(gift_cards_summary, "bonus_percent")
    payroll_summary = payroll_dashboard_summary()
    summaries = _dashboard_weekly_sales_summaries(limit=6)
    dashboard_title = _dashboard_title(summaries)
    dashboard_headers = _dashboard_weekly_report_headers()
    dashboard_rows = _weekly_report_rows(summaries)
    dashboard_rows.extend(_dashboard_trend_rows(summaries))
    ranking_summaries = _dashboard_ranking_summaries(limit=4)
    ranking_headers = _dashboard_ranking_report_headers()
    ranking_rows = _ranking_report_rows(ranking_summaries)
    segment_summaries = _dashboard_segment_summaries(limit=1)
    segment_headers = _dashboard_segments_report_headers()
    segment_rows = _dashboard_segment_rows(segment_summaries)
    context = shell_context(
        section="dashboard",
        page_title=dashboard_title,
        eyebrow="Dashboard",
        subtitle=_dashboard_subtitle(summaries),
        bonus_club_value=bonus_club_value,
        gift_cards_value=gift_cards_value,
        payroll_summary=payroll_summary,
        dashboard_headers=dashboard_headers,
        dashboard_rows=dashboard_rows,
        ranking_headers=ranking_headers,
        ranking_rows=ranking_rows,
        segment_headers=segment_headers,
        segment_rows=segment_rows,
        empty_state="No persisted weekly reports have been wired in yet.",
    )
    if request.GET.get("format") == "json":
        return JsonResponse(
            {
                "dashboard": {
                    "bonus_club": {"value": bonus_club_value},
                    "gift_cards": {"value": gift_cards_value},
                    "payroll": payroll_summary,
                    "headers": dashboard_headers,
                    "rows": [
                        {
                            "row_class": row.get("row_class", ""),
                            "values": list(cast(list[object], row.get("values") or [])),
                        }
                        for row in dashboard_rows
                    ],
                },
                "ranking": {
                    "headers": ranking_headers,
                    "rows": [
                        {
                            "headers": list(cast(list[str], row.get("headers") or [])),
                            "values": list(cast(list[object], row.get("values") or [])),
                        }
                        for row in ranking_rows
                    ],
                },
                "segments": {
                    "headers": segment_headers,
                    "rows": [
                        {
                            "values": list(cast(list[object], row.get("values") or [])),
                        }
                        for row in segment_rows
                    ],
                },
                "empty_state": context["empty_state"],
            }
        )
    return render(request, "reports/dashboard.html", context)


def dashboard_review(request: HttpRequest) -> HttpResponse:
    """Render a saved weekly review template in its configured order."""
    if request.method == "POST" and request.POST.get("action") == "save-note":
        selected = ReviewTemplate.objects.filter(pk=request.POST.get("template_id")).first()
        try:
            module_index = int(request.POST.get("module_index", "-1"))
        except ValueError:
            module_index = -1
        if selected and 0 <= module_index < len(selected.layout):
            layout = list(selected.layout)
            module = dict(layout[module_index])
            if module.get("type") == "notes":
                module["title"] = (request.POST.get("note_title") or "Notes").strip()[:120] or "Notes"
                module["text"] = sanitize_rich_text(request.POST.get("note_text", ""))
                layout[module_index] = module
                selected.layout = layout
                selected.save(update_fields=["layout", "updated_at"])
        if selected:
            return redirect(f"{reverse('dashboard-review')}?template={selected.pk}")

    context = _dashboard_review_context(request)
    return render(request, "reports/dashboard_review.html", context)


def _dashboard_review_context(request: HttpRequest) -> dict[str, object]:
    templates = list(ReviewTemplate.objects.all())
    selected_id = request.GET.get("template")
    selected = (
        ReviewTemplate.objects.filter(pk=selected_id).first()
        if selected_id
        else (templates[0] if templates else None)
    )
    weekly = _dashboard_weekly_sales_summaries(limit=6)
    ranking = _dashboard_ranking_summaries(limit=5)
    segment = _dashboard_segment_summaries(limit=1)
    module_data = {
        "bonus-gift-combined": _dashboard_bonus_gift_table(),
        "bonus-club": {"value": _dashboard_store_percentage(_dashboard_latest_summary(BonusClubSummary), "capture_rate")},
        "gift-card-bonus": {"value": _dashboard_store_percentage(_dashboard_latest_summary(GiftCardsSummary), "bonus_percent")},
        "payroll": {"payroll": payroll_dashboard_summary()},
        "weekly-sales-trend": {"headers": _weekly_report_headers(), "rows": _weekly_report_rows(weekly) + _dashboard_trend_rows(weekly)},
        "segments": {"headers": _segments_report_headers(), "rows": _dashboard_segment_rows(segment)},
        "parties": parties_dashboard_summary() or {"message": "No direct Parties data is available."},
        "product-top-10": product_dashboard_summary() or {"message": "No parsed Product data is available."},
        "rankings": {"headers": _ranking_report_headers(), "rows": _ranking_report_rows(ranking)},
    }
    review_render_modules = []
    for module in (selected.layout if selected else []):
        if module.get("enabled", True) is False:
            continue
        rendered_module = {**module, **module_data.get(module.get("type"), {})}
        if rendered_module.get("type") == "bonus-gift-combined" and rendered_module.get("title") == "Bonus Club & Gift Cards":
            rendered_module["title"] = "Last Weeks Bonus Club & Gift Cards"
        review_render_modules.append(rendered_module)
    review_week = weekly[-1].fiscal_week if weekly else calculate_fiscal_week(
        _current_date() - timedelta(days=6), _current_date()
    ).fiscal_week_number
    return shell_context(
        section="dashboard", active_dashboard_tab="review", page_title="Last Week Review",
        eyebrow="Dashboard", subtitle="Last Weeks Performance Review",
        review_templates=templates, selected_review_template=selected,
        review_layout=review_render_modules, review_module_data=module_data,
        report_pdf_title=f"Store 214 Review: Week {int(review_week):02d}",
        report_pdf_subtitle=f"Business review for week {int(review_week):02d}",
        report_pdf_logo_url=(Path(settings.STATICFILES_DIRS[0]) / "images" / "bearbiz-banner.png").as_uri(),
    )


def dashboard_review_pdf(request: HttpRequest) -> HttpResponse:
    """Export only the selected review modules as a PDF attachment."""
    context = _dashboard_review_context(request)
    html = render_to_string("reports/dashboard_review_pdf.html", context, request=request)
    pdf = HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()
    response = HttpResponse(pdf or b"", content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="Last Week Review.pdf"'
    return response


def performance(request: HttpRequest) -> HttpResponse:
    """Render associate performance across the persisted report summaries."""
    state = _performance_state(request)
    context = shell_context(
        section="performance",
        page_title="Performance",
        eyebrow="Performance",
        subtitle="Associate performance from Gift Cards, Bonus Club, and Segment Accountability reports.",

        performance_date_filter=state["date_filter"],
        performance_date_options=state["date_options"],
        performance_range_start=state["range_start"],
        performance_range_end=state["range_end"],
        performance_associate_options=state["associate_options"],
        performance_associate_selected=state["selected_associate"],
        performance_associate_label=state["selected_label"],
        performance_rows=state["rows"],
        performance_segment_rows=state["segment_rows"],
        segment_headers=_segments_range_report_headers(),
        performance_segment_listed=state["segment_listed"],
        performance_chart_svg=state["chart_svg"],
        performance_period_label=state["period_label"],
    )
    return render(request, "performance/associates.html", context)


def performance_pdf(request: HttpRequest) -> HttpResponse:
    """Export the current associate performance selection as a portrait PDF."""
    # Keep this endpoint beside the performance state builder for live reloads.
    state = _performance_state(request)
    selected_label = str(state["selected_label"] or "Associate")
    filename_label = re.sub(r"[^A-Za-z0-9 .:-]+", "", selected_label).strip(" .-") or "Associate"
    date_filter = str(state["date_filter"])
    if date_filter == "range":
        suffix = f"{state['range_start']} to {state['range_end']}"
    else:
        suffix = {"last_week": "last week", "month": "current month", "quarter": "current quarter"}.get(date_filter, "current view")
    filename = f"Performance Associates: {filename_label} - {suffix}.pdf"
    context = shell_context(
        section="performance",
        page_title="Performance",
        performance_associate_label=selected_label,
        performance_period_label=state["period_label"],
        performance_rows=state["rows"],
        performance_segment_rows=state["segment_rows"],
        performance_segment_listed=state["segment_listed"],
        performance_chart_svg=state["chart_svg"],
        segment_headers=_segments_range_report_headers(),
        report_pdf_title=filename.removesuffix(".pdf"),
        report_pdf_logo_url=(Path(settings.STATICFILES_DIRS[0]) / "images" / "bearbiz-banner.png").as_uri(),
    )
    html = render(request, "performance/associates_pdf.html", context).content.decode("utf-8")
    pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
    response = HttpResponse(pdf or b"", content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _performance_state(request: HttpRequest) -> dict[str, object]:
    date_filter = str(request.GET.get("date_filter", "last_week"))
    if date_filter not in {"last_week", "month", "quarter", "range"}:
        date_filter = "last_week"
    today = _current_date()
    gift_cards = list(getattr(GiftCardsSummary, "objects").select_related("report_upload").order_by("fiscal_year", "fiscal_week", "id"))
    bonus_club = list(getattr(BonusClubSummary, "objects").select_related("report_upload").order_by("fiscal_year", "fiscal_week", "id"))
    segments = list(getattr(SegmentsSummary, "objects").select_related("report_upload").order_by("fiscal_year", "fiscal_week", "id"))
    available_associate_summaries = gift_cards + bonus_club
    all_summaries = available_associate_summaries + segments
    dates = [summary.fiscal_period_end for summary in all_summaries if summary.fiscal_period_end]
    latest_date = max(dates, default=today)
    if date_filter == "last_week":
        filtered_end = latest_date
        filtered_start = latest_date - timedelta(days=6)
    elif date_filter == "month":
        filtered_start = today.replace(day=1)
        filtered_end = today
    elif date_filter == "quarter":
        filtered_start = today.replace(month=((today.month - 1) // 3) * 3 + 1, day=1)
        filtered_end = today
    else:
        filtered_start = _parse_date(str(request.GET.get("range_start", ""))) or latest_date - timedelta(days=6)
        filtered_end = _parse_date(str(request.GET.get("range_end", ""))) or latest_date
        if filtered_start > filtered_end:
            filtered_start, filtered_end = filtered_end, filtered_start

    def in_period(summary: Any) -> bool:
        return bool(summary.fiscal_period_end and filtered_start <= summary.fiscal_period_end <= filtered_end)

    gift_cards = [summary for summary in gift_cards if in_period(summary)]
    bonus_club = [summary for summary in bonus_club if in_period(summary)]
    segments = [summary for summary in segments if in_period(summary)]
    option_map: dict[str, str] = {}
    for summary in available_associate_summaries:
        raw = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        for row in raw.get("associate_rows", []) if isinstance(raw.get("associate_rows"), list) else []:
            if not isinstance(row, dict):
                continue
            number = str(row.get("associate_number", "")).strip()
            name = str(row.get("name", "")).strip()
            if number and name:
                option_map.setdefault(number, name)
    options = [{"value": number, "label": name} for number, name in sorted(option_map.items(), key=lambda item: item[1].casefold())]
    selected = str(request.GET.get("associate", "")).strip()
    if selected not in option_map:
        selected = options[0]["value"] if options else ""
    selected_label = option_map.get(selected, "")

    rows = _performance_rows(gift_cards, bonus_club, selected)
    segment_rows = _performance_segment_rows(segments, selected_label) if selected_label else []
    segment_listed = bool(segment_rows)
    chart_svg = _performance_chart_svg(_performance_chart_series(gift_cards, bonus_club, segments, selected, selected_label))
    period_label = f"{_format_display_date(filtered_start)} – {_format_display_date(filtered_end)}"
    return {
        "date_filter": date_filter,
        "date_options": [("last_week", "Last week"), ("month", "Current month"), ("quarter", "Current quarter"), ("range", "Custom range")],
        "range_start": filtered_start.isoformat(),
        "range_end": filtered_end.isoformat(),
        "associate_options": options,
        "selected_associate": selected,
        "selected_label": selected_label,
        "rows": rows,
        "segment_rows": segment_rows,
        "segment_listed": segment_listed,
        "chart_svg": chart_svg,
        "period_label": period_label,
    }


def _performance_rows(gift_cards: list[GiftCardsSummary], bonus_club: list[BonusClubSummary], selected: str) -> list[dict[str, object]]:
    by_date: dict[date, dict[str, object]] = {}
    for summary, kind in [(summary, "gift") for summary in gift_cards] + [(summary, "bonus") for summary in bonus_club]:
        if not summary.fiscal_period_end:
            continue
        raw = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        match = _find_associate_row(raw.get("associate_rows"), selected)
        if not isinstance(match, dict):
            continue
        metrics = match.get("metrics") if isinstance(match.get("metrics"), dict) else {}
        entry = by_date.setdefault(summary.fiscal_period_end, {"date": _format_display_date(summary.fiscal_period_end), "gift": {}, "bonus": {}})
        entry[kind] = metrics
    rows: list[dict[str, object]] = []
    totals: dict[str, list[float]] = {"gift_total": [], "gift_bonus": [], "gift_pct": [], "bonus_total": [], "bonus_club": [], "bonus_pct": []}
    for period_end in sorted(by_date):
        entry = by_date[period_end]
        gift = entry["gift"] if isinstance(entry["gift"], dict) else {}
        bonus = entry["bonus"] if isinstance(entry["bonus"], dict) else {}
        values = [entry["date"], _format_number(gift.get("total_transactions")), _format_number(gift.get("gc_bonus_transactions")), _format_percent(gift.get("bonus_percent")), _format_number(bonus.get("total_transactions")), _format_number(bonus.get("transactions_with_club")), _format_percent(bonus.get("capture_rate"))]
        rows.append({"period_end": period_end, "values": values, "row_class": "report-week-row"})
        for key, metrics, metric in [("gift_total", gift, "total_transactions"), ("gift_bonus", gift, "gc_bonus_transactions"), ("gift_pct", gift, "bonus_percent"), ("bonus_total", bonus, "total_transactions"), ("bonus_club", bonus, "transactions_with_club"), ("bonus_pct", bonus, "capture_rate")]:
            number = _coerce_number(metrics.get(metric))
            if number is not None:
                totals[key].append(number)
    if not rows:
        return []
    rows.append({"values": ["Total", _format_number(sum(totals["gift_total"])), _format_number(sum(totals["gift_bonus"])), _format_percent((sum(totals["gift_bonus"]) / sum(totals["gift_total"]) * 100) if totals["gift_total"] else None), _format_number(sum(totals["bonus_total"])), _format_number(sum(totals["bonus_club"])), _format_percent((sum(totals["bonus_club"]) / sum(totals["bonus_total"]) * 100) if totals["bonus_total"] else None)], "row_class": "report-summary-row report-summary-total"})
    rows.append({"values": ["Average", *[_format_average_number(totals[key]) for key in ("gift_total", "gift_bonus")], _format_percent(_average_number(totals["gift_pct"])), *[_format_average_number(totals[key]) for key in ("bonus_total", "bonus_club")], _format_percent(_average_number(totals["bonus_pct"])),], "row_class": "report-summary-row report-summary-average"})
    rows.append({
        "values": [
            "Trend", "", "", _performance_trend(rows, 3), "", "", _performance_trend(rows, 6),
        ],
        "row_class": "report-summary-row report-summary-trend",
    })
    return rows


def _performance_trend(rows: list[dict[str, object]], index: int) -> str:
    weekly = [row for row in rows if row.get("period_end")]
    values: list[float] = []
    for row in weekly:
        row_values = row.get("values")
        if isinstance(row_values, list) and index < len(row_values):
            number = _coerce_number(row_values[index])
            if number is not None:
                values.append(number)
    if len(values) < 2:
        return "—"
    change = values[-1] - values[0]
    if abs(change) < 0.005:
        return "No change"
    return f"{'↑' if change > 0 else '↓'} {abs(change):.2f} pts"


def _performance_segment_rows(segments: list[SegmentsSummary], selected_label: str) -> list[dict[str, object]]:
    """Reuse range totals without accepting an unlisted manager fallback."""
    selected_name = _normalize_person_name(selected_label)
    listed_segments: list[SegmentsSummary] = []
    for summary in segments:
        raw = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        manager_rows = raw.get("manager_rows") if isinstance(raw.get("manager_rows"), list) else []
        if any(
            isinstance(row, dict)
            and _normalize_person_name(row.get("name")) == selected_name
            and isinstance(row.get("metrics"), dict)
            and any(value not in (None, "") for value in cast(dict[str, object], row.get("metrics", {})).values())
            for row in manager_rows
        ):
            listed_segments.append(summary)
    return _segments_range_report_rows(listed_segments, selected_label) if listed_segments else []


def _performance_chart_series(gift_cards: list[GiftCardsSummary], bonus_club: list[BonusClubSummary], segments: list[SegmentsSummary], selected: str, selected_label: str) -> list[dict[str, object]]:
    by_date: dict[date, dict[str, object]] = {}
    metric_specs = [
        (gift_cards, "Gift Card Bonus %", "bonus_percent", "Store Gift Card Bonus %"),
        (bonus_club, "Bonus Club Capture %", "capture_rate", "Store Bonus Club Capture %"),
    ]
    for summaries, label, metric, store_label in metric_specs:
        for summary in summaries:
            if not summary.fiscal_period_end:
                continue
            raw = summary.raw_json if isinstance(summary.raw_json, dict) else {}
            match = _find_associate_row(raw.get("associate_rows"), selected)
            metrics = match.get("metrics") if isinstance(match, dict) and isinstance(match.get("metrics"), dict) else {}
            value = _coerce_number(metrics.get(metric))
            if value is not None:
                by_date.setdefault(summary.fiscal_period_end, {})[metric] = value
            store_total = raw.get("store_total")
            store_metrics = store_total.get("metrics") if isinstance(store_total, dict) and isinstance(store_total.get("metrics"), dict) else {}
            store_value = _coerce_number(store_metrics.get(metric))
            if store_value is not None:
                by_date.setdefault(summary.fiscal_period_end, {})[store_label] = store_value
    labels = [period_end.strftime("%m/%d/%y") for period_end in sorted(by_date)]
    series_specs = [
        ("bonus_percent", "Gift Card Bonus %"),
        ("capture_rate", "Bonus Club Capture %"),
        ("Store Gift Card Bonus %", "Store Gift Card Bonus %"),
        ("Store Bonus Club Capture %", "Store Bonus Club Capture %"),
    ]
    return [{"label": label, "points": [by_date[period].get(key) for period in sorted(by_date)]} for key, label in series_specs if any(by_date[period].get(key) is not None for period in sorted(by_date))] + [{"labels": labels}]


def _performance_chart_svg(series: list[dict[str, object]]) -> str:
    labels_obj = series[-1].get("labels", []) if series else []
    labels = labels_obj if isinstance(labels_obj, list) else []
    plotted = series[:-1] if series and "labels" in series[-1] else series
    if not plotted:
        return ""
    width, height, left, top, chart_width, chart_height = 720, 280, 52, 24, 640, 190
    colors = ["#dc2626" if str(item.get("label", "")).startswith("Store ") else color for item, color in zip(plotted, ["#5b7cfa", "#0f8b4c", "#f97316", "#5b7cfa", "#0f8b4c", "#f97316"])]
    parts = [f'<svg class="performance-chart" role="img" aria-label="Associate performance trend line graph" viewBox="0 0 {width} {height}" data-series="{len(plotted)}">']
    parts.append(f'<line x1="{left}" y1="{top + chart_height}" x2="{left + chart_width}" y2="{top + chart_height}" stroke="currentColor" opacity=".35"/><line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_height}" stroke="currentColor" opacity=".35"/>')
    for tick in (0, 25, 50, 75, 100):
        y = top + chart_height - (tick / 100 * chart_height)
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" class="chart-y-label" font-size="10">{tick}</text>')
    for index, label in enumerate(labels):
        x = left + (chart_width * index / max(len(labels) - 1, 1))
        parts.append(f'<text x="{x:.1f}" y="{top + chart_height + 18}" text-anchor="middle" class="chart-label" font-size="10">{escape(str(label))}</text>')
    for index, item in enumerate(plotted):
        values = item.get("points", [])
        points: list[str] = []
        point_positions: list[tuple[float, float, float]] = []
        for point_index, value in enumerate(values if isinstance(values, list) else []):
            if value is None:
                continue
            x = left + (chart_width * point_index / max(len(labels) - 1, 1))
            y = top + chart_height - (float(value) / 100 * chart_height)
            points.append(f"{x:.1f},{y:.1f}")
            point_positions.append((x, y, float(value)))
        if points:
            label = escape(str(item.get("label", "")), quote=True)
            color = colors[index % len(colors)]
            parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{" ".join(points)}" data-series-label="{label}"/>')
            for x, y, value in point_positions:
                # Stagger labels from different series and keep them inside the plot.
                label_y = max(top + 10, min(top + chart_height - 4, y - 7 - (index % 3) * 9))
                value_label = escape(f'{Decimal(str(float(value))).normalize():f}%')
                parts.append(
                    f'<text x="{x:.1f}" y="{label_y:.1f}" text-anchor="middle" '
                    f'class="chart-point-label" font-size="9" fill="{color}" '
                    f'paint-order="stroke" stroke="white" stroke-width="3" stroke-opacity=".85">{value_label}</text>'
                )
    parts.append('<g class="chart-legend" aria-label="Chart legend">')
    legend_items: list[tuple[str, str]] = []
    store_legend_added = False
    for index, item in enumerate(plotted):
        item_label = str(item.get("label", ""))
        if item_label.startswith("Store "):
            if store_legend_added:
                continue
            store_legend_added = True
            legend_items.append(("Store Performance", colors[index % len(colors)]))
        else:
            legend_items.append((item_label, colors[index % len(colors)]))
    legend_x = 56
    for label_text, color in legend_items:
        label = escape(label_text)
        parts.append(f'<line x1="{legend_x}" y1="255" x2="{legend_x + 12}" y2="255" stroke="{color}" stroke-width="2"/><text x="{legend_x + 16}" y="258" fill="{color}" class="chart-legend-item" font-size="8">{label}</text>')
        legend_x += 16 + max(34, len(label_text) * 4.2) + 12
    parts.append("</g>")
    parts.append("</svg>")
    return mark_safe("".join(parts))


def report_section(request: HttpRequest, number: int = 1) -> HttpResponse:
    context = _report_context(request, number)
    return render(request, "reports/report_section.html", context)


def report_pdf(request: HttpRequest, number: int = 1) -> HttpResponse:
    context = _report_context(request, number)
    report = cast(dict[str, Any], context["report"])
    context["report_pdf_logo_url"] = (Path(settings.STATICFILES_DIRS[0]) / "images" / "bearbiz-banner.png").as_uri()
    html = render(request, "reports/report_pdf.html", context).content.decode("utf-8")
    pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
    response = HttpResponse(pdf or b"", content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{context["report_pdf_filename"]}"'
    return response


def _report_pdf_filename(report: dict[str, Any], request: HttpRequest, context: dict[str, Any]) -> str:
    """Build a safe, useful filename without changing uploaded source names."""

    report_names = {
        "weekly_sales": "Weekly Sales Report",
        "ranking": "Ranking Report",
        "segments": "Segments Report",
        "gift_cards": "Gift Cards Report",
        "bonus_club": "Bonus Club Report",
    }
    report_name = report_names.get(str(report.get("slug") or ""), "Report 6")
    selection = str(request.GET.get("date_filter", "last_week"))
    if selection == "year":
        suffix = "year"
    elif selection == "range":
        start_value = _parse_date(str(context.get("report_range_start") or ""))
        end_value = _parse_date(str(context.get("report_range_end") or ""))
        if start_value and end_value and start_value > end_value:
            start_value, end_value = end_value, start_value
        start = _filename_date(start_value)
        end = _filename_date(end_value)
        suffix = f"{start} to {end}"
    elif selection == "week":
        suffix = _filename_date(context.get("report_week_end"))
    else:
        suffix = {
            "last_week": "last week",
            "month": "current month",
            "quarter": "current quarter",
            "all": "all",
        }.get(selection, "current-view")
    safe_name = re.sub(r"[^A-Za-z0-9 .:-]+", "", report_name)
    safe_name = re.sub(r"\s+", " ", safe_name).strip(" .-") or "Report"
    safe_suffix = re.sub(r"[^A-Za-z0-9 .:-]+", "", suffix)
    safe_suffix = re.sub(r"\s+", " ", safe_suffix).strip(" .-") or "current-view"
    return f"{safe_name}: {safe_suffix}.pdf"


def _filename_date(value: object) -> str:
    parsed = _parse_date(str(value or ""))
    return parsed.strftime("%m-%d-%y") if parsed else "unspecified-date"


def _report_context(request: HttpRequest, number: int) -> dict[str, Any]:
    report = REPORTS.get(number)
    if report is None:
        raise Http404("Unknown report type.")

    report_type = str(report.get("slug") or "weekly_sales")
    date_filter = str(request.GET.get("date_filter", "last_week"))
    if date_filter == "all":
        date_filter = "last_week"
    report_date_state = _report_date_state(request, report_type)
    context = shell_context(
        section="reports",
        page_title="Reports",
        subtitle=str(report.get("subtitle", "Browse the weekly report data newest first.")),
        active_number=number,
        report_date_tabs=report_date_tabs(date_filter, number, request.GET),
        report_upload_url=(reverse("reports:history") if number == 1 else reverse("reports:history-number", kwargs={"number": number})) if bool(report.get("upload_supported")) else "",
        report_number=number,
        report=report,
        report_slug=report_type,
        report_headers=report_date_state["headers"],
        report_rows=report_date_state["rows"],
        report_date_mode=date_filter,
        report_total_count=report_date_state["total_count"],
        report_filtered_count=report_date_state["filtered_count"],
        report_week_end=report_date_state["week_end"],
        report_range_start=report_date_state["range_start"],
        report_range_end=report_date_state["range_end"],
        report_associate_options=report_date_state["associate_options"],
        report_associate_selected=report_date_state["selected_associate"],
        report_show_associate_filter=False,
        report_date_state_year=report_date_state["year"],
        report_view_title=str(report.get("viewer_title", "Weekly report data")),
        report_view_note=str(report_date_state.get("note") or report.get("viewer_note", "Newest week first, with each week in its own row.")),
        report_table_class=report_date_state["table_class"],
        report_period_label=report_date_state["period_label"],
        report_pdf_period_label=(
            ""
            if report_type in {"gift_cards", "bonus_club"}
            and report_date_state["mode"] in {"month", "quarter", "range"}
            else report_date_state["period_label"]
        ),
        report_pdf_url=f'{reverse("reports:report-pdf", kwargs={"number": number})}?{request.META.get("QUERY_STRING", "")}' if request.META.get("QUERY_STRING") else reverse("reports:report-pdf", kwargs={"number": number}),
    )
    report_pdf_filename = _report_pdf_filename(report, request, context)
    context["report_pdf_filename"] = report_pdf_filename
    context["report_pdf_title"] = report_pdf_filename.removesuffix(".pdf")
    return context


def report_history(request: HttpRequest, number: int = 1) -> HttpResponse:
    report = REPORTS.get(number)
    if report is None:
        raise Http404("Unknown report type.")

    report_type = str(report.get("slug") or "weekly_sales")
    report_upload_supported = bool(report.get("upload_supported"))
    relation_name = str(report.get("summary_relation") or "")
    uploads = _uploads_for_report(report_type, relation_name)

    if request.method == "POST":
        if not report_upload_supported:
            raise Http404("Uploads are not enabled for this report type.")
        form = ReportUploadForm(request.POST, request.FILES)
        if form.is_valid():
            upload = form.save(report_type=report_type)
            _parse_and_store_summary(upload)
            return redirect("reports:detail", pk=upload.pk)
    else:
        form = ReportUploadForm()

    context = shell_context(
        section="uploads",
        page_title=str(report.get("label", "Uploads")),
        subtitle=str(report.get("subtitle", "Upload and manage report PDFs.")),
        active_number=number,
        report_number=number,
        report=report,
        report_upload_supported=report_upload_supported,
        form=form,
        uploads=uploads,
        upload_url=request.path,
    )
    return render(request, "reports/history.html", context, status=400 if request.method == "POST" and not form.is_valid() else 200)


def report_upload(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        return redirect("reports:history")
    return report_history(request, 1)


def report_detail(request: HttpRequest, pk: int) -> HttpResponse:
    upload = get_object_or_404(ReportUpload, pk=pk)
    if str(upload.report_type) in {"gift_cards", "bonus_club"} and upload.parse_status == "failed" and upload.source_file and upload.source_file.name:
        _parse_and_store_summary(upload)
        upload.refresh_from_db()
    report_number = _report_number_for_type(str(upload.report_type))
    report = REPORTS.get(report_number, {})
    summary, summary_metric_headers, summary_metric_values, summary_section_title = _summary_for_upload(upload)
    detail_headers: list[str] = []
    detail_rows: list[dict[str, object]] = []
    detail_note = ""
    detail_section_title = ""
    if str(upload.report_type) == "gift_cards" and summary is not None:
        detail_headers = _gift_cards_report_headers()
        detail_rows = _gift_cards_report_rows([cast(GiftCardsSummary, summary)])
        detail_note = "Associate rows from the upload, with store total at the bottom."
        detail_section_title = "Gift card rows"
    if str(upload.report_type) == "bonus_club" and summary is not None:
        detail_headers = _bonus_club_report_headers()
        detail_rows = _bonus_club_report_rows([cast(BonusClubSummary, summary)])
        detail_note = "Associate rows from the upload, with store total at the bottom."
        detail_section_title = "Bonus club rows"
    context = shell_context(
        section="reports",
        page_title=upload.source_name,
        subtitle="Upload detail and parsed summary.",
        top_tabs=report_tabs(report_number),
        primary_action={"label": "Upload another PDF", "url": reverse("reports:history-number", kwargs={"number": report_number}) if report_number > 1 else reverse("reports:history")},
        report=report,
        upload=upload,
        summary=summary,
        summary_metric_headers=summary_metric_headers,
        summary_metric_values=summary_metric_values,
        summary_section_title=summary_section_title,
        detail_headers=detail_headers,
        detail_rows=detail_rows,
        detail_note=detail_note,
        detail_section_title=detail_section_title,
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


@require_POST
def report_delete(request: HttpRequest, pk: int) -> HttpResponse:
    upload = get_object_or_404(ReportUpload, pk=pk)
    if upload.source_file and upload.source_file.name:
        upload.source_file.delete(save=False)
    report_number = _report_number_for_type(str(upload.report_type))
    upload.delete()
    if report_number > 1:
        return redirect("reports:history-number", number=report_number)
    return redirect("reports:history")


def _report_number_for_type(report_type: str) -> int:
    for number, config in REPORTS.items():
        if str(config.get("slug") or "") == str(report_type or ""):
            return number
    return 1


def _uploads_for_report(report_type: str, relation_name: str) -> list[ReportUpload]:
    queryset = getattr(ReportUpload, "objects").filter(report_type=report_type).order_by("-uploaded_at", "-id")
    if relation_name:
        queryset = queryset.select_related(relation_name)
    return list(queryset)


def _summary_for_upload(upload: ReportUpload) -> tuple[object | None, list[str], list[object], str]:
    report_number = _report_number_for_type(str(upload.report_type))
    report = REPORTS.get(report_number, {})
    relation_name = str(report.get("summary_relation") or "")
    summary = getattr(upload, relation_name, None) if relation_name else None
    if str(upload.report_type) == "weekly_sales":
        weekly_summary = _refresh_weekly_summary_if_needed(upload, cast(WeeklySalesSummary | None, summary))
        if weekly_summary is not None:
            summary = weekly_summary
    if str(upload.report_type) == "ranking":
        ranking_summary = cast(RankingSummary | None, summary)
        summary = _refresh_ranking_summary_if_needed(upload, ranking_summary)
    if str(upload.report_type) == "segments":
        segment_summary = cast(SegmentsSummary | None, summary)
        summary = _refresh_segments_summary_if_needed(upload, segment_summary)
    if str(upload.report_type) == "gift_cards":
        gift_cards_summary = cast(GiftCardsSummary | None, summary)
        summary = _refresh_gift_cards_summary_if_needed(upload, gift_cards_summary)
    if str(upload.report_type) == "bonus_club":
        bonus_club_summary = cast(BonusClubSummary | None, summary)
        summary = _refresh_bonus_club_summary_if_needed(upload, bonus_club_summary)
    raw_json = summary.raw_json if summary and isinstance(summary.raw_json, dict) else {}
    if str(upload.report_type) == "ranking":
        headers, values = _ranking_metrics_for_display(cast(RankingSummary | None, summary), raw_json)
        return summary, headers, values, "Ranking report metrics"
    if str(upload.report_type) == "segments":
        headers, values = _segments_metrics_for_display(cast(SegmentsSummary | None, summary), raw_json)
        return summary, headers, values, "Store total metrics"
    if str(upload.report_type) == "gift_cards":
        headers, values = _gift_cards_metrics_for_display(cast(GiftCardsSummary | None, summary), raw_json)
        return summary, headers, values, "Gift card store sales"
    if str(upload.report_type) == "bonus_club":
        headers, values = _bonus_club_metrics_for_display(cast(BonusClubSummary | None, summary), raw_json)
        return summary, headers, values, "Bonus club store totals"
    headers, values = _weekly_metrics_for_display(cast(WeeklySalesSummary | None, summary), raw_json)
    return summary, headers, values, "Weekly summary metrics"


def _refresh_ranking_summary_if_needed(upload: ReportUpload, summary: RankingSummary | None) -> RankingSummary | None:
    if summary is None:
        return None
    raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
    if int(raw_json.get("parse_version", 0) or 0) >= int(getattr(RankingReport, "parse_version", 2)):
        target = raw_json.get("target_store") if isinstance(raw_json, dict) else None
        ranks = target.get("ranks") if isinstance(target, dict) else {}
        if isinstance(ranks, dict) and len(ranks) >= len(_RANKING_VIEW_METRICS):
            return summary
    target = raw_json.get("target_store") if isinstance(raw_json, dict) else None
    ranks = target.get("ranks") if isinstance(target, dict) else {}
    source_text = str(raw_json.get("raw_text") or "") if isinstance(raw_json, dict) else ""
    if not source_text and upload.source_file and upload.source_file.name:
        try:
            source_text = _extract_pdf_text_from_upload(upload)
        except Exception:
            source_text = ""
    if not source_text:
        return summary
    parsed = get("ranking").parse(source_text)
    parsed_payload = parsed.payload if isinstance(parsed.payload, dict) else {}
    parsed_fiscal_obj = parsed_payload.get("fiscal")
    parsed_fiscal = parsed_fiscal_obj if isinstance(parsed_fiscal_obj, dict) else {}
    defaults: dict[str, object] = {
        "fiscal_year": int(parsed_fiscal.get("fiscal_year", summary.fiscal_year)),
        "fiscal_week": int(parsed_fiscal.get("fiscal_week_number", summary.fiscal_week)),
        "fiscal_period_start": _parse_date(parsed.period_start),
        "fiscal_period_end": _parse_date(parsed.period_end),
        "raw_json": parsed.payload,
    }
    return getattr(RankingSummary, "objects").update_or_create(report_upload=upload, defaults=defaults)[0]


def _ranking_metrics_for_display(summary: RankingSummary | None, raw_json: dict[str, object] | None) -> tuple[list[str], list[object]]:
    raw_json = raw_json if isinstance(raw_json, dict) else {}
    fiscal_obj = raw_json.get("fiscal")
    fiscal = fiscal_obj if isinstance(fiscal_obj, dict) else {}
    target_obj = raw_json.get("target_store")
    target = target_obj if isinstance(target_obj, dict) else {}
    ranks_obj = target.get("ranks") if isinstance(target, dict) else {}
    ranks = ranks_obj if isinstance(ranks_obj, dict) else {}
    headers = ["Week", "Date", *[label for _, label in _RANKING_VIEW_METRICS]]
    week_number = summary.fiscal_week if summary else fiscal.get("fiscal_week_number", "")
    week_end_value = summary.fiscal_period_end if summary and summary.fiscal_period_end else fiscal.get("week_ending_date")
    values: list[object] = [week_number, _format_display_date(week_end_value)]
    for key, _label in _RANKING_VIEW_METRICS:
        rank = ranks.get(key) if isinstance(ranks, dict) else None
        if isinstance(rank, dict):
            rank_value = rank.get("rank")
            total_value = rank.get("total")
            if rank_value and total_value:
                values.append(f"{rank_value}/{total_value}")
                continue
        values.append("")
    return headers, values


def _ranking_report_rows(summaries: list[RankingSummary]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, summary in enumerate(summaries):
        upload = cast(ReportUpload, summary.report_upload)
        summary = _refresh_ranking_summary_if_needed(upload, summary)
        raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        headers, values = _ranking_metrics_for_display(summary, raw_json)
        rows.append(
            {
                "summary": summary,
                "headers": headers,
                "values": values,
                "row_class": "report-ranking-row-latest" if index == len(summaries) - 1 else "",
            }
        )
    return rows


def _ranking_report_headers() -> list[str]:
    return ["Week", "Date", *[label for _, label in _RANKING_VIEW_METRICS]]


def _segments_report_headers() -> list[str]:
    return ["Week", "Date", *SegmentsReport._VISIBLE_HEADERS]


def _dashboard_weekly_report_headers() -> list[str]:
    replacements = {"Traffic Lev": "leverage", "% Δ LY Traf": "% traf"}
    return [replacements.get(header, header) for header in _weekly_report_headers()]


def _dashboard_ranking_report_headers() -> list[str]:
    replacements = {"Sales v plan": "v plan"}
    return [replacements.get(header, header) for header in _ranking_report_headers()]


def _dashboard_segments_report_headers() -> list[str]:
    replacements = {"Conversion": "Conv", "Success Segments": "Success Seg"}
    return [replacements.get(header, header) for header in _segments_report_headers()]


def _segments_report_rows(summaries: list[SegmentsSummary]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for summary in summaries:
        upload = cast(ReportUpload, summary.report_upload)
        summary = _refresh_segments_summary_if_needed(upload, summary)
        if summary is None:
            continue
        raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        manager_rows = raw_json.get("manager_rows") if isinstance(raw_json, dict) else []
        if not isinstance(manager_rows, list):
            continue
        fiscal_obj = raw_json.get("fiscal") if isinstance(raw_json, dict) else {}
        fiscal = fiscal_obj if isinstance(fiscal_obj, dict) else {}
        week_value = summary.fiscal_week or fiscal.get("fiscal_week_number") or fiscal.get("fiscal_week") or ""
        date_value = summary.fiscal_period_end or fiscal.get("week_ending_date")
        week_label = str(week_value) if week_value != "" else ""
        date_label = _format_display_date(date_value)
        for row in manager_rows:
            if not isinstance(row, dict):
                continue
            values = [week_label, date_label, row.get("name", ""), *list(row.get("visible_values", []))]
            rows.append(
                {
                    "summary": summary,
                    "row_kind": row.get("row_kind"),
                    "metrics": row.get("metrics", {}),
                    "week": week_label,
                    "date": date_label,
                    "name": row.get("name"),
                    "job_title": row.get("job_title"),
                    "values": values,
                }
            )
        store_total = raw_json.get("store_total") if isinstance(raw_json, dict) else None
        if isinstance(store_total, dict):
            values = [week_label, date_label, store_total.get("name", ""), *list(store_total.get("visible_values", []))]
            rows.append(
                {
                    "summary": summary,
                    "row_kind": "store_total",
                    "week": week_label,
                    "date": date_label,
                    "name": store_total.get("name"),
                    "job_title": "",
                    "values": values,
                }
            )
    return rows


def _segments_range_report_headers(*, include_period: bool = True) -> list[str]:
    return _segments_report_headers() if include_period else list(SegmentsReport._VISIBLE_HEADERS)


def _segments_aggregate_report_rows(summaries: list[SegmentsSummary]) -> list[dict[str, object]]:
    """Combine manager and store Segment metrics over a selected timeframe."""
    managers: dict[str, dict[str, object]] = {}
    store = {"name": "Store Total", "segment_count": 0.0, "success_segments": 0.0, "store_sales": 0.0, "sales_trans": 0.0}
    for summary in summaries:
        upload = cast(ReportUpload, summary.report_upload)
        summary = _refresh_segments_summary_if_needed(upload, summary)
        if summary is None:
            continue
        raw = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        manager_rows = raw.get("manager_rows") if isinstance(raw.get("manager_rows"), list) else []
        for row in manager_rows:
            if not isinstance(row, dict) or not isinstance(row.get("metrics"), dict):
                continue
            name = str(row.get("name") or "").strip()
            key = _normalize_person_name(name)
            if not key:
                continue
            group = managers.setdefault(key, {"name": name, "segment_count": 0.0, "success_segments": 0.0, "store_sales": 0.0, "sales_trans": 0.0, "summary": summary})
            metrics = cast(dict[str, object], row["metrics"])
            for metric in ("segment_count", "success_segments", "store_sales", "sales_trans"):
                value = _coerce_number(metrics.get(metric))
                if value is not None:
                    group[metric] = float(group[metric]) + value
            group["summary"] = summary
        store_total = raw.get("store_total") if isinstance(raw.get("store_total"), dict) else {}
        store_metrics = store_total.get("metrics") if isinstance(store_total.get("metrics"), dict) else {}
        visible_values = store_total.get("visible_values") if isinstance(store_total.get("visible_values"), list) else []
        visible_fallbacks = {
            "segment_count": visible_values[0] if len(visible_values) > 0 else None,
            "success_segments": visible_values[2] if len(visible_values) > 2 else None,
            "store_sales": visible_values[4] if len(visible_values) > 4 else None,
            "sales_trans": visible_values[5] if len(visible_values) > 5 else None,
        }
        if store_total.get("name"):
            store["name"] = str(store_total["name"])
        for metric in ("segment_count", "success_segments", "store_sales", "sales_trans"):
            value = _coerce_number(store_metrics.get(metric, visible_fallbacks[metric]))
            if value is not None:
                store[metric] = float(store[metric]) + value
    if not managers and not any(store[metric] for metric in ("segment_count", "success_segments", "store_sales", "sales_trans")):
        return []
    store_segment_count = float(store["segment_count"])
    rows: list[dict[str, object]] = []
    for group in managers.values():
        segment_count = float(group["segment_count"])
        sales_trans = float(group["sales_trans"])
        store_sales = float(group["store_sales"])
        success_segments = float(group["success_segments"])
        rows.append({
            "summary": group["summary"],
            "row_kind": "manager",
            "row_class": f"report-week-row {'report-week-row-even' if len(rows) % 2 else 'report-week-row-odd'}",
            "values": [
                group["name"],
                _format_segment_number(segment_count),
                _format_segment_percent((segment_count / store_segment_count * 100) if store_segment_count else None),
                _format_segment_number(success_segments),
                _format_segment_percent((success_segments / segment_count * 100) if segment_count else None),
                _format_segment_currency(store_sales),
                _format_segment_number(sales_trans),
                "",
                _format_segment_number((store_sales / sales_trans) if sales_trans else None),
                "",
            ],
        })
    store_sales = float(store["store_sales"])
    sales_trans = float(store["sales_trans"])
    success_segments = float(store["success_segments"])
    rows.append({
        "summary": next(iter(managers.values()))["summary"] if managers else summaries[-1],
        "row_kind": "store_total",
        "row_class": "report-summary-row report-store-total-row",
        "values": [
            store["name"],
            _format_segment_number(store_segment_count),
            _format_segment_percent(100 if store_segment_count else None),
            _format_segment_number(success_segments),
            _format_segment_percent((success_segments / store_segment_count * 100) if store_segment_count else None),
            _format_segment_currency(store_sales),
            _format_segment_number(sales_trans),
            "",
            _format_segment_number((store_sales / sales_trans) if sales_trans else None),
            "",
        ],
    })
    return rows


def _segments_range_report_rows(summaries: list[SegmentsSummary], selected_manager: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    totals: dict[str, list[float]] = {
        "segment_count": [],
        "segment_total_pct": [],
        "success_segments": [],
        "success_pct": [],
        "store_sales": [],
        "sales_trans": [],
        "conversion": [],
        "dpt": [],
        "upt": [],
    }
    selected_name = ""
    for summary in summaries:
        upload = cast(ReportUpload, summary.report_upload)
        summary = _refresh_segments_summary_if_needed(upload, summary)
        if summary is None:
            continue
        raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        fiscal_obj = raw_json.get("fiscal") if isinstance(raw_json, dict) else {}
        fiscal = fiscal_obj if isinstance(fiscal_obj, dict) else {}
        week_value = summary.fiscal_week or fiscal.get("fiscal_week_number") or fiscal.get("fiscal_week") or ""
        date_value = summary.fiscal_period_end or fiscal.get("week_ending_date")
        week_label = str(week_value) if week_value != "" else ""
        date_label = _format_display_date(date_value)
        match = _find_segments_manager_row(raw_json.get("manager_rows"), selected_manager)
        if not isinstance(match, dict):
            continue
        selected_name = str(match.get("name", selected_name) or selected_name)
        metrics_obj = match.get("metrics") if isinstance(match.get("metrics"), dict) else {}
        metrics = metrics_obj if isinstance(metrics_obj, dict) else {}
        values = [week_label, date_label, selected_name, *_segments_visible_values_from_metrics(metrics)]
        rows.append(
            {
                "summary": summary,
                "row_kind": "manager",
                "week": week_label,
                "date": date_label,
                "name": selected_name,
                "job_title": match.get("job_title"),
                "row_class": f"report-week-row {'report-week-row-even' if len(rows) % 2 == 0 else 'report-week-row-odd'}",
                "values": values,
            }
        )
        for key in totals:
            value = _coerce_number(metrics.get(key))
            if value is not None:
                totals[key].append(value)
    if not rows:
        return []
    total_segment_count = sum(totals["segment_count"])
    total_success_segments = sum(totals["success_segments"])
    total_store_sales = sum(totals["store_sales"])
    total_sales_trans = sum(totals["sales_trans"])
    total_visible_values = [
        _format_segment_number(total_segment_count),
        _format_segment_percent(_average_number(totals["segment_total_pct"])),
        _format_segment_number(total_success_segments),
        _format_segment_percent((total_success_segments / total_segment_count * 100) if total_segment_count else None),
        _format_segment_currency(total_store_sales),
        _format_segment_number(total_sales_trans),
        _format_segment_percent(_average_number(totals["conversion"])),
        _format_segment_number((total_store_sales / total_sales_trans) if total_sales_trans else None),
        _format_segment_number(_average_number(totals["upt"])),
    ]
    rows.append(
        {
            "summary": rows[-1]["summary"],
            "row_kind": "segment_total",
            "week": "Total",
            "date": "",
            "name": selected_name,
            "job_title": "",
            "row_class": "report-summary-row report-summary-total",
            "values": ["Total", "", selected_name, *total_visible_values],
        }
    )
    rows.append(
        {
            "summary": rows[-1]["summary"],
            "row_kind": "segment_spacer",
            "week": "",
            "date": "",
            "name": "",
            "job_title": "",
            "row_class": "report-spacer-row",
            "values": ["", "", "", "", "", "", "", "", "", "", "", ""],
        }
    )
    rows.append(
        {
            "summary": rows[-1]["summary"],
            "row_kind": "segment_average",
            "week": "Average",
            "date": "",
            "name": selected_name,
            "job_title": "",
            "row_class": "report-summary-row report-summary-average",
            "values": [
                "Average",
                "",
                selected_name,
                _format_segment_number(_average_number(totals["segment_count"])),
                _format_segment_percent(_average_number(totals["segment_total_pct"])),
                _format_segment_number(_average_number(totals["success_segments"])),
                _format_segment_percent(_average_number(totals["success_pct"])),
                _format_segment_currency(_average_number(totals["store_sales"])),
                _format_segment_number(_average_number(totals["sales_trans"])),
                _format_segment_percent(_average_number(totals["conversion"])),
                _format_segment_number(_average_number(totals["dpt"])),
                _format_segment_number(_average_number(totals["upt"])),
            ],
        }
    )
    return rows


def _find_segments_manager_row(manager_rows: object, selected_manager: str) -> dict[str, object] | None:
    if not isinstance(manager_rows, list):
        return None
    if selected_manager:
        for row in manager_rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", "")).strip()
            if _normalize_person_name(selected_manager) == _normalize_person_name(name):
                return row
    for row in manager_rows:
        if isinstance(row, dict):
            return row
    return None


def _segments_visible_values_from_metrics(metrics: dict[str, object]) -> list[str]:
    return [
        _format_segment_number(metrics.get("segment_count")),
        _format_segment_percent(metrics.get("segment_total_pct")),
        _format_segment_number(metrics.get("success_segments")),
        _format_segment_percent(metrics.get("success_pct")),
        _format_segment_currency(metrics.get("store_sales")),
        _format_segment_number(metrics.get("sales_trans")),
        _format_segment_percent(metrics.get("conversion")),
        _format_segment_number(metrics.get("dpt")),
        _format_segment_number(metrics.get("upt")),
    ]


def _format_segment_number(value: object | None) -> str:
    if value is None:
        return ""
    number = _coerce_number(value)
    if number is None:
        return str(value)
    return f"{Decimal(str(number)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def _format_segment_percent(value: object | None) -> str:
    if value is None:
        return ""
    number = _coerce_decimal(value)
    if abs(number) <= 1:
        number *= 100
    return f"{number.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}%"


def _format_segment_currency(value: object | None) -> str:
    if value is None:
        return ""
    number = _coerce_number(value)
    if number is None:
        return str(value)
    return f"${Decimal(str(number)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def _gift_cards_report_headers() -> list[str]:
    return ["Week", "Date", *GiftCardsReport._VISIBLE_HEADERS]


def _segments_metrics_for_display(summary: SegmentsSummary | None, raw_json: dict[str, object] | None) -> tuple[list[str], list[object]]:
    raw_json_dict = raw_json if isinstance(raw_json, dict) else {}
    headers = list(SegmentsReport._VISIBLE_HEADERS)
    row_obj = raw_json_dict.get("store_total")
    if not isinstance(row_obj, dict):
        manager_rows = raw_json_dict.get("manager_rows")
        if isinstance(manager_rows, list) and manager_rows:
            first_row = manager_rows[0]
            row_obj = first_row if isinstance(first_row, dict) else None
        else:
            row_obj = None
    if row_obj is None:
        return headers, [""] * len(headers)
    values = [row_obj.get("name", ""), *list(row_obj.get("visible_values", []))]
    if len(values) < len(headers):
        values.extend([""] * (len(headers) - len(values)))
    return headers, values[: len(headers)]


def _gift_cards_report_headers() -> list[str]:
    return ["Week", "Date", *GiftCardsReport._VISIBLE_HEADERS]


def _performer_row_class(rank: int, count: int) -> str:
    # Keep the groups distinct; with fewer than six performers, three top and
    # three bottom rows would overlap and produce contradictory highlighting.
    if count < 6:
        return ""
    classes: list[str] = []
    if rank < 3:
        classes.append("report-performer-top")
    if rank >= count - 3:
        classes.append("report-performer-bottom")
    return " ".join(classes)


def _rank_performer_rows(rows: list[object], metric_name: str) -> list[dict[str, object]]:
    valid_rows: list[dict[str, object]] = [row for row in rows if isinstance(row, dict)]
    return sorted(
        valid_rows,
        key=lambda row: (-_performer_rate(row, metric_name), str(row.get("name", "")).casefold()),
    )


def _performer_rate(row: dict[str, object], metric_name: str) -> float:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    value = _coerce_number(cast(dict[str, object], metrics).get(metric_name))
    return value if value is not None else float("-inf")


def _aggregate_group_rate(group: dict[str, object], metric_names: tuple[str, ...]) -> float:
    values = cast(dict[str, object], group["values"])
    total = _coerce_number(values.get(metric_names[0])) or 0.0
    related = _coerce_number(values.get(metric_names[1])) or 0.0
    return related / total * 100 if total else float("-inf")


def _gift_cards_report_rows(summaries: list[GiftCardsSummary]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for summary in summaries:
        upload = cast(ReportUpload, summary.report_upload)
        summary = _refresh_gift_cards_summary_if_needed(upload, summary)
        if summary is None:
            continue
        raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        fiscal_obj = raw_json.get("fiscal") if isinstance(raw_json, dict) else {}
        fiscal = fiscal_obj if isinstance(fiscal_obj, dict) else {}
        week_value = summary.fiscal_week or fiscal.get("fiscal_week_number") or fiscal.get("fiscal_week") or ""
        date_value = summary.fiscal_period_end or fiscal.get("week_ending_date")
        week_label = str(week_value) if week_value != "" else ""
        date_label = _format_display_date(date_value)
        weekly_sales_ready = raw_json.get("weekly_sales_dpt") is not None

        associate_rows = raw_json.get("associate_rows") if isinstance(raw_json, dict) else []
        if isinstance(associate_rows, list):
            ranked_rows = _rank_performer_rows(associate_rows, "bonus_percent")
            for rank, row in enumerate(ranked_rows):
                values = [week_label, date_label, *_gift_cards_row_values(row)]
                rows.append(
                    {
                        "summary": summary,
                        "row_kind": row.get("row_kind"),
                        "week": week_label,
                        "date": date_label,
                        "name": row.get("name"),
                        "associate_number": row.get("associate_number", ""),
                        "weekly_sales_ready": weekly_sales_ready,
                        "row_class": f"report-week-row {'report-week-row-even' if len(rows) % 2 == 0 else 'report-week-row-odd'} {_performer_row_class(rank, len(ranked_rows))}".strip(),
                        "values": values,
                    }
                )

        store_total = raw_json.get("store_total") if isinstance(raw_json, dict) else None
        if isinstance(store_total, dict):
            values = [week_label, date_label, *_gift_cards_row_values(store_total)]
            rows.append(
                {
                    "summary": summary,
                    "row_kind": "store_total",
                    "week": week_label,
                    "date": date_label,
                    "name": store_total.get("name"),
                    "associate_number": store_total.get("associate_number", ""),
                    "weekly_sales_ready": weekly_sales_ready,
                    "row_class": "report-summary-row report-store-total-row",
                    "values": values,
                }
            )
    return rows


def _gift_cards_metrics_for_display(summary: GiftCardsSummary | None, raw_json: dict[str, object] | None) -> tuple[list[str], list[object]]:
    raw_json_dict = raw_json if isinstance(raw_json, dict) else {}
    headers = ["Week", "Date", "Store Sales", "Total Transactions", "Total Transactions with GC Bonus", "% Transactions w/ GC Bonus", "Missed Opportunities"]
    fiscal_obj = raw_json_dict.get("fiscal")
    fiscal = fiscal_obj if isinstance(fiscal_obj, dict) else {}
    row_obj = raw_json_dict.get("store_total")
    if not isinstance(row_obj, dict):
        row_obj = None
    week_value = summary.fiscal_week if summary else fiscal.get("fiscal_week_number", "")
    week_label = str(week_value) if week_value != "" else ""
    date_value = summary.fiscal_period_end if summary and summary.fiscal_period_end else fiscal.get("week_ending_date")
    date_label = _format_display_date(date_value)
    if row_obj is None:
        return headers, [week_label, date_label, "", "", "", "", ""]
    metrics_obj = row_obj.get("metrics") if isinstance(row_obj, dict) else {}
    metrics = metrics_obj if isinstance(metrics_obj, dict) else {}
    values = [
        week_label,
        date_label,
        row_obj.get("name", ""),
        _format_number(metrics.get("total_transactions")),
        _format_number(metrics.get("gc_bonus_transactions")),
        _format_percent(metrics.get("bonus_percent")),
        _format_currency(metrics.get("missed_opportunities")),
    ]
    return headers, values


def _gift_cards_row_values(row: dict[str, object]) -> list[object]:
    metrics_obj = row.get("metrics") if isinstance(row, dict) else {}
    metrics = metrics_obj if isinstance(metrics_obj, dict) else {}
    return [
        row.get("associate_number", ""),
        row.get("name", ""),
        _format_number(metrics.get("total_transactions")),
        _format_number(metrics.get("gc_bonus_transactions")),
        _format_percent(metrics.get("bonus_percent")),
        _format_currency(metrics.get("missed_opportunities")),
    ]


def _gift_cards_associate_report_headers(*, include_period: bool = True) -> list[str]:
    columns = ["Associate #", "Name", "Total Transactions", "Total Transactions with GC Bonus", "% Transactions w/ GC Bonus", "Missed Opportunities"]
    return (["Week", "Date"] if include_period else []) + columns


def _aggregate_associate_report_rows(summaries: list[Any], selected_associate: str, report_type: str, period_label: str) -> list[dict[str, object]]:
    specs = {
        "gift_cards": ("total_transactions", "gc_bonus_transactions", "bonus_percent", "missed_opportunities"),
        "bonus_club": ("total_transactions", "transactions_with_club", "capture_rate"),
    }
    metric_names = specs[report_type]
    grouped: dict[str, dict[str, object]] = {}
    store_totals: dict[str, object] = {name: 0.0 for name in metric_names if name != metric_names[2]}
    store_name = "Store total"
    store_number = ""
    for summary in summaries:
        if report_type == "gift_cards":
            summary = _refresh_gift_cards_summary_if_needed(cast(ReportUpload, summary.report_upload), summary)
        else:
            summary = _refresh_bonus_club_summary_if_needed(cast(ReportUpload, summary.report_upload), summary)
        if summary is None:
            continue
        raw = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        associates = raw.get("associate_rows") if isinstance(raw.get("associate_rows"), list) else []
        for row in associates:
            if not isinstance(row, dict):
                continue
            number = str(row.get("associate_number", "")).strip()
            name = str(row.get("name", "")).strip()
            if selected_associate and selected_associate not in {number, name} and _normalize_person_name(selected_associate) != _normalize_person_name(name):
                continue
            key = number or _normalize_person_name(name)
            if not key:
                continue
            group = grouped.setdefault(key, {"number": number, "name": name, "summary": summary, "values": {metric: 0.0 for metric in metric_names}})
            metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
            for metric in metric_names:
                value = _coerce_number(metrics.get(metric))
                if value is not None and metric != metric_names[2]:
                    cast(dict[str, object], group["values"])[metric] = float(cast(dict[str, object], group["values"])[metric]) + value
            if selected_associate:
                group["summary"] = summary
        store = raw.get("store_total") if isinstance(raw.get("store_total"), dict) else {}
        store_metrics = store.get("metrics") if isinstance(store.get("metrics"), dict) else {}
        store_name = str(store.get("name") or store_name)
        store_number = str(store.get("associate_number") or store_number)
        for metric in store_totals:
            value = _coerce_number(store_metrics.get(metric))
            if value is not None:
                store_totals[metric] = float(store_totals[metric]) + value
    rows: list[dict[str, object]] = []
    headers_len = 8 if report_type == "gift_cards" else 7
    ordered_groups = sorted(
        grouped.values(),
        key=lambda group: (-_aggregate_group_rate(group, metric_names), str(group["name"]).casefold()),
    )
    for rank, group in enumerate(ordered_groups):
        values = cast(dict[str, object], group["values"])
        total = float(values.get(metric_names[0]) or 0)
        related = float(values.get(metric_names[1]) or 0)
        rate = related / total * 100 if total else None
        display = [group["number"], group["name"], _format_number(total), _format_number(related)]
        if report_type == "gift_cards":
            display.extend([_format_percent(rate), _format_currency(values.get("missed_opportunities"))])
        else:
            display.append(_format_percent(rate))
        rows.append({"summary": group["summary"], "row_kind": "associate_total", "row_class": f"report-week-row {'report-week-row-even' if len(rows) % 2 else 'report-week-row-odd'} {_performer_row_class(rank, len(ordered_groups))}".strip(), "values": display[:headers_len - 2]})
    if not selected_associate and any(value for value in store_totals.values()):
        total = store_totals[metric_names[0]]
        related = store_totals[metric_names[1]]
        display = [store_number, store_name, _format_number(total), _format_number(related), _format_percent(related / total * 100 if total else None)]
        if report_type == "gift_cards":
            display.append(_format_currency(store_totals.get("missed_opportunities")))
        rows.append({"row_kind": "store_total", "row_class": "report-summary-row report-store-total-row", "values": display[:headers_len - 2]})
    return rows


def _gift_cards_associate_report_rows(summaries: list[GiftCardsSummary], selected_associate: str, *, aggregate: bool = False, period_label: str = "") -> list[dict[str, object]]:
    if aggregate:
        return _aggregate_associate_report_rows(summaries, selected_associate, "gift_cards", period_label)
    rows: list[dict[str, object]] = []
    totals: dict[str, list[float]] = {"total_transactions": [], "gc_bonus_transactions": [], "bonus_percent": [], "missed_opportunities": []}
    selected_name = ""
    selected_number = selected_associate
    for summary in summaries:
        upload = cast(ReportUpload, summary.report_upload)
        summary = _refresh_gift_cards_summary_if_needed(upload, summary)
        if summary is None:
            continue
        raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        fiscal_obj = raw_json.get("fiscal") if isinstance(raw_json, dict) else {}
        fiscal = fiscal_obj if isinstance(fiscal_obj, dict) else {}
        week_value = summary.fiscal_week or fiscal.get("fiscal_week_number") or fiscal.get("fiscal_week") or ""
        date_value = summary.fiscal_period_end or fiscal.get("week_ending_date")
        week_label = str(week_value) if week_value != "" else ""
        date_label = _format_display_date(date_value)
        match = _find_associate_row(raw_json.get("associate_rows"), selected_associate)
        if not isinstance(match, dict):
            continue
        selected_number = str(match.get("associate_number", selected_number) or selected_number)
        selected_name = str(match.get("name", selected_name) or selected_name)
        metrics_obj = match.get("metrics") if isinstance(match.get("metrics"), dict) else {}
        metrics = metrics_obj if isinstance(metrics_obj, dict) else {}
        rows.append(
            {
                "summary": summary,
                "row_kind": "associate_week",
                "week": week_label,
                "date": date_label,
                "name": selected_name,
                "associate_number": selected_number,
                "row_class": f"report-week-row {'report-week-row-even' if len(rows) % 2 == 0 else 'report-week-row-odd'}",
                "values": [
                    week_label,
                    date_label,
                    selected_number,
                    selected_name,
                    _format_number(metrics.get("total_transactions")),
                    _format_number(metrics.get("gc_bonus_transactions")),
                    _format_percent(metrics.get("bonus_percent")),
                    _format_currency(metrics.get("missed_opportunities")),
                ],
            }
        )
        if metrics.get("total_transactions") is not None:
            totals["total_transactions"].append(_coerce_number(metrics.get("total_transactions")) or 0.0)
        if metrics.get("gc_bonus_transactions") is not None:
            totals["gc_bonus_transactions"].append(_coerce_number(metrics.get("gc_bonus_transactions")) or 0.0)
        if metrics.get("bonus_percent") is not None:
            totals["bonus_percent"].append(_coerce_number(metrics.get("bonus_percent")) or 0.0)
        if metrics.get("missed_opportunities") is not None:
            totals["missed_opportunities"].append(_coerce_number(metrics.get("missed_opportunities")) or 0.0)
    if not rows:
        return []
    total_transactions = sum(totals["total_transactions"])
    total_gc_bonus = sum(totals["gc_bonus_transactions"])
    total_bonus_percent = (total_gc_bonus / total_transactions * 100) if total_transactions else None
    total_missed = sum(totals["missed_opportunities"]) if totals["missed_opportunities"] else None
    rows.append(
        {
            "summary": rows[-1]["summary"],
            "row_kind": "associate_total",
            "week": "Total",
            "date": "",
            "name": selected_name,
            "associate_number": selected_number,
            "row_class": "report-summary-row report-summary-total",
            "values": [
                "Total",
                "",
                selected_number,
                selected_name,
                _format_number(total_transactions),
                _format_number(total_gc_bonus),
                _format_percent(total_bonus_percent),
                _format_currency(total_missed),
            ],
        }
    )
    rows.append(
        {
            "summary": rows[-1]["summary"],
            "row_kind": "associate_spacer",
            "week": "",
            "date": "",
            "name": "",
            "associate_number": "",
            "row_class": "report-spacer-row",
            "values": ["", "", "", "", "", "", "", ""],
        }
    )
    rows.append(
        {
            "summary": rows[-1]["summary"],
            "row_kind": "associate_average",
            "week": "Average",
            "date": "",
            "name": selected_name,
            "associate_number": selected_number,
            "row_class": "report-summary-row report-summary-average",
            "values": [
                "Average",
                "",
                selected_number,
                selected_name,
                _format_average_number(totals["total_transactions"]),
                _format_average_number(totals["gc_bonus_transactions"]),
                _format_percent(_average_number(totals["bonus_percent"])),
                _format_currency(_average_number(totals["missed_opportunities"])),
            ],
        }
    )
    return rows


def _bonus_club_report_headers() -> list[str]:
    return ["Week", "Date", *BonusClubReport._VISIBLE_HEADERS]


def _bonus_club_report_rows(summaries: list[BonusClubSummary]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for summary in summaries:
        upload = cast(ReportUpload, summary.report_upload)
        summary = _refresh_bonus_club_summary_if_needed(upload, summary)
        if summary is None:
            continue
        raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        fiscal_obj = raw_json.get("fiscal") if isinstance(raw_json, dict) else {}
        fiscal = fiscal_obj if isinstance(fiscal_obj, dict) else {}
        week_value = summary.fiscal_week or fiscal.get("fiscal_week_number") or fiscal.get("fiscal_week") or ""
        date_value = summary.fiscal_period_end or fiscal.get("week_ending_date")
        week_label = str(week_value) if week_value != "" else ""
        date_label = _format_display_date(date_value)

        associate_rows = raw_json.get("associate_rows") if isinstance(raw_json, dict) else []
        if isinstance(associate_rows, list):
            ranked_rows = _rank_performer_rows(associate_rows, "capture_rate")
            for rank, row in enumerate(ranked_rows):
                values = [week_label, date_label, *_bonus_club_row_values(row)]
                rows.append(
                    {
                        "summary": summary,
                        "row_kind": row.get("row_kind"),
                        "week": week_label,
                        "date": date_label,
                        "name": row.get("name"),
                        "associate_number": row.get("associate_number", ""),
                        "row_class": f"report-week-row {'report-week-row-even' if len(rows) % 2 == 0 else 'report-week-row-odd'} {_performer_row_class(rank, len(ranked_rows))}".strip(),
                        "values": values,
                    }
                )

        store_total = raw_json.get("store_total") if isinstance(raw_json, dict) else None
        if isinstance(store_total, dict):
            values = [week_label, date_label, *_bonus_club_row_values(store_total)]
            rows.append(
                {
                    "summary": summary,
                    "row_kind": "store_total",
                    "week": week_label,
                    "date": date_label,
                    "name": store_total.get("name"),
                    "associate_number": store_total.get("associate_number", ""),
                    "row_class": "report-summary-row report-store-total-row",
                    "values": values,
                }
            )
    return rows


def _bonus_club_metrics_for_display(summary: BonusClubSummary | None, raw_json: dict[str, object] | None) -> tuple[list[str], list[object]]:
    raw_json_dict = raw_json if isinstance(raw_json, dict) else {}
    headers = ["Week", "Date", "Store Sales", "Total Transactions", "Transactions with Club #", "Bonus Club Capture Rate"]
    fiscal_obj = raw_json_dict.get("fiscal")
    fiscal = fiscal_obj if isinstance(fiscal_obj, dict) else {}
    row_obj = raw_json_dict.get("store_total")
    if not isinstance(row_obj, dict):
        row_obj = None
    week_value = summary.fiscal_week if summary else fiscal.get("fiscal_week_number", "")
    week_label = str(week_value) if week_value != "" else ""
    date_value = summary.fiscal_period_end if summary and summary.fiscal_period_end else fiscal.get("week_ending_date")
    date_label = _format_display_date(date_value)
    if row_obj is None:
        return headers, [week_label, date_label, "", "", "", ""]
    metrics_obj = row_obj.get("metrics") if isinstance(row_obj, dict) else {}
    metrics = metrics_obj if isinstance(metrics_obj, dict) else {}
    values = [
        week_label,
        date_label,
        row_obj.get("name", ""),
        _format_number(metrics.get("total_transactions")),
        _format_number(metrics.get("transactions_with_club")),
        _format_percent(metrics.get("capture_rate")),
    ]
    return headers, values


def _bonus_club_row_values(row: dict[str, object]) -> list[object]:
    metrics_obj = row.get("metrics") if isinstance(row, dict) else {}
    metrics = metrics_obj if isinstance(metrics_obj, dict) else {}
    return [
        row.get("associate_number", ""),
        row.get("name", ""),
        _format_number(metrics.get("total_transactions")),
        _format_number(metrics.get("transactions_with_club")),
        _format_percent(metrics.get("capture_rate")),
    ]


def _bonus_club_associate_report_headers(*, include_period: bool = True) -> list[str]:
    columns = ["Associate #", "Name", "Total Transactions", "Transactions with Club #", "Bonus Club Capture Rate"]
    return (["Week", "Date"] if include_period else []) + columns


def _bonus_club_associate_report_rows(summaries: list[BonusClubSummary], selected_associate: str, *, aggregate: bool = False, period_label: str = "") -> list[dict[str, object]]:
    if aggregate:
        return _aggregate_associate_report_rows(summaries, selected_associate, "bonus_club", period_label)
    rows: list[dict[str, object]] = []
    totals: dict[str, list[float]] = {"total_transactions": [], "transactions_with_club": [], "capture_rate": []}
    selected_name = ""
    selected_number = selected_associate
    for summary in summaries:
        upload = cast(ReportUpload, summary.report_upload)
        summary = _refresh_bonus_club_summary_if_needed(upload, summary)
        if summary is None:
            continue
        raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        fiscal_obj = raw_json.get("fiscal") if isinstance(raw_json, dict) else {}
        fiscal = fiscal_obj if isinstance(fiscal_obj, dict) else {}
        week_value = summary.fiscal_week or fiscal.get("fiscal_week_number") or fiscal.get("fiscal_week") or ""
        date_value = summary.fiscal_period_end or fiscal.get("week_ending_date")
        week_label = str(week_value) if week_value != "" else ""
        date_label = _format_display_date(date_value)
        match = _find_associate_row(raw_json.get("associate_rows"), selected_associate)
        if not isinstance(match, dict):
            continue
        selected_number = str(match.get("associate_number", selected_number) or selected_number)
        selected_name = str(match.get("name", selected_name) or selected_name)
        metrics_obj = match.get("metrics") if isinstance(match.get("metrics"), dict) else {}
        metrics = metrics_obj if isinstance(metrics_obj, dict) else {}
        rows.append(
            {
                "summary": summary,
                "row_kind": "associate_week",
                "week": week_label,
                "date": date_label,
                "name": selected_name,
                "associate_number": selected_number,
                "row_class": f"report-week-row {'report-week-row-even' if len(rows) % 2 == 0 else 'report-week-row-odd'}",
                "values": [
                    week_label,
                    date_label,
                    selected_number,
                    selected_name,
                    _format_number(metrics.get("total_transactions")),
                    _format_number(metrics.get("transactions_with_club")),
                    _format_percent(metrics.get("capture_rate")),
                ],
            }
        )
        if metrics.get("total_transactions") is not None:
            totals["total_transactions"].append(_coerce_number(metrics.get("total_transactions")) or 0.0)
        if metrics.get("transactions_with_club") is not None:
            totals["transactions_with_club"].append(_coerce_number(metrics.get("transactions_with_club")) or 0.0)
        if metrics.get("capture_rate") is not None:
            totals["capture_rate"].append(_coerce_number(metrics.get("capture_rate")) or 0.0)
    if not rows:
        return []
    total_transactions = sum(totals["total_transactions"])
    total_with_club = sum(totals["transactions_with_club"])
    total_capture_rate = (total_with_club / total_transactions * 100) if total_transactions else None
    rows.append(
        {
            "summary": rows[-1]["summary"],
            "row_kind": "associate_total",
            "week": "Total",
            "date": "",
            "name": selected_name,
            "associate_number": selected_number,
            "row_class": "report-summary-row report-summary-total",
            "values": [
                "Total",
                "",
                selected_number,
                selected_name,
                _format_number(total_transactions),
                _format_number(total_with_club),
                _format_percent(total_capture_rate),
            ],
        }
    )
    rows.append(
        {
            "summary": rows[-1]["summary"],
            "row_kind": "associate_spacer",
            "week": "",
            "date": "",
            "name": "",
            "associate_number": "",
            "row_class": "report-spacer-row",
            "values": ["", "", "", "", "", "", ""],
        }
    )
    rows.append(
        {
            "summary": rows[-1]["summary"],
            "row_kind": "associate_average",
            "week": "Average",
            "date": "",
            "name": selected_name,
            "associate_number": selected_number,
            "row_class": "report-summary-row report-summary-average",
            "values": [
                "Average",
                "",
                selected_number,
                selected_name,
                _format_average_number(totals["total_transactions"]),
                _format_average_number(totals["transactions_with_club"]),
                _format_percent(_average_number(totals["capture_rate"])),
            ],
        }
    )
    return rows


def _normalize_person_name(value: object) -> str:
    """Match display-only case/whitespace and ``Last, First`` differences."""
    name = " ".join(str(value or "").split()).casefold()
    if "," not in name:
        return name
    last, first = name.split(",", 1)
    return " ".join(f"{first} {last}".split())


def _find_associate_row(associate_rows: object, selected_associate: str) -> dict[str, object] | None:
    if not isinstance(associate_rows, list):
        return None
    if selected_associate:
        for row in associate_rows:
            if not isinstance(row, dict):
                continue
            associate_number = str(row.get("associate_number", "")).strip()
            name = str(row.get("name", "")).strip()
            if selected_associate == associate_number or _normalize_person_name(selected_associate) == _normalize_person_name(name):
                return row
    for row in associate_rows:
        if isinstance(row, dict):
            return row
    return None


def _associate_options_for_report(report_type: str, summaries: list[Any]) -> list[dict[str, str]]:
    if report_type not in {"gift_cards", "bonus_club", "segments"}:
        return []
    options: dict[str, str] = {}
    for summary in summaries:
        raw_json = summary.raw_json if hasattr(summary, "raw_json") and isinstance(summary.raw_json, dict) else {}
        if report_type == "segments":
            rows = raw_json.get("manager_rows") if isinstance(raw_json, dict) else []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name", "")).strip()
                if not name:
                    continue
                options.setdefault(name, name)
            continue
        associate_rows = raw_json.get("associate_rows") if isinstance(raw_json, dict) else []
        if not isinstance(associate_rows, list):
            continue
        for row in associate_rows:
            if not isinstance(row, dict):
                continue
            associate_number = str(row.get("associate_number", "")).strip()
            name = str(row.get("name", "")).strip()
            if not associate_number or not name:
                continue
            options.setdefault(associate_number, name)
    return [{"value": value, "label": label} for value, label in sorted(options.items(), key=lambda item: item[1].casefold())]


def _average_number(values: list[float]) -> Decimal | None:
    decimals = [Decimal(str(value)) for value in values if value is not None]
    if not decimals:
        return None
    return sum(decimals) / Decimal(len(decimals))


def _format_average_number(values: list[float]) -> str:
    average = _average_number(values)
    if average is None:
        return ""
    if average == average.to_integral_value():
        return f"{int(average):,}"
    return f"{average:,.2f}".rstrip("0").rstrip(".")


def _refresh_bonus_club_summary_if_needed(upload: ReportUpload, summary: BonusClubSummary | None) -> BonusClubSummary | None:
    if summary is None:
        return None
    raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
    parse_version = int(raw_json.get("parse_version", 0) or 0)
    associate_rows = raw_json.get("associate_rows") if isinstance(raw_json, dict) else None
    store_total = raw_json.get("store_total") if isinstance(raw_json, dict) else None
    if parse_version >= int(getattr(BonusClubReport, "parse_version", 1)):
        if isinstance(associate_rows, list) and associate_rows and isinstance(store_total, dict):
            return summary
    raw_text = str(raw_json.get("raw_text") or "")
    if not raw_text:
        raw_text = _extract_pdf_text_from_upload(upload)
    if not raw_text:
        return summary
    report = get("bonus_club").parse(raw_text)
    parsed_payload = report.payload if isinstance(report.payload, dict) else {}
    parsed_fiscal_obj = parsed_payload.get("fiscal")
    parsed_fiscal = parsed_fiscal_obj if isinstance(parsed_fiscal_obj, dict) else {}
    defaults: dict[str, object] = {
        "fiscal_year": int(parsed_fiscal.get("fiscal_year", summary.fiscal_year)),
        "fiscal_week": int(parsed_fiscal.get("fiscal_week_number", summary.fiscal_week)),
        "fiscal_period_start": _parse_date(report.period_start),
        "fiscal_period_end": _parse_date(report.period_end),
        "raw_json": parsed_payload,
    }
    return getattr(BonusClubSummary, "objects").update_or_create(report_upload=upload, defaults=defaults)[0]


def _refresh_gift_cards_summary_if_needed(upload: ReportUpload, summary: GiftCardsSummary | None) -> GiftCardsSummary | None:
    if summary is None:
        return None
    raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
    parse_version = int(raw_json.get("parse_version", 0) or 0)
    weekly_sales_dpt = raw_json.get("weekly_sales_dpt")
    associate_rows = raw_json.get("associate_rows") if isinstance(raw_json, dict) else None
    store_total = raw_json.get("store_total") if isinstance(raw_json, dict) else None
    if parse_version >= int(getattr(GiftCardsReport, "parse_version", 1)):
        if weekly_sales_dpt is not None and isinstance(associate_rows, list) and associate_rows and isinstance(store_total, dict):
            return summary
    raw_text = str(raw_json.get("raw_text") or "")
    if not raw_text:
        raw_text = _extract_pdf_text_from_upload(upload)
    if not raw_text:
        return summary
    report = get("gift_cards").parse(raw_text)
    parsed_payload = report.payload if isinstance(report.payload, dict) else {}
    parsed_fiscal_obj = parsed_payload.get("fiscal")
    parsed_fiscal = parsed_fiscal_obj if isinstance(parsed_fiscal_obj, dict) else {}
    period_end = _parse_date(report.period_end)
    dpt_value, dpt_source_name = _gift_cards_weekly_sales_dpt(period_end)
    defaults: dict[str, object] = {
        "fiscal_year": int(parsed_fiscal.get("fiscal_year", summary.fiscal_year)),
        "fiscal_week": int(parsed_fiscal.get("fiscal_week_number", summary.fiscal_week)),
        "fiscal_period_start": _parse_date(report.period_start),
        "fiscal_period_end": period_end,
        "raw_json": _gift_cards_enrich_payload(parsed_payload, dpt_value, dpt_source_name),
    }
    return getattr(GiftCardsSummary, "objects").update_or_create(report_upload=upload, defaults=defaults)[0]


def _gift_cards_enrich_payload(payload: dict[str, object], dpt_value: object | None, dpt_source_name: str) -> dict[str, object]:
    enriched = dict(payload)
    associate_rows = enriched.get("associate_rows") if isinstance(enriched, dict) else []
    store_total = enriched.get("store_total") if isinstance(enriched, dict) else None
    enriched["weekly_sales_dpt"] = dpt_value
    enriched["weekly_sales_source_name"] = dpt_source_name
    enriched["weekly_sales_missing"] = dpt_value is None
    if isinstance(associate_rows, list):
        enriched["associate_rows"] = [_gift_cards_apply_dpt_to_row(row, dpt_value) for row in associate_rows if isinstance(row, dict)]
    if isinstance(store_total, dict):
        enriched["store_total"] = _gift_cards_apply_dpt_to_row(store_total, dpt_value)
    summary_rows = enriched.get("summary_rows")
    if isinstance(summary_rows, list):
        updated_rows: list[dict[str, object]] = []
        for row in summary_rows:
            if isinstance(row, dict):
                updated_rows.append(_gift_cards_apply_dpt_to_row(row, dpt_value))
        enriched["summary_rows"] = updated_rows
    return enriched


def _gift_cards_apply_dpt_to_row(row: dict[str, object], dpt_value: object | None) -> dict[str, object]:
    metrics_obj = row.get("metrics") if isinstance(row, dict) else {}
    metrics = dict(metrics_obj) if isinstance(metrics_obj, dict) else {}
    total_transactions = _coerce_decimal(metrics.get("total_transactions"))
    bonus_transactions = _coerce_decimal(metrics.get("gc_bonus_transactions"))
    goal_transactions = total_transactions * Decimal("0.18") if total_transactions is not None else None
    transaction_gap = goal_transactions - bonus_transactions if goal_transactions is not None and bonus_transactions is not None else None
    missed_opportunities = None
    if dpt_value is not None and transaction_gap is not None:
        missed_opportunities = max(transaction_gap, Decimal("0")) * _coerce_decimal(dpt_value)
        missed_opportunities = missed_opportunities.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    metrics["goal_transactions"] = float(goal_transactions.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if goal_transactions is not None else None
    metrics["transaction_gap"] = float(transaction_gap.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if transaction_gap is not None else None
    metrics["weekly_sales_dpt"] = float(_coerce_decimal(dpt_value)) if dpt_value is not None else None
    metrics["missed_opportunities"] = float(missed_opportunities) if missed_opportunities is not None else None
    enriched = dict(row)
    enriched["metrics"] = metrics
    return enriched


def _gift_cards_weekly_sales_dpt(period_end: date | None) -> tuple[object | None, str]:
    if period_end is None:
        return None, ""
    summary = (
        getattr(WeeklySalesSummary, "objects")
        .select_related("report_upload")
        .filter(fiscal_period_end=period_end)
        .order_by("-fiscal_year", "-fiscal_week", "-id")
        .first()
    )
    if summary is None:
        return None, ""
    raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
    kpis = raw_json.get("summary_kpis") if isinstance(raw_json, dict) else {}
    kpis_dict = kpis if isinstance(kpis, dict) else {}
    dpt_value = kpis_dict.get("dpt")
    if dpt_value is None:
        dpt_value = raw_json.get("dpt")
    if dpt_value is None:
        return None, str(summary.report_upload.source_name)
    return float(_coerce_decimal(dpt_value)), str(summary.report_upload.source_name)


def _format_number(value: object | None) -> str:
    if value is None:
        return ""
    try:
        number = Decimal(str(value))
    except Exception:
        return str(value)
    if number == number.to_integral():
        return f"{int(number):,}"
    return f"{number.normalize():f}"


def _coerce_decimal(value: object | None) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal("0")
    text = str(value).strip().replace(",", "").replace("$", "")
    if text.endswith("%"):
        text = text[:-1]
    if not text:
        return Decimal("0")
    return Decimal(text)


def _coerce_int_or_none(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text or text.lower() == "none":
        return None
    try:
        return int(float(text.replace(",", "")))
    except (TypeError, ValueError):
        return None


def _refresh_segments_summary_if_needed(upload: ReportUpload, summary: SegmentsSummary | None) -> SegmentsSummary | None:
    if summary is None:
        return None
    raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
    parse_version = int(raw_json.get("parse_version", 0) or 0)
    manager_rows = raw_json.get("manager_rows") if isinstance(raw_json, dict) else None
    store_total = raw_json.get("store_total") if isinstance(raw_json, dict) else None
    if parse_version >= int(getattr(SegmentsReport, "parse_version", 1)):
        if isinstance(manager_rows, list) and manager_rows and isinstance(store_total, dict):
            return summary
    raw_text = str(raw_json.get("raw_text") or "")
    if not raw_text:
        raw_text = _extract_pdf_text_from_upload(upload)
    if not raw_text:
        return summary
    report = get("segments").parse(raw_text)
    parsed_payload = report.payload if isinstance(report.payload, dict) else {}
    parsed_fiscal_obj = parsed_payload.get("fiscal")
    parsed_fiscal = parsed_fiscal_obj if isinstance(parsed_fiscal_obj, dict) else {}
    defaults: dict[str, object] = {
        "fiscal_year": int(parsed_fiscal.get("fiscal_year", summary.fiscal_year)),
        "fiscal_week": int(parsed_fiscal.get("fiscal_week_number", summary.fiscal_week)),
        "fiscal_period_start": _parse_date(report.period_start),
        "fiscal_period_end": _parse_date(report.period_end),
        "raw_json": parsed_payload,
    }
    return getattr(SegmentsSummary, "objects").update_or_create(report_upload=upload, defaults=defaults)[0]


def _report_timeframe_label(mode: str, filtered: list[Any], range_start: date, range_end: date, week_end: date, today: date) -> str:
    if mode == "month":
        return "Showing monthly totals"
    if mode == "quarter":
        quarter = (today.month - 1) // 3 + 1
        return f"Showing Q{quarter} totals"
    if mode == "range":
        if range_start == range_end:
            return f"Showing totals for {_format_display_date(range_start)}"
        return f"Showing totals for {_format_display_date(range_start)}–{_format_display_date(range_end)}"
    if mode == "week":
        return f"Showing totals for {_format_display_date(week_end)}"
    return "Showing totals for last week"


def _report_date_state(request: HttpRequest, report_type: str) -> dict[str, object]:
    today = _current_date()
    mode = str(request.GET.get("date_filter", "last_week"))
    if mode == "all":
        mode = "last_week"
    if report_type == "ranking":
        summaries: list[Any] = list(getattr(RankingSummary, "objects").select_related("report_upload").order_by("fiscal_year", "fiscal_week", "id"))
        headers = _ranking_report_headers()
        row_builder: Any = _ranking_report_rows
    elif report_type == "segments":
        summaries = list(getattr(SegmentsSummary, "objects").select_related("report_upload").order_by("fiscal_year", "fiscal_week", "id"))
        headers = _segments_report_headers()
        row_builder = _segments_report_rows
    elif report_type == "gift_cards":
        summaries = list(getattr(GiftCardsSummary, "objects").select_related("report_upload").order_by("fiscal_year", "fiscal_week", "id"))
        headers = _gift_cards_report_headers()
        row_builder = _gift_cards_report_rows
    elif report_type == "bonus_club":
        summaries = list(getattr(BonusClubSummary, "objects").select_related("report_upload").order_by("fiscal_year", "fiscal_week", "id"))
        headers = _bonus_club_report_headers()
        row_builder = _bonus_club_report_rows
    else:
        summaries = list(getattr(WeeklySalesSummary, "objects").select_related("report_upload").order_by("fiscal_year", "fiscal_week", "id"))
        headers = _weekly_report_headers()
        if mode == "month":
            row_builder = _weekly_month_report_rows
        elif mode == "quarter":
            row_builder = _weekly_quarter_report_rows
        elif mode == "year":
            row_builder = _weekly_year_report_rows
        else:
            row_builder = _weekly_report_rows
    total_count = len(summaries)
    latest_summary = summaries[-1] if summaries else None
    latest_fiscal_year = latest_summary.fiscal_year if latest_summary and latest_summary.fiscal_year else today.year
    week_end_text = str(request.GET.get("week_end", today.isoformat()))
    range_start_text = str(request.GET.get("range_start", today.isoformat()))
    range_end_text = str(request.GET.get("range_end", today.isoformat()))
    selected_associate = str(request.GET.get("associate", "")).strip()
    associate_options = _associate_options_for_report(report_type, summaries)
    if report_type == "segments" and mode == "range" and not selected_associate and associate_options:
        selected_associate = str(associate_options[0]["value"])
    selected_associate_label = next((str(option["label"]) for option in associate_options if str(option["value"]) == selected_associate), "")
    range_select_label = "Manager" if report_type == "segments" else "Associate"
    week_end = _parse_date(week_end_text) or today
    range_start = _parse_date(range_start_text) or today
    range_end = _parse_date(range_end_text) or today
    if range_start > range_end:
        range_start, range_end = range_end, range_start

    filtered: list[Any]
    if mode == "last_week":
        filtered = summaries[-1:] if summaries else []
    elif mode == "month":
        filtered = [summary for summary in summaries if summary.fiscal_period_end and summary.fiscal_period_end.year == today.year and summary.fiscal_period_end.month == today.month]
    elif mode == "quarter":
        current_quarter = (today.month - 1) // 3
        filtered = [summary for summary in summaries if summary.fiscal_period_end and summary.fiscal_period_end.year == today.year and ((summary.fiscal_period_end.month - 1) // 3) == current_quarter]
    elif mode == "year" and report_type in {"weekly_sales", "ranking"}:
        filtered = [summary for summary in summaries if summary.fiscal_year == latest_fiscal_year]
    elif mode == "week":
        filtered = [summary for summary in summaries if summary.fiscal_period_end == week_end]
    elif mode == "range":
        filtered = [summary for summary in summaries if summary.fiscal_period_end and range_start <= summary.fiscal_period_end <= range_end]
    else:
        mode = "last_week"
        filtered = summaries[-1:] if summaries else []

    report_table_class = "report-grid striped"
    if report_type == "weekly_sales" and mode == "year":
        report_table_class = "report-grid report-grid-year"
    multi_period = len(filtered) > 1 and mode in {"month", "quarter", "range"}
    period_label = _report_timeframe_label(mode, filtered, range_start, range_end, week_end, today)
    if report_type == "gift_cards" and mode in {"month", "quarter", "range"}:
        headers = _gift_cards_associate_report_headers(include_period=False)
        rows = _gift_cards_associate_report_rows(filtered, "", aggregate=True, period_label=period_label)
        report_table_class = "report-grid report-grid-associate"
    elif report_type == "bonus_club" and mode in {"month", "quarter", "range"}:
        headers = _bonus_club_associate_report_headers(include_period=False)
        rows = _bonus_club_associate_report_rows(filtered, "", aggregate=True, period_label=period_label)
        report_table_class = "report-grid report-grid-associate"
    elif report_type == "segments" and mode in {"month", "quarter", "range"}:
        headers = _segments_range_report_headers(include_period=False)
        rows = _segments_aggregate_report_rows(filtered)
        report_table_class = "report-grid report-grid-associate"
    else:
        rows = row_builder(filtered)
    note = ""
    if report_type == "gift_cards":
        if mode in {"month", "quarter", "range"}:
            note = f"{period_label} for all associates."
        else:
            note = "Waiting on weekly sales." if any(not row.get("weekly_sales_ready", True) for row in rows) else "One row per associate, store total at bottom."
    elif report_type == "bonus_club":
        if mode in {"month", "quarter", "range"}:
            note = f"{period_label} for all associates."
        else:
            note = "One row per associate, store total at bottom."
    elif report_type == "segments" and mode in {"month", "quarter", "range"}:
        note = f"{period_label} for all managers, with combined store totals."
    elif report_type == "weekly_sales" and mode == "year":
        note = "Monthly, quarterly, and yearly totals for the selected fiscal year."
    elif report_type == "ranking" and mode == "year":
        note = "All weekly ranking rows for the selected fiscal year."

    return {
        "headers": headers,
        "rows": rows,
        "total_count": total_count,
        "filtered_count": len(filtered),
        "week_end": week_end_text,
        "range_start": range_start_text,
        "range_end": range_end_text,
        "year": latest_fiscal_year,
        "mode": mode,
        "note": note,
        "associate_options": associate_options,
        "selected_associate": selected_associate,
        "selected_associate_label": selected_associate_label,
        "range_select_label": range_select_label,
        "table_class": report_table_class,
        "period_label": period_label,
    }


def _dashboard_reports():
    for summary in getattr(WeeklySalesSummary, "objects").select_related("report_upload").order_by("fiscal_year", "fiscal_week", "id"):
        summary = _refresh_weekly_summary_if_needed(cast(ReportUpload, summary.report_upload), summary)
        if summary is None:
            continue
        raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        yield {
            "report_type": "weekly_sales",
            "source_name": summary.report_upload.source_name,
            "period_start": summary.fiscal_period_start.isoformat() if summary.fiscal_period_start else None,
            "period_end": summary.fiscal_period_end.isoformat() if summary.fiscal_period_end else None,
            "payload": raw_json,
            "raw_rows": raw_json.get("summary_rows", []),
        }


def _dashboard_weekly_sales_summaries(limit: int = 6) -> list[WeeklySalesSummary]:
    summaries = list(
        getattr(WeeklySalesSummary, "objects")
        .select_related("report_upload")
        .order_by("fiscal_year", "fiscal_week", "id")
    )
    if limit > 0:
        summaries = summaries[-limit:]
    return summaries


def _dashboard_title(summaries: list[WeeklySalesSummary]) -> str:
    if not summaries:
        return "214 Temecula"
    return f"214 Temecula: Week {summaries[-1].fiscal_week:02d}"


def _dashboard_subtitle(summaries: list[WeeklySalesSummary]) -> str:
    if not summaries:
        return "Last week performance"
    latest = summaries[-1]
    period_end = cast(date | None, latest.fiscal_period_end)
    period_start = cast(date | None, latest.fiscal_period_start)
    if period_end and period_start is None:
        period_start = period_end - timedelta(days=6)
    if period_start and period_end:
        return f"Last week performance for {period_start:%m/%d/%y} to {period_end:%m/%d/%y}"
    return "Last week performance"


def _dashboard_latest_summary(model: type[Any]) -> Any | None:
    summaries = list(
        getattr(model, "objects")
        .select_related("report_upload")
        .order_by("fiscal_year", "fiscal_week", "id")
    )
    return summaries[-1] if summaries else None


def _dashboard_store_percentage(summary: Any | None, metric_key: str) -> str:
    if summary is None:
        return ""
    raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
    store_total_obj = raw_json.get("store_total") if isinstance(raw_json, dict) else None
    store_total = store_total_obj if isinstance(store_total_obj, dict) else {}
    metrics_obj = store_total.get("metrics") if isinstance(store_total.get("metrics"), dict) else {}
    return _format_percent(metrics_obj.get(metric_key))


def _dashboard_bonus_gift_table() -> dict[str, object]:
    """Return last-week Bonus Club/Gift Card rows with store comparisons."""
    gift = _dashboard_latest_summary(GiftCardsSummary)
    bonus = _dashboard_latest_summary(BonusClubSummary)
    gift_raw = gift.raw_json if gift and isinstance(gift.raw_json, dict) else {}
    bonus_raw = bonus.raw_json if bonus and isinstance(bonus.raw_json, dict) else {}

    def rows_by_person(raw: dict[str, object]) -> dict[str, dict[str, object]]:
        rows = raw.get("associate_rows") if isinstance(raw.get("associate_rows"), list) else []
        result: dict[str, dict[str, object]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            number = str(row.get("associate_number") or "").strip()
            name = str(row.get("name") or "").strip()
            key = number or _normalize_person_name(name)
            if key:
                result[key] = row
        return result

    gift_rows, bonus_rows = rows_by_person(gift_raw), rows_by_person(bonus_raw)
    gift_store = gift_raw.get("store_total") if isinstance(gift_raw.get("store_total"), dict) else {}
    bonus_store = bonus_raw.get("store_total") if isinstance(bonus_raw.get("store_total"), dict) else {}
    gift_store_metrics = gift_store.get("metrics") if isinstance(gift_store.get("metrics"), dict) else {}
    bonus_store_metrics = bonus_store.get("metrics") if isinstance(bonus_store.get("metrics"), dict) else {}
    gift_store_rate = _coerce_number(gift_store_metrics.get("bonus_percent"))
    bonus_store_rate = _coerce_number(bonus_store_metrics.get("capture_rate"))
    headers = ["Associate", "Bonus Club Total", "Club #", "Club %", "GC Total", "GC Bonus #", "GC %", "Missed Ops"]
    rows: list[dict[str, object]] = []
    for key in sorted(set(gift_rows) | set(bonus_rows), key=lambda item: str((gift_rows.get(item) or bonus_rows.get(item) or {}).get("name", "")).casefold()):
        gift_row, bonus_row = gift_rows.get(key, {}), bonus_rows.get(key, {})
        gift_metrics = gift_row.get("metrics") if isinstance(gift_row.get("metrics"), dict) else {}
        bonus_metrics = bonus_row.get("metrics") if isinstance(bonus_row.get("metrics"), dict) else {}
        gift_rate = _coerce_number(gift_metrics.get("bonus_percent"))
        bonus_rate = _coerce_number(bonus_metrics.get("capture_rate"))
        rows.append({
            "values": [str(gift_row.get("name") or bonus_row.get("name") or ""), _format_number(bonus_metrics.get("total_transactions")), _format_number(bonus_metrics.get("transactions_with_club")), _format_percent(bonus_rate), _format_number(gift_metrics.get("total_transactions")), _format_number(gift_metrics.get("gc_bonus_transactions")), _format_percent(gift_rate), _format_currency(gift_metrics.get("missed_opportunities"))],
            "bonus_above_store": bonus_rate is not None and bonus_store_rate is not None and bonus_rate > bonus_store_rate,
            "gift_above_store": gift_rate is not None and gift_store_rate is not None and gift_rate > gift_store_rate,
            "row_class": f"report-week-row {'report-week-row-even' if len(rows) % 2 else 'report-week-row-odd'}",
        })
    if gift_store or bonus_store:
        rows.append({
            "values": [str(bonus_store.get("name") or gift_store.get("name") or "Store Total"), _format_number(bonus_store_metrics.get("total_transactions")), _format_number(bonus_store_metrics.get("transactions_with_club")), _format_percent(bonus_store_rate), _format_number(gift_store_metrics.get("total_transactions")), _format_number(gift_store_metrics.get("gc_bonus_transactions")), _format_percent(gift_store_rate), _format_currency(gift_store_metrics.get("missed_opportunities"))],
            "row_class": "report-summary-row report-store-total-row",
        })
    return {"headers": headers, "rows": rows}


def _dashboard_ranking_summaries(limit: int = 4) -> list[RankingSummary]:
    summaries = list(
        getattr(RankingSummary, "objects")
        .select_related("report_upload")
        .order_by("fiscal_year", "fiscal_week", "id")
    )
    if limit > 0:
        summaries = summaries[-limit:]
    return summaries


def _dashboard_segment_summaries(limit: int = 4) -> list[SegmentsSummary]:
    summaries = list(
        getattr(SegmentsSummary, "objects")
        .select_related("report_upload")
        .order_by("fiscal_year", "fiscal_week", "id")
    )
    if limit > 0:
        summaries = summaries[-limit:]
    return summaries


def _dashboard_segment_rows(summaries: list[SegmentsSummary]) -> list[dict[str, object]]:
    rows = _segments_report_rows(summaries)
    manager_rows = [row for row in rows if row.get("row_kind") == "manager"]
    if not manager_rows:
        return manager_rows

    highlight_metrics = {
        "success_segments": "highlight_success_segments",
        "success_pct": "highlight_success",
        "store_sales": "highlight_store_sales",
        "sales_trans": "highlight_sales_trans",
        "conversion": "highlight_conversion",
        "dpt": "highlight_dpt",
        "upt": "highlight_upt",
    }
    rows_by_week: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in manager_rows:
        summary = row.get("summary")
        week_key = (
            getattr(summary, "pk", None),
            getattr(summary, "fiscal_year", None),
            getattr(summary, "fiscal_week", None),
            row.get("week"),
            row.get("date"),
        )
        rows_by_week.setdefault(week_key, []).append(row)

    for weekly_rows in rows_by_week.values():
        best_values = {}
        for metric in highlight_metrics:
            values = [
                value
                for row in weekly_rows
                if (value := _coerce_number(cast(dict[str, object], row.get("metrics") or {}).get(metric))) is not None
            ]
            best_values[metric] = max(values) if values else None
        for row in weekly_rows:
            metrics = cast(dict[str, object], row.get("metrics") or {})
            for metric, flag in highlight_metrics.items():
                value = _coerce_number(metrics.get(metric))
                row[flag] = value is not None and best_values[metric] is not None and value == best_values[metric]
    return manager_rows


def _dashboard_trend_rows(summaries: list[WeeklySalesSummary]) -> list[dict[str, object]]:
    if len(summaries) < 2:
        return []
    first = summaries[0]
    last = summaries[-1]
    first_raw = first.raw_json if isinstance(first.raw_json, dict) else {}
    last_raw = last.raw_json if isinstance(last.raw_json, dict) else {}
    first_summary = cast(dict[str, object], first_raw.get("summary_kpis") if isinstance(first_raw.get("summary_kpis"), dict) else {})
    last_summary = cast(dict[str, object], last_raw.get("summary_kpis") if isinstance(last_raw.get("summary_kpis"), dict) else {})
    spacer = {
        "row_class": "report-spacer-row",
        "values": [""] * len(_weekly_report_headers()),
    }
    values = ["Trend", ""]
    for label, keys in _WEEKLY_METRICS:
        if label in {"Week", "Date"} or label in _REPORT_VIEW_HIDDEN_METRICS:
            continue
        first_value = _weekly_metric_numeric_value(first, first_raw, first_summary, label, keys)
        last_value = _weekly_metric_numeric_value(last, last_raw, last_summary, label, keys)
        values.append(_format_metric_trend(label, first_value, last_value))
    return [
        spacer,
        {
            "row_class": "report-summary-row report-summary-trend",
            "values": values,
        },
    ]


def _parse_and_store_summary(upload: ReportUpload) -> None:
    report_type = str(upload.report_type or "weekly_sales")
    try:
        raw_text = _extract_pdf_text_from_upload(upload)
        report = get(report_type).parse(raw_text)
        fiscal = report.payload.get("fiscal") if isinstance(report.payload, dict) else None
        if not isinstance(fiscal, dict):
            fiscal = {}
        fiscal_year_value = fiscal.get("fiscal_year")
        fiscal_week_value = fiscal.get("fiscal_week_number", fiscal.get("fiscal_week"))
        fiscal_year = _coerce_int_or_none(fiscal_year_value)
        fiscal_week = _coerce_int_or_none(fiscal_week_value)
        period_start = _parse_date(report.period_start)
        period_end = _parse_date(report.period_end)
        if period_end and period_start is None:
            period_start = period_end - timedelta(days=6)
        if (fiscal_year is None or fiscal_week is None) and period_start and period_end:
            try:
                fallback_fiscal = as_dict(calculate_fiscal_week(period_start, period_end))
            except Exception:
                fallback_fiscal = {}
            if fiscal_year is None:
                fiscal_year = _coerce_int_or_none(fallback_fiscal.get("fiscal_year"))
            if fiscal_week is None:
                fiscal_week = _coerce_int_or_none(fallback_fiscal.get("fiscal_week_number", fallback_fiscal.get("fiscal_week")))
        if fiscal_year is None or fiscal_week is None:
            raise ValueError("Unable to determine fiscal year/week from report.")
        defaults: dict[str, object] = {
            "fiscal_year": fiscal_year,
            "fiscal_week": fiscal_week,
            "fiscal_period_start": period_start,
            "fiscal_period_end": period_end,
            "raw_json": report.payload,
        }
        if report_type == "weekly_sales":
            ai_result = summarize_weekly_sales_report(
                report.payload,
                source_name=str(upload.source_name),
                raw_text=raw_text,
            )
            if ai_result.ok:
                defaults.update(
                    {
                        "ai_summary": ai_result.summary,
                        "ai_provider": ai_result.provider,
                        "ai_model": ai_result.model,
                        "ai_payload": ai_result.payload,
                        "ai_error": "",
                        "ai_generated_at": timezone.now(),
                    }
                )
            elif ai_result.enabled:
                defaults.update(
                    {
                        "ai_summary": "",
                        "ai_provider": ai_result.provider,
                        "ai_model": ai_result.model,
                        "ai_payload": ai_result.payload,
                        "ai_error": ai_result.error,
                    }
                )
            getattr(WeeklySalesSummary, "objects").update_or_create(
                report_upload=upload,
                defaults=defaults,
            )
        elif report_type == "ranking":
            getattr(RankingSummary, "objects").update_or_create(
                report_upload=upload,
                defaults=defaults,
            )
        elif report_type == "segments":
            getattr(SegmentsSummary, "objects").update_or_create(
                report_upload=upload,
                defaults=defaults,
            )
        elif report_type == "gift_cards":
            getattr(GiftCardsSummary, "objects").update_or_create(
                report_upload=upload,
                defaults=defaults,
            )
        elif report_type == "bonus_club":
            getattr(BonusClubSummary, "objects").update_or_create(
                report_upload=upload,
                defaults=defaults,
            )
        else:
            raise ValueError(f"Unsupported report type: {report_type}")
        upload.parse_status = "parsed"
        upload.parse_error = ""
        upload.parsed_at = timezone.now()
        setattr(upload, "source_name", Path(str(upload.source_name)).name)
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


_WEEKLY_METRICS = (
    ("Week", ("fiscal_week",)),
    ("Date", ("week_ending_date", "period_end")),
    ("Sales", ("total_sales",)),
    ("LY Sales", ("ly_total_sales",)),
    ("Target", ("target_total_sales", "t_total_sales", "ttotal_sales")),
    ("% Tgt", ("pct_to_target", "percent_to_target")),
    ("Ent Sales", ("enterprise_sales",)),
    ("Traffic Lev", ("traffic_leverage",)),
    ("Conv", ("conversion_rate", "conversion")),
    ("LY Conv", ("ly_conversion_rate", "ly_conversion")),
    ("Traffic", ("traffic",)),
    ("LY Traffic", ("ly_traffic",)),
    ("% Δ LY Traf", ("pct_change_to_ly_traffic", "percent_change_to_ly_traffic")),
    ("Sales Tr", ("sales_trans",)),
    ("DPT", ("dpt",)),
    ("LY DPT", ("ly_dpt",)),
    ("UPT", ("upt",)),
    ("Cap Rate", ("capture_rate",)),
    ("STAR", ("star",)),
)

_CURRENCY_METRICS = {"Sales", "LY Sales", "Target", "Ent Sales"}
_PERCENT_METRICS = {"% Tgt", "Conv", "LY Conv", "% Δ LY Traf", "Cap Rate"}
# Keep these metrics in the persisted/raw payload, but omit them from the
# compact report viewer and dashboard tables.
_REPORT_VIEW_HIDDEN_METRICS = {"Ent Sales", "LY Traffic", "Sales Tr", "Cap Rate", "STAR"}


_RANKING_VIEW_METRICS = (
    ("sales", "Sales"),
    ("sales_v_plan", "Sales v plan"),
    ("sales_v_ly", "Sales v ly"),
    ("dpt", "DPT"),
    ("upt", "UPT"),
    ("parties", "Parties"),
    ("traffic_bw", "Traffic b/w"),
    ("conv_ty", "Conv ty"),
    ("conv_bw", "Conv b/w"),
    ("stuffers", "Stuffers"),
)


def _weekly_metrics_for_display(
    summary: WeeklySalesSummary | None,
    raw_json: dict[str, object] | None,
) -> tuple[list[str], list[object]]:
    raw_json = raw_json if isinstance(raw_json, dict) else {}
    fiscal = raw_json.get("fiscal") if isinstance(raw_json.get("fiscal"), dict) else {}
    summary_kpis = raw_json.get("summary_kpis") if isinstance(raw_json.get("summary_kpis"), dict) else {}
    headers: list[str] = []
    values: list[object] = []
    for label, keys in _WEEKLY_METRICS:
        headers.append(label)
        values.append(_weekly_metric_value(summary, fiscal, summary_kpis, label, keys))
    return headers, values


def _weekly_report_headers() -> list[str]:
    return [label for label, _ in _WEEKLY_METRICS if label not in _REPORT_VIEW_HIDDEN_METRICS]


def _weekly_report_rows(summaries: list[WeeklySalesSummary]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    total = len(summaries)
    for index, summary in enumerate(summaries):
        summary = _refresh_weekly_summary_if_needed(cast(ReportUpload, summary.report_upload), summary)
        if summary is None:
            continue
        raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
        headers, values = _weekly_metrics_for_display(summary, raw_json)
        filtered_values = [value for label, value in zip(headers, values) if label not in _REPORT_VIEW_HIDDEN_METRICS]
        row_class = "report-week-row"
        if index == total - 1:
            row_class = "report-week-row report-week-row-latest"
        rows.append(
            {
                "summary": summary,
                "values": filtered_values,
                "row_class": row_class,
            }
        )
    return rows


def _weekly_year_report_rows(summaries: list[WeeklySalesSummary]) -> list[dict[str, object]]:
    return _weekly_period_report_rows(summaries, include_month_summary=True, include_quarter_summary=True, include_year_summary=True)


def _weekly_month_report_rows(summaries: list[WeeklySalesSummary]) -> list[dict[str, object]]:
    return _weekly_period_report_rows(summaries, include_month_summary=True, include_quarter_summary=False, include_year_summary=False)


def _weekly_quarter_report_rows(summaries: list[WeeklySalesSummary]) -> list[dict[str, object]]:
    return _weekly_period_report_rows(summaries, include_month_summary=True, include_quarter_summary=True, include_year_summary=False)


def _weekly_period_report_rows(
    summaries: list[WeeklySalesSummary],
    *,
    include_month_summary: bool,
    include_quarter_summary: bool,
    include_year_summary: bool,
) -> list[dict[str, object]]:
    entries = [entry for summary in summaries if (entry := _weekly_sales_entry(summary))]
    if not entries:
        return []

    entries = [entry for entry in entries if _weekly_summary_period_end(cast(WeeklySalesSummary, entry["summary"])) != date.min]
    if not entries:
        return []

    entries.sort(key=lambda entry: _weekly_summary_period_end(cast(WeeklySalesSummary, entry["summary"])))
    latest_year = max((_weekly_summary_period_end(cast(WeeklySalesSummary, entry["summary"])).year for entry in entries), default=_current_date().year)
    year_entries = [entry for entry in entries if _weekly_summary_period_end(cast(WeeklySalesSummary, entry["summary"])).year == latest_year]
    rows: list[dict[str, object]] = []
    week_index = 0
    month_entries: list[dict[str, object]] = []
    quarter_entries: list[dict[str, object]] = []
    current_month: int | None = None
    current_quarter: int | None = None
    current_year: int | None = None

    def flush_month() -> None:
        nonlocal month_entries
        if not include_month_summary or not month_entries:
            return
        month_end = _weekly_summary_period_end(cast(WeeklySalesSummary, month_entries[-1]["summary"]))
        rows.append(_weekly_year_summary_row(f"{month_end.strftime('%b %Y')}", list(month_entries), "report-summary-row report-summary-month"))
        month_entries = []

    def flush_quarter() -> None:
        nonlocal quarter_entries
        if not include_quarter_summary or not quarter_entries:
            return
        quarter_end = _weekly_summary_period_end(cast(WeeklySalesSummary, quarter_entries[-1]["summary"]))
        rows.append(_weekly_year_summary_row(f"Q{_calendar_quarter(quarter_end)} {current_year or latest_year}", list(quarter_entries), "report-summary-row report-summary-quarter"))
        quarter_entries = []

    def flush_year() -> None:
        if include_year_summary:
            rows.append(_weekly_year_summary_row(f"{current_year or latest_year} Total", year_entries, "report-summary-row report-summary-year"))

    for index, entry in enumerate(year_entries):
        summary = cast(WeeklySalesSummary, entry["summary"])
        period_end = _weekly_summary_period_end(summary)
        month = period_end.month
        quarter = _calendar_quarter(period_end)
        year = period_end.year
        if current_month is None:
            current_month = month
        if current_quarter is None:
            current_quarter = quarter
        if current_year is None:
            current_year = year
        if month != current_month:
            flush_month()
            current_month = month
        if quarter != current_quarter:
            flush_quarter()
            current_quarter = quarter
        if year != current_year:
            flush_month()
            flush_quarter()
            current_year = year
        raw_json = cast(dict[str, object], entry["raw_json"])
        headers, values = _weekly_metrics_for_display(summary, raw_json)
        filtered_values = [value for label, value in zip(headers, values) if label not in _REPORT_VIEW_HIDDEN_METRICS]
        rows.append(
            {
                "summary": summary,
                "values": filtered_values,
                "row_class": f"report-week-row {'report-week-row-even' if week_index % 2 == 0 else 'report-week-row-odd'}",
            }
        )
        week_index += 1
        month_entries.append(entry)
        quarter_entries.append(entry)

        next_entry = year_entries[index + 1] if index + 1 < len(year_entries) else None
        next_period_end = _weekly_summary_period_end(cast(WeeklySalesSummary, next_entry["summary"])) if next_entry else date.min
        if next_entry is None or next_period_end.month != month:
            flush_month()
        if next_entry is None or _calendar_quarter(next_period_end) != quarter:
            flush_quarter()

    flush_year()
    return rows


def _weekly_sales_entry(summary: WeeklySalesSummary) -> dict[str, object] | None:
    upload = cast(ReportUpload, summary.report_upload)
    summary = _refresh_weekly_summary_if_needed(upload, summary)
    if summary is None:
        return None
    raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
    fiscal = raw_json.get("fiscal") if isinstance(raw_json.get("fiscal"), dict) else {}
    summary_kpis = raw_json.get("summary_kpis") if isinstance(raw_json.get("summary_kpis"), dict) else {}
    return {
        "summary": summary,
        "raw_json": raw_json,
        "fiscal": fiscal,
        "summary_kpis": summary_kpis,
    }


def _weekly_summary_period_end(summary: WeeklySalesSummary) -> date:
    period_end = summary.fiscal_period_end
    if isinstance(period_end, date):
        return period_end
    return date.min


def _weekly_year_summary_row(period_label: str, entries: list[dict[str, object]], row_class: str) -> dict[str, object]:
    metric_values = _weekly_year_metric_values(entries)
    headers = _weekly_report_headers()
    return {
        "summary": cast(WeeklySalesSummary, entries[0]["summary"]),
        "values": [period_label, "", *[_format_metric_value(label=label, value=metric_values.get(label, "")) for label in headers[2:]]],
        "row_class": row_class,
    }


def _weekly_year_metric_values(entries: list[dict[str, object]]) -> dict[str, object]:
    totals: dict[str, float] = {"Sales": 0.0, "LY Sales": 0.0, "Target": 0.0, "Ent Sales": 0.0, "Traffic": 0.0, "LY Traffic": 0.0, "Sales Tr": 0.0}
    uplift: dict[str, list[float]] = {"UPT": [], "STAR": []}
    for entry in entries:
        summary_kpis = entry.get("summary_kpis") if isinstance(entry, dict) else {}
        if not isinstance(summary_kpis, dict):
            continue
        totals["Sales"] += _weekly_sales_numeric(summary_kpis, ("total_sales",)) or 0.0
        totals["LY Sales"] += _weekly_sales_numeric(summary_kpis, ("ly_total_sales",)) or 0.0
        totals["Target"] += _weekly_sales_numeric(summary_kpis, ("target_total_sales", "t_total_sales", "ttotal_sales")) or 0.0
        totals["Ent Sales"] += _weekly_sales_numeric(summary_kpis, ("enterprise_sales",)) or 0.0
        totals["Traffic"] += _weekly_sales_numeric(summary_kpis, ("traffic",)) or 0.0
        totals["LY Traffic"] += _weekly_sales_numeric(summary_kpis, ("ly_traffic",)) or 0.0
        totals["Sales Tr"] += _weekly_sales_numeric(summary_kpis, ("sales_trans",)) or 0.0
        for label in uplift:
            value = _weekly_sales_numeric(summary_kpis, _weekly_metric_keys(label))
            if value is not None:
                uplift[label].append(value)

    return {
        "Week": "",
        "Date": "",
        "Sales": totals["Sales"],
        "LY Sales": totals["LY Sales"],
        "Target": totals["Target"],
        "% Tgt": round((totals["Sales"] / totals["Target"] * 100), 2) if totals["Target"] else "",
        "Ent Sales": totals["Ent Sales"],
        "Traffic Lev": round((totals["Sales"] / totals["Traffic"]), 2) if totals["Traffic"] else "",
        "Conv": round((totals["Sales Tr"] / totals["Traffic"] * 100), 2) if totals["Traffic"] else "",
        "LY Conv": round((totals["Sales Tr"] / totals["LY Traffic"] * 100), 2) if totals["LY Traffic"] else "",
        "Traffic": totals["Traffic"],
        "% Δ LY Traf": round(((totals["Traffic"] - totals["LY Traffic"]) / totals["LY Traffic"] * 100), 2) if totals["LY Traffic"] else "",
        "DPT": round((totals["Sales"] / totals["Sales Tr"]), 2) if totals["Sales Tr"] else "",
        "LY DPT": round((totals["LY Sales"] / totals["Sales Tr"]), 2) if totals["Sales Tr"] else "",
        "UPT": _weekly_sales_average(uplift["UPT"]),
        "STAR": _weekly_sales_average(uplift["STAR"]),
    }


def _weekly_sales_numeric(summary_kpis: dict[str, object], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        number = _coerce_number(summary_kpis.get(key))
        if number is not None:
            return number
    return None


def _weekly_sales_average(values: list[float]) -> float | str:
    if not values:
        return ""
    return round(sum(values) / len(values), 2)


def _weekly_metric_keys(label: str) -> tuple[str, ...]:
    for metric_label, keys in _WEEKLY_METRICS:
        if metric_label == label:
            return keys
    return ()


def _calendar_quarter(value: date) -> int:
    return ((value.month - 1) // 3) + 1


def _weekly_metric_value(
    summary: WeeklySalesSummary | None,
    fiscal: dict[str, object],
    summary_kpis: dict[str, object],
    display_label: str,
    keys: tuple[str, ...],
) -> object:
    for key in keys:
        if key == "week_ending_date":
            if summary and summary.fiscal_period_end:
                return _format_display_date(summary.fiscal_period_end)
            value = fiscal.get("week_ending_date")
            if value:
                return _format_display_date(value)
            continue
        if key == "period_end":
            if summary and summary.fiscal_period_end:
                return _format_display_date(summary.fiscal_period_end)
            value = fiscal.get("period_end")
            if value:
                return _format_display_date(value)
            continue
        if key == "fiscal_week":
            if summary and summary.fiscal_week:
                return summary.fiscal_week
            value = fiscal.get("fiscal_week_number") or fiscal.get("fiscal_week")
            if value:
                return value
            continue
        if key in summary_kpis:
            return _format_metric_value(label=display_label, value=summary_kpis[key])
    return ""


def _refresh_weekly_summary_if_needed(upload: ReportUpload, summary: WeeklySalesSummary | None) -> WeeklySalesSummary | None:
    if summary is None:
        return None
    raw_json = summary.raw_json if isinstance(summary.raw_json, dict) else {}
    parse_version = int(raw_json.get("parse_version", 0) or 0)
    if parse_version >= int(getattr(WeeklySalesReport, "parse_version", 2)):
        return summary

    raw_text = str(raw_json.get("raw_text") or "")
    if not raw_text:
        return summary

    report = get("weekly_sales").parse(raw_text)
    parsed_payload = report.payload if isinstance(report.payload, dict) else {}
    parsed_fiscal_obj = parsed_payload.get("fiscal")
    parsed_fiscal = parsed_fiscal_obj if isinstance(parsed_fiscal_obj, dict) else {}
    expected_year = parsed_fiscal.get("fiscal_year", summary.fiscal_year)
    expected_week = parsed_fiscal.get("fiscal_week_number", summary.fiscal_week)
    if parse_version >= int(getattr(WeeklySalesReport, "parse_version", 2)):
        if summary.fiscal_year == expected_year and summary.fiscal_week == expected_week:
            return summary
    defaults: dict[str, object] = {
        "fiscal_year": int(expected_year),
        "fiscal_week": int(expected_week),
        "fiscal_period_start": _parse_date(report.period_start),
        "fiscal_period_end": _parse_date(report.period_end),
        "raw_json": parsed_payload,
    }
    return getattr(WeeklySalesSummary, "objects").update_or_create(report_upload=upload, defaults=defaults)[0]
def _format_metric_value(*, label: str, value: object) -> object:
    if label in _CURRENCY_METRICS:
        return _format_currency(value)
    if label in _PERCENT_METRICS:
        return _format_percent(value)
    return _stringify_value(value)


def _weekly_metric_numeric_value(
    summary: WeeklySalesSummary | None,
    raw_json: dict[str, object],
    summary_kpis: dict[str, object],
    label: str,
    keys: tuple[str, ...],
) -> Decimal | None:
    for key in keys:
        value = summary_kpis.get(key)
        if value is None:
            continue
        number = _coerce_decimal(value)
        if number is not None:
            return number
    return None


def _format_metric_trend(label: str, first: Decimal | None, last: Decimal | None) -> str:
    if first is None or last is None:
        return ""
    delta = last - first
    if delta == 0:
        return "0"
    sign = "+" if delta > 0 else "-"
    magnitude = abs(delta)
    if label in _CURRENCY_METRICS:
        rounded = magnitude.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if rounded == rounded.to_integral_value():
            return f"{sign}${int(rounded):,}"
        return f"{sign}${rounded:,.2f}".rstrip("0").rstrip(".")
    if label in _PERCENT_METRICS:
        rounded = magnitude.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if rounded == rounded.to_integral_value():
            return f"{sign}{int(rounded):,}%"
        return f"{sign}{rounded:,.2f}".rstrip("0").rstrip(".") + "%"
    rounded = magnitude.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded == rounded.to_integral_value():
        return f"{sign}{int(rounded):,}"
    return f"{sign}{rounded:,.2f}".rstrip("0").rstrip(".")


def _format_currency(value: object) -> str:
    number = _coerce_decimal(value)
    if number is None:
        return str(value)
    if number == number.to_integral_value():
        return f"${int(number):,}"
    return f"${number.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}".rstrip("0").rstrip(".")


def _format_percent(value: object) -> str:
    number = _coerce_decimal(value)
    if number is None:
        return str(value)
    if abs(number) <= 1:
        number *= 100
    if number == number.to_integral_value():
        return f"{int(number):,}%"
    return f"{number.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}".rstrip("0").rstrip(".") + "%"


def _coerce_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1]
    if text.startswith("$"):
        text = text[1:]
    try:
        return float(text)
    except ValueError:
        return None


def _stringify_value(value: object) -> object:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _format_display_date(value: object) -> str:
    if isinstance(value, date):
        return value.strftime("%m/%d/%y")
    text = str(value).strip()
    try:
        return date.fromisoformat(text).strftime("%m/%d/%y")
    except ValueError:
        return text


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


def _extract_pdf_text_from_upload(upload: ReportUpload) -> str:
    source_file = cast(Any, upload.source_file)
    if source_file and getattr(source_file, "name", ""):
        try:
            if hasattr(source_file, "open"):
                source_file.open("rb")
                try:
                    data = source_file.read()
                finally:
                    source_file.close()
                if data:
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
                        decoded = data.decode("latin1", errors="ignore").replace("\x00", "")
                        if decoded.strip():
                            return decoded
        except Exception:
            pass
    source_path = getattr(source_file, "path", "")
    if source_path:
        return _extract_pdf_text(source_path)
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


def _current_date() -> date:
    return date.today()
