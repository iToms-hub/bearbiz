from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from apps.reports.gantt_views import _floor_leader_rows
from apps.reports.gantts import parse_gantt_report
from apps.reports.models import GanttReport, MissedOpportunityReport, SegmentReport

ATTACHMENTS = Path("/home/tome/.hermes/profiles/claire/attachments")


@pytest.mark.parametrize(
    ("filename", "expected_day", "expected_date"),
    [
        ("saturday 9-19.pdf", "Saturday", "2026-09-19"),
        ("Sunday 9-13.pdf", "Sunday", "2026-09-13"),
    ],
)
def test_gantt_parser_extracts_day_employees_and_floor_leaders(filename, expected_day, expected_date):
    parsed = parse_gantt_report((ATTACHMENTS / filename).read_bytes(), filename)

    assert parsed["day"] == expected_day
    assert parsed["day_date"] == expected_date
    assert parsed["week_end"] == "2026-09-19"
    assert parsed["time_slots"]
    assert all("name" in employee and "assignments" in employee for employee in parsed["employees"])
    assert any(
        assignment["label"] == "Floor Leader"
        for employee in parsed["employees"]
        for assignment in employee["assignments"]
    )


def test_gantt_parser_keeps_floor_leader_owner_and_interval():
    parsed = parse_gantt_report((ATTACHMENTS / "Sunday 9-13.pdf").read_bytes(), "Sunday 9-13.pdf")

    floor_leaders = [
        (employee["name"], assignment)
        for employee in parsed["employees"]
        for assignment in employee["assignments"]
        if assignment["label"] == "Floor Leader"
    ]

    assert {name for name, _assignment in floor_leaders} >= {"Vanessa Esparza", "Mindy Montejano"}
    assert all(assignment["start"] < assignment["end"] for _name, assignment in floor_leaders)


@pytest.mark.django_db()
def test_missed_ops_navigation_starts_with_mo_reports(client: Client):
    response = client.get(reverse("missed-ops-mo-reports"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "MO Reports" in html
    assert "Schedules" not in html


@pytest.mark.django_db()
def test_missed_ops_root_opens_mo_reports(client: Client):
    response = client.get(reverse("missed-ops"))
    assert response.status_code == 302
    assert response["Location"].endswith(reverse("missed-ops-mo-reports"))


@pytest.mark.django_db()
def test_review_rows_join_ranked_segments_to_gantt_floor_leader():
    mo = MissedOpportunityReport.objects.create(
        fiscal_year=2027, fiscal_week=33, week_end="2026-09-19", source_name="week 33.pdf",
        days=[{"day": "Sat", "missed_store_sales": "$1,078", "has_missed_opportunity": True}],
    )
    SegmentReport.objects.create(
        fiscal_year=2027, fiscal_week=33, day_of_week="Saturday", day_date="2026-09-19",
        week_end="2026-09-19", source_name="saturday.pdf", headers=[], rows=[
            {"values": ["2:00 PM", "$100", "-10%", "-21.5%", "12.0%", "$29.32", "18.8"]},
            {"values": ["4:00 PM", "$200", "-5%", "-12.0%", "14.0%", "$31.00", "20.0"]},
        ],
    )
    GanttReport.objects.create(
        fiscal_year=2027, fiscal_week=33, day_of_week="Saturday", day_date="2026-09-19",
        week_end="2026-09-19", source_name="saturday gantt.pdf", time_slots=[],
        employees=[{"name": "Haley Ebitner", "manager": True, "assignments": [{"label": "Floor Leader", "start": "2:00 PM", "end": "3:00 PM", "start_minutes": 840, "end_minutes": 900}]}],
    )

    from apps.reports.missed_ops_review import build_review_rows

    rows = build_review_rows(mo)

    assert rows == [
        {
            "date": "09/19/26", "day": "Saturday", "segment": "2:00 PM", "floor_leader": "Haley Ebitner",
            "leverage": "-21.5%", "dpt": "$29.32", "conversion": "12.0%", "star": "18.8",
            "reasons": ["Leverage below threshold", "DPT below threshold", "Conversion below threshold", "STAR above threshold"],
            "flags": {"leverage": True, "dpt": True, "conversion": True, "star": True},
        },
        {
            "date": "09/19/26", "day": "Saturday", "segment": "4:00 PM", "floor_leader": "Not identified",
            "leverage": "-12.0%", "dpt": "$31.00", "conversion": "14.0%", "star": "20.0",
            "reasons": ["Leverage below threshold", "DPT below threshold", "Conversion below threshold", "STAR above threshold"],
            "flags": {"leverage": True, "dpt": True, "conversion": True, "star": True},
        },
    ]


@pytest.mark.django_db()
def test_review_page_and_pdf_routes_render(client: Client):
    response = client.get(reverse("missed-ops-review"))
    html = response.content.decode()
    assert "Missed Ops Review" in html
    assert response.context["missed_ops_review_headers"] == ["Date", "Day", "Segment", "Floor Leader", "Leverage", "DPT", "Conversion", "STAR"]
    assert "text-align:center" in html

    pdf = client.get(reverse("missed-ops-review-pdf"))
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


@pytest.mark.django_db()
def test_dashboard_review_module_includes_missed_ops_highlight_contract(client: Client):
    response = client.get(reverse("dashboard-review"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "missed-ops-review-module-grid" in html
    assert "review-underperformance" in html


def test_gantt_rows_sort_by_segment_time_without_role_column():
    report = GanttReport(
        employees=[
            {"name": "Later Manager", "assignments": [{"label": "Floor Leader", "start": "4:00 PM", "end": "5:00 PM", "start_minutes": 960, "end_minutes": 1020}]},
            {"name": "Earlier Associate", "assignments": [{"label": "Floor Leader", "start": "2:00 PM", "end": "3:00 PM", "start_minutes": 840, "end_minutes": 900}]},
        ]
    )
    rows = _floor_leader_rows(report)
    assert [row["segment_time"] for row in rows] == ["2:00 PM", "4:00 PM"]
    assert "role" not in rows[0]


@pytest.mark.django_db()
def test_review_criteria_flags_underperforming_metrics(client: Client):
    response = client.get(reverse("missed-ops-review"), {"leverage_below": "-5", "dpt_below": "30", "conversion_below": "10", "star_above": "25"})
    assert response.status_code == 200
    assert response.context["missed_ops_review_criteria"]["dpt_below"] == Decimal("30")
