from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.models import ReviewTemplate
from apps.reports.models import PartiesWeek
from apps.reports.parties_views import parties_dashboard_summary, payroll_fiscal_year


@pytest.mark.django_db
def test_parties_page_has_month_tabs_grouped_headers_and_four_five_four_weeks(client: Client) -> None:
    response = client.get(reverse("parties") + "?month=2")

    assert response.status_code == 200
    html = response.content.decode()
    assert html.count("data-parties-month-tab=") == 12
    assert html.count('name="held_current_') == 5
    assert ">Week<" in html
    assert ">Week Ending<" in html
    assert ">Parties Held<" in html
    assert ">Parties Booked<" in html
    assert ">Current Year<" in html
    assert ">Previous Year<" in html
    assert html.count(">+/-<") == 2
    assert ">Total<" in html
    assert ">Quarter Totals<" in html
    assert ">Year Totals<" in html
    assert "data-parties-calculation=\"held-variance\"" in html
    assert "data-parties-calculation=\"booked-variance\"" in html
    assert "addEventListener('input'" in html
    assert "Number(field.value.replace(/,/g, ''))" in html
    assert "initialSummary" in html
    assert "['quarter', 'year']" in html
    assert "justify-content: flex-start" in client.get(reverse("parties")).content.decode() or "parties-save-button" in html


@pytest.mark.django_db
def test_parties_page_saves_calculates_and_totals_weekly_values(client: Client) -> None:
    response = client.post(
        reverse("parties"),
        {
            "month": "1",
            "held_current_1": "10",
            "held_previous_1": "7",
            "booked_current_1": "8",
            "booked_previous_1": "5",
            "held_current_2": "4",
            "held_previous_2": "6",
            "booked_current_2": "3",
            "booked_previous_2": "4",
        },
    )

    assert response.status_code == 302
    week = PartiesWeek.objects.get(fiscal_week=1)
    assert week.held_variance == Decimal("3.00")
    assert week.booked_variance == Decimal("3.00")
    week_two = PartiesWeek.objects.get(fiscal_week=2)
    assert week_two.held_variance == Decimal("-2.00")

    html = client.get(reverse("parties") + "?month=1").content.decode()
    assert ">14.00<" in html
    assert ">13.00<" in html
    assert ">1.00<" in html
    assert "parties-save-button" in html
    assert "parties-entry-grid" in html


@pytest.mark.django_db
def test_parties_quarter_and_year_totals_stop_at_selected_month(client: Client) -> None:
    client.post(reverse("parties"), {"month": "1", "held_current_1": "10", "held_previous_1": "7", "booked_current_1": "8", "booked_previous_1": "5"})
    client.post(reverse("parties"), {"month": "2", "held_current_5": "20", "held_previous_5": "12", "booked_current_5": "15", "booked_previous_5": "9"})

    month_one = client.get(reverse("parties") + "?month=1").context
    month_two = client.get(reverse("parties") + "?month=2").context

    assert month_one["parties_quarter_total"]["held_current"] == "10.00"
    assert month_one["parties_year_total"]["held_current"] == "10.00"
    assert month_two["parties_total"]["held_current"] == "20.00"
    assert month_two["parties_quarter_total"]["held_current"] == "30.00"
    assert month_two["parties_quarter_total"]["held_previous"] == "19.00"
    assert month_two["parties_year_total"]["booked_current"] == "23.00"
    assert month_two["parties_year_total"]["booked_previous"] == "14.00"


@pytest.mark.django_db
def test_dashboard_review_parties_module_uses_direct_entry_summary(client: Client) -> None:
    client.post(reverse("parties"), {"month": "1", "held_current_1": "10", "held_previous_1": "7", "booked_current_1": "8", "booked_previous_1": "5"})
    template = ReviewTemplate.objects.create(name="Parties review", layout=[{"type": "parties", "title": "Parties"}])

    response = client.get(reverse("dashboard-review") + f"?template={template.pk}")

    assert response.status_code == 200
    html = response.content.decode()
    assert 'data-review-module="parties"' in html
    assert "Held Current Year" in html
    assert "Booked Current Year" in html
    assert "Current Year" in html
    assert "review-parties-latest" in html
    assert "review-parties-year" in html
    assert "Fiscal Year YTD" not in html
    assert "No direct Parties data is available" not in html


@pytest.mark.django_db
def test_dashboard_parties_summary_shows_last_week_month_quarter_and_year_rows() -> None:
    fiscal_year = payroll_fiscal_year()
    for week in range(1, 9):
        PartiesWeek.objects.create(
            fiscal_year=fiscal_year,
            fiscal_month=1 if week <= 4 else 2,
            fiscal_week=week,
            held_current=Decimal(week),
            held_previous=Decimal("1"),
            booked_current=Decimal(week + 1),
            booked_previous=Decimal("2"),
        )

    summary = parties_dashboard_summary()

    assert summary is not None
    assert summary["headers"][0] == "Period"
    rows = summary["rows"]
    assert len(rows) == 4
    assert [row["values"][0] for row in rows] == ["Last Fiscal Week", "Current Month", "Current Quarter", "Current Year"]
    assert rows[0]["values"][1] == "8.00"
    assert rows[0]["row_class"] == "review-parties-latest"
    assert rows[-1]["row_class"] == "review-parties-year"


@pytest.mark.django_db
def test_parties_page_accepts_comma_formatted_existing_values(client: Client) -> None:
    client.post(reverse("parties"), {"month": "1", "held_current_1": "1000"})

    response = client.post(reverse("parties"), {"month": "1", "held_current_1": "1,000.00"})

    assert response.status_code == 302
    assert PartiesWeek.objects.get(fiscal_week=1).held_current == Decimal("1000.00")


@pytest.mark.django_db
def test_parties_page_preserves_valid_inputs_when_another_field_is_invalid(client: Client) -> None:
    response = client.post(
        reverse("parties"),
        {"month": "1", "held_current_1": "123.45", "held_previous_1": "not-a-number"},
    )

    assert response.status_code == 400
    html = response.content.decode()
    assert 'name="held_current_1" value="123.45"' in html
    assert 'name="held_previous_1" value="not-a-number"' in html


@pytest.mark.django_db
def test_parties_page_server_totals_leave_partial_variance_blank(client: Client) -> None:
    client.post(reverse("parties"), {"month": "1", "held_current_1": "10", "held_previous_2": "7"})

    response = client.get(reverse("parties") + "?month=1")

    assert response.context["parties_total"]["held_current"] == "10.00"
    assert response.context["parties_total"]["held_previous"] == "7.00"
    assert response.context["parties_total"]["held_variance"] == ""


@pytest.mark.django_db
def test_parties_page_clears_an_existing_week_when_all_inputs_are_blank(client: Client) -> None:
    client.post(reverse("parties"), {"month": "1", "held_current_1": "2"})
    assert PartiesWeek.objects.filter(fiscal_week=1).exists()

    response = client.post(reverse("parties"), {"month": "1"})

    assert response.status_code == 302
    assert not PartiesWeek.objects.filter(fiscal_week=1).exists()
