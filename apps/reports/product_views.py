from __future__ import annotations

import re
from decimal import Decimal

from django import forms
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.core.navigation import shell_context
from apps.reports.payroll_views import payroll_month_layout
from .models import ProductItem, ProductReport
from .modules.product import parse_product_pdf


class ProductUploadForm(forms.Form):
    source_file = forms.FileField(widget=forms.ClearableFileInput(attrs={"accept": "application/pdf"}))

    def clean_source_file(self):
        source = self.cleaned_data["source_file"]
        if not (getattr(source, "name", "") or "").lower().endswith(".pdf"):
            raise forms.ValidationError("Upload a PDF file.")
        return source


def _ranked_items(items: list[ProductItem], metric: str) -> list[dict[str, object]]:
    other = "net_sales" if metric == "units_sold" else "units_sold"
    ordered = sorted(items, key=lambda item: (-getattr(item, metric), -getattr(item, other), item.item_number))[:10]
    return [{
        "rank": index,
        "item_number": item.item_number,
        "item_description": item.item_description,
        "department": item.department,
        "value": getattr(item, metric),
    } for index, item in enumerate(ordered, start=1)]


def reusable_backpacks(items: list[ProductItem]) -> dict[str, object]:
    """Aggregate Friend items containing CARRIER, report typo CARIER, or standalone CR."""
    matches = [
        item for item in items
        if str(item.department).strip().casefold() == "friend"
        and re.search(r"\b(?:CARRIER|CARIER|CR)\b", str(item.item_description), flags=re.IGNORECASE)
    ]
    return {
        "label": "Reusable Backpacks",
        "item_number": "—",
        "item_description": "Reusable Backpacks",
        "department": "Friend",
        "units_sold": sum((item.units_sold for item in matches), 0),
        "net_sales": sum((item.net_sales for item in matches), Decimal("0")),
    }


def product_lookup(query: str) -> dict[str, object] | None:
    query = query.strip()
    if not query:
        return None
    reports = list(
        ProductReport.objects.filter(parse_status="parsed")
        .prefetch_related("items")
        .order_by("-fiscal_year", "-fiscal_week")
    )
    latest = reports[0] if reports else None
    if latest is None:
        return {"query": query, "title": f"Product lookup: {query}", "found": False, "periods": []}

    all_items = [item for report in reports for item in report.items.all()]
    item_match = any(str(item.item_number) == query for item in all_items)
    if item_match:
        matcher = lambda item: str(item.item_number) == query
        title = f"Item lookup: {query}"
    else:
        matcher = lambda item: str(item.department).strip().casefold() == query.casefold()
        title = f"Department lookup: {query}"

    anchor_week = latest.fiscal_week
    layout = payroll_month_layout()
    month_number = next((month for month, weeks in layout.items() if anchor_week in weeks), 12)
    month_weeks = list(layout[month_number])
    if anchor_week > month_weeks[-1]:
        month_weeks.extend(range(month_weeks[-1] + 1, anchor_week + 1))
    quarter_number = ((month_number - 1) // 3) + 1
    quarter_months = range((quarter_number - 1) * 3 + 1, quarter_number * 3 + 1)
    quarter_weeks = [week for month in quarter_months for week in layout[month]]
    if anchor_week > quarter_weeks[-1]:
        quarter_weeks.extend(range(quarter_weeks[-1] + 1, anchor_week + 1))

    periods = [
        ("Last Week", {anchor_week}),
        ("Current Month", set(month_weeks)),
        ("Current Quarter", set(quarter_weeks)),
        ("Current Year", set(range(1, anchor_week + 1))),
    ]
    period_rows: list[dict[str, object]] = []
    matching_item_numbers: set[str] = set()
    for label, weeks in periods:
        units = 0
        sales = Decimal("0")
        for report in reports:
            if report.fiscal_year != latest.fiscal_year or report.fiscal_week not in weeks:
                continue
            for item in report.items.all():
                if matcher(item):
                    units += item.units_sold
                    sales += item.net_sales
                    matching_item_numbers.add(str(item.item_number))
        period_rows.append({"label": label, "units_sold": units, "net_sales": sales})

    return {
        "query": query,
        "title": title,
        "found": bool(matching_item_numbers),
        "periods": period_rows,
        "fiscal_year": latest.fiscal_year,
        "fiscal_week": latest.fiscal_week,
    }


def product_dashboard_summary() -> dict[str, object] | None:
    report = ProductReport.objects.filter(parse_status="parsed").order_by("-fiscal_year", "-fiscal_week").first()
    if report is None:
        return None
    items = list(report.items.all())
    return {
        "latest_week": report.fiscal_week,
        "latest_year": report.fiscal_year,
        "units_rows": _ranked_items(items, "units_sold"),
        "sales_rows": _ranked_items(items, "net_sales"),
        "reusable_backpacks": reusable_backpacks(items),
    }


def index(request: HttpRequest) -> HttpResponse:
    errors: list[str] = []
    form = ProductUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        source = form.cleaned_data["source_file"]
        try:
            parsed = parse_product_pdf(source.read())
            with transaction.atomic():
                report, _ = ProductReport.objects.update_or_create(
                    fiscal_year=parsed["fiscal_year"], fiscal_week=parsed["fiscal_week"],
                    defaults={
                        "store_number": parsed["store_number"], "period_start": parsed["period_start"], "period_end": parsed["period_end"],
                        "source_name": source.name, "parse_status": "parsed", "parse_error": "", "row_count": len(parsed["rows"]), "parsed_at": timezone.now(),
                    },
                )
                report.items.all().delete()
                ProductItem.objects.bulk_create([ProductItem(report=report, **row) for row in parsed["rows"]])
        except Exception as exc:
            errors.append(str(exc))
        else:
            return redirect(f"/product/?week={parsed['fiscal_week']}")
    elif request.method == "POST":
        errors.extend(str(error) for error in form.errors.get("source_file", []))

    weeks = list(ProductReport.objects.filter(parse_status="parsed").order_by("-fiscal_year", "-fiscal_week"))
    selected_week = request.GET.get("week")
    selected = next((report for report in weeks if str(report.fiscal_week) == selected_week), weeks[0] if weeks else None)
    items = list(selected.items.all()) if selected else []
    context = shell_context(
        section="product", page_title="Product", subtitle="",
        product_form=form, product_errors=errors, product_weeks=weeks, selected_product_week=selected.fiscal_week if selected else "",
        product_report=selected, product_units_rows=_ranked_items(items, "units_sold"), product_sales_rows=_ranked_items(items, "net_sales"), product_reusable_backpacks=reusable_backpacks(items), product_lookup_data=product_lookup(str(request.GET.get("lookup", "") or "")),
    )
    return render(request, "product/index.html", context, status=400 if errors else 200)
