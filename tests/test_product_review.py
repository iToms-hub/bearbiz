from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.models import ReviewTemplate
from apps.reports.models import ProductItem, ProductReport


@pytest.mark.django_db
def test_dashboard_review_product_top10_module_renders_both_rankings_side_by_side(client) -> None:
    report = ProductReport.objects.create(
        fiscal_year=2027,
        fiscal_week=31,
        period_start=date(2026, 8, 30),
        period_end=date(2026, 9, 5),
        store_number="1214",
        row_count=2,
        parse_status="parsed",
    )
    ProductItem.objects.create(
        report=report, department="Clothes", department_rank=1,
        item_number="000002", item_description="Blue Shirt", units_sold=12, net_sales=Decimal("24.00"),
    )
    ProductItem.objects.create(
        report=report, department="Stuffers", department_rank=1,
        item_number="000001", item_description="Red Hat", units_sold=10, net_sales=Decimal("30.00"),
    )
    ProductItem.objects.create(
        report=report, department="Friend", department_rank=2,
        item_number="000003", item_description="Reusable CARRIER", units_sold=5, net_sales=Decimal("12.50"),
    )
    template = ReviewTemplate.objects.create(
        name="Product review",
        layout=[{"type": "product-top-10", "title": "Product Top 10"}],
    )

    response = client.get(reverse("dashboard-review"), {"template": template.pk})

    assert response.status_code == 200
    html = response.content.decode()
    assert 'data-review-module="product-top-10"' in html
    assert "Top 10 by Units Sold" in html
    assert "Top 10 by Net Sales" in html
    assert "Blue Shirt" in html
    assert "Red Hat" in html
    assert "review-product-top10-grid" in html
    assert "Fiscal Year 2027, Week 31" in html
    assert html.count("Reusable Backpacks") >= 1
    assert "12.50" in html

    pdf_response = client.get(reverse("dashboard-review-pdf"), {"template": template.pk})
    assert pdf_response.status_code == 200
    assert pdf_response["Content-Type"] == "application/pdf"
    assert pdf_response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_product_top10_module_is_available_in_review_module_library(client) -> None:
    response = client.post(reverse("settings:templates"), {"action": "create", "name": "Product library test"})
    assert response.status_code == 200

    html = response.content.decode()
    assert "Product Top 10 · Latest Fiscal Week" in html
