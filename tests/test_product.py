from datetime import date
from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.reports.models import ProductItem, ProductReport
from apps.reports.modules.product import parse_product_pdf
from apps.reports.product_views import _ranked_items, product_lookup, reusable_backpacks

FIXTURE = Path("/home/tome/.hermes/profiles/claire/attachments/Top 20 Items By Department Report (1) (2).pdf")


@pytest.mark.skipif(not FIXTURE.exists(), reason="supplied Product PDF fixture is not present in this checkout")
@pytest.mark.django_db
def test_product_parser_extracts_all_departments_and_preserves_item_numbers() -> None:
    parsed = parse_product_pdf(FIXTURE.read_bytes())

    assert parsed["store_number"] == "1214"
    assert parsed["period_start"].isoformat() == "2026-08-30"
    assert parsed["period_end"].isoformat() == "2026-09-05"
    assert len(parsed["rows"]) == 142
    assert parsed["rows"][0]["item_number"] == "035164"
    assert {row["department"] for row in parsed["rows"]} == {"Unstuffed", "Clothes", "Stuffers", "Footwear", "Stuffed", "Accessories", "Friend", "Human"}
    assert all(row["item_number"].isdigit() for row in parsed["rows"])

    backpack_totals = reusable_backpacks([SimpleNamespace(**row) for row in parsed["rows"]])
    assert backpack_totals["units_sold"] == 26
    assert backpack_totals["net_sales"] == Decimal("206.40")


def test_reusable_backpacks_matches_only_friend_carrier_or_standalone_cr() -> None:
    def item(department: str, description: str, units: int, sales: str) -> SimpleNamespace:
        return SimpleNamespace(department=department, item_description=description, units_sold=units, net_sales=Decimal(sales))

    result = reusable_backpacks([
        item("Friend", "Reusable CARRIER", 4, "10.00"),
        item("Friend", "Reusable CARIER", 5, "11.00"),
        item("FRIEND", "Travel CR - Blue", 3, "2.34"),
        item("Friend", "CRATE", 99, "99.00"),
        item("Friend", "CREDIT CARD", 99, "99.00"),
        item("Clothes", "CARRIER", 99, "99.00"),
    ])

    assert result["label"] == "Reusable Backpacks"
    assert result["units_sold"] == 12
    assert result["net_sales"] == Decimal("23.34")


@pytest.mark.django_db
def test_product_lookup_aggregates_item_and_department_by_fiscal_period() -> None:
    for week, units, sales in [(29, 2, "10.00"), (30, 3, "15.00"), (31, 5, "25.00")]:
        report = ProductReport.objects.create(
            fiscal_year=2027, fiscal_week=week, period_start=date(2026, 8, 1), period_end=date(2026, 8, 7),
            source_name=f"week-{week}.pdf", parse_status="parsed",
        )
        ProductItem.objects.create(
            report=report, department="Friend", department_rank=1, item_number="000123",
            item_description="Test item", units_sold=units, net_sales=Decimal(sales),
        )
        ProductItem.objects.create(
            report=report, department="Clothes", department_rank=1, item_number="000999",
            item_description="Other item", units_sold=10, net_sales=Decimal("100.00"),
        )

    item_result = product_lookup("000123")
    department_result = product_lookup("friend")

    assert item_result is not None and item_result["found"] is True
    assert [row["units_sold"] for row in item_result["periods"]] == [5, 5, 10, 10]
    assert [row["net_sales"] for row in item_result["periods"]] == [Decimal("25.00"), Decimal("25.00"), Decimal("50.00"), Decimal("50.00")]
    assert department_result is not None and department_result["title"] == "Department lookup: friend"
    assert department_result["found"] is True


@pytest.mark.skipif(not FIXTURE.exists(), reason="supplied Product PDF fixture is not present in this checkout")
@pytest.mark.django_db
def test_product_upload_persists_rows_without_a_source_file(client) -> None:
    upload = SimpleUploadedFile(FIXTURE.name, FIXTURE.read_bytes(), content_type="application/pdf")

    response = client.post(reverse("product"), {"source_file": upload})

    assert response.status_code == 302
    report = ProductReport.objects.get(fiscal_week=31)
    assert report.row_count == 142
    assert ProductItem.objects.filter(report=report).count() == 142
    assert not hasattr(report, "source_file")
    page = client.get(reverse("product"), {"week": 31})
    assert page.status_code == 200
    html = page.content.decode()
    assert "Reusable Backpacks" in html
    assert "product-special-row" in html
    lookup_page = client.get(reverse("product"), {"week": 31, "lookup": "035164"})
    assert lookup_page.status_code == 200
    lookup_html = lookup_page.content.decode()
    assert "product-lookup-results" in lookup_html
    assert "Item lookup: 035164" in lookup_html
    assert "Last Week" in lookup_html


@pytest.mark.django_db
def test_product_page_has_week_selector_and_side_by_side_ranking_tables(client) -> None:
    response = client.get(reverse("product"))

    assert response.status_code == 200
    html = response.content.decode()
    assert 'id="product-week"' in html
    assert "Top 10 by Units Sold" in html
    assert "Top 10 by Net Sales" in html
    assert "product-ranking-grid" in html
    assert "Month" not in html
    assert "Quarter" not in html
    assert "Year" not in html
    assert '<section class="panel stack product-lookup-results">' not in html
    assert "Top-selling products across all departments" not in html
    dashboard = client.get(reverse("dashboard"))
    assert dashboard.status_code == 200
    assert '<form method="get" class="product-lookup-form">' not in dashboard.content.decode()


def test_product_ranking_tie_breaks_are_deterministic() -> None:
    class Item:
        def __init__(self, number, units, sales):
            self.item_number = number
            self.item_description = number
            self.department = "Test"
            self.units_sold = units
            self.net_sales = sales

    ranked = _ranked_items([Item("0002", 10, 20), Item("0001", 10, 20), Item("0003", 10, 19)], "units_sold")

    assert [row["item_number"] for row in ranked] == ["0001", "0002", "0003"]
