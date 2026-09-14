from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
from datetime import date

from apps.core.models import FiscalYearSettings
from apps.reports.models import PartiesSummary, ReportUpload
from apps.reports.modules.parties import PartiesReport
from apps.core.ai import build_bearbiz_chat_context
from apps.reports.parties_views import HEADERS, _rows


FIXTURE = Path("/home/tome/.hermes/kanban/boards/bearbiz/attachments/t_1a262103/week 31 parties.pdf")


def test_parties_parser_preserves_groups_status_and_na() -> None:
    parsed = PartiesReport().parse(
        """Party Summary - Store Report '26 FW31
        TTL Parties Held | Comp Parties Held | TTL Parties Booked
        ACT wk1 | 1 | 2 | +1 | 3 | 4 | -1 | 5 | 6 | +2
        FCST wk2 | #N/A | 1 | #N/A | #N/A | 2 | #N/A | #N/A | 3 | #N/A
        """
    )
    assert parsed.report_type == "parties"
    assert parsed.payload["fiscal"] == {"fiscal_year": 2026, "fiscal_week_number": 31}
    assert parsed.payload["rows"][0]["status"] == "ACT"
    assert {key: parsed.payload["rows"][0]["metrics"]["ttl_held"][key] for key in ("current", "previous", "variance")} == {"current": 1, "previous": 2, "variance": 1}
    assert parsed.payload["rows"][1]["status"] == "FCST"
    assert parsed.payload["rows"][1]["metrics"]["ttl_held"]["current"] is None
    assert parsed.payload["rows"][1]["metrics"]["ttl_held"]["raw_current"] == "#N/A"


@pytest.mark.django_db
def test_parties_parser_uses_source_month_markers_and_configured_fiscal_start() -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))
    parsed = PartiesReport().parse(
        """Party Summary - Store Report '26 FW31
        ACT wk1 1 1 +0 1 1 +0 1 1 +0
        Feb
        ACT wk2 2 2 +0 2 2 +0 2 2 +0
        Mar
        ACT wk3 3 3 +0 3 3 +0 3 3 +0
        """
    )

    rows = parsed.payload["rows"]
    assert [row["source_month"] for row in rows] == ["Jan", "Feb", "Mar"]
    assert [row["fiscal_month"] for row in rows] == [1, 1, 1]


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture unavailable")
def test_week_31_fixture_parses_source_rows() -> None:
    import pdfplumber

    with pdfplumber.open(FIXTURE) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    parsed = PartiesReport().parse(text)
    assert parsed.payload["fiscal"]["fiscal_year"] == 2026
    assert len(parsed.payload["rows"]) == 52
    assert any(row["status"] == "FCST" for row in parsed.payload["rows"])
    assert parsed.payload["rows"][-1]["metrics"]["ttl_held"]["current"] is None


@pytest.mark.django_db
def test_parties_upload_history_and_rollup_view(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    client = Client()
    with override_settings(MEDIA_ROOT=media_root), FIXTURE.open("rb") as source:
        response = client.post(
            reverse("parties-uploads"),
            {"source_file": SimpleUploadedFile("week 31 parties.pdf", source.read(), content_type="application/pdf")},
        )
    assert response.status_code == 302
    upload = ReportUpload.objects.get(report_type="parties")
    summary = PartiesSummary.objects.get(report_upload=upload)
    assert upload.parse_status == "parsed"
    assert len(summary.rows) == 52
    assert summary.raw_json["rows"][31]["status"] == "FCST"
    with override_settings(MEDIA_ROOT=media_root):
        html = client.get(reverse("parties")).content.decode()
    assert "Parties" in html
    assert "TTL Parties Held" in html
    assert "Comp Parties Held" not in html
    assert "Status" not in html
    assert "TTL Parties Booked" in html
    assert "Month Totals" in html
    assert "Quarter Totals" in html
    assert "Fiscal Year Total" in html
    assert 'name="fiscal_month"' not in html


def test_parties_headers_hide_status_and_comp_columns() -> None:
    assert HEADERS == [
        "Week",
        "Week Date",
        "TTL Parties Held TY",
        "TTL Parties Held LY",
        "Held +/-",
        "TTL Parties Booked TY",
        "TTL Parties Booked LY",
        "Booked +/-",
    ]


@pytest.mark.django_db
def test_parties_display_starts_at_week_one_and_places_week_date_after_week() -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))
    upload = ReportUpload.objects.create(report_type="parties", source_name="parties.pdf")
    summary = PartiesSummary.objects.create(
        report_upload=upload,
        fiscal_year=2027,
        fiscal_week=2,
        rows=[
            {
                "week": "wk7",
                "week_number": 1,
                "week_date": "2026-02-01",
                "status": "ACT",
                "fiscal_month": 1,
                "metrics": {
                    "ttl_held": {"current": 1, "previous": 2, "variance": -1},
                    "ttl_booked": {"current": 3, "previous": 4, "variance": -1},
                    "comp_held": {"current": 9, "previous": 8, "variance": 1},
                },
            }
        ],
        raw_json={},
    )
    display = _rows(summary)[0]
    assert display["values"][:2] == ["Week 1", "02/01/26"]
    assert len(display["values"]) == 8


@pytest.mark.django_db
def test_later_parties_upload_preserves_history_and_adds_new_weeks(monkeypatch, tmp_path: Path) -> None:
    from apps.reports import parties_views

    first_text = "Party Summary - Store Report '26 FW2\n" + "\n".join(
        f"ACT wk{week} 1 1 0 1 1 0 1 1 0" for week in range(1, 3)
    )
    later_text = "Party Summary - Store Report '26 FW3\n" + "\n".join(
        ["ACT wk1 1 1 0 1 1 0 1 1 0", "ACT wk2 1 1 0 1 1 0 1 1 0", "ACT wk3 3 3 0 3 3 0 3 3 0"]
    )
    texts = iter([first_text, later_text])
    monkeypatch.setattr(parties_views, "_extract", lambda upload: next(texts))
    with override_settings(MEDIA_ROOT=tmp_path / "media"):
        first_upload = ReportUpload.objects.create(
            report_type="parties", source_name="week-2.pdf",
            source_file=SimpleUploadedFile("week-2.pdf", b"first"),
        )
        first_summary = parties_views._parse(first_upload)
        original_rows = first_summary.rows
        second_upload = ReportUpload.objects.create(
            report_type="parties", source_name="week-3.pdf",
            source_file=SimpleUploadedFile("week-3.pdf", b"second"),
        )
        merged_summary = parties_views._parse(second_upload)

    first_summary.refresh_from_db()
    assert first_summary.rows == original_rows
    assert len(merged_summary.rows) == 3
    assert merged_summary.rows[0]["metrics"] == original_rows[0]["metrics"]
    assert merged_summary.rows[2]["week_number"] == 3
    assert second_upload.parse_status == "parsed"


@pytest.mark.django_db
def test_later_parties_upload_surfaces_historical_conflict_without_overwrite(monkeypatch, tmp_path: Path) -> None:
    from apps.reports import parties_views

    first_text = "Party Summary - Store Report '26 FW2\nACT wk1 1 1 0 1 1 0 1 1 0"
    conflicting_text = "Party Summary - Store Report '26 FW3\nACT wk1 9 9 0 9 9 0 9 9 0\nACT wk2 2 2 0 2 2 0 2 2 0"
    texts = iter([first_text, conflicting_text])
    monkeypatch.setattr(parties_views, "_extract", lambda upload: next(texts))
    with override_settings(MEDIA_ROOT=tmp_path / "media"):
        first_upload = ReportUpload.objects.create(
            report_type="parties", source_name="week-2.pdf",
            source_file=SimpleUploadedFile("week-2.pdf", b"first"),
        )
        first_summary = parties_views._parse(first_upload)
        original_rows = first_summary.rows
        second_upload = ReportUpload.objects.create(
            report_type="parties", source_name="week-3.pdf",
            source_file=SimpleUploadedFile("week-3.pdf", b"second"),
        )

        merged_summary = parties_views._parse(second_upload)

    first_summary.refresh_from_db()
    assert first_summary.rows == original_rows
    assert merged_summary.rows[0]["metrics"] == original_rows[0]["metrics"]
    assert merged_summary.rows[1]["week_number"] == 2
    assert second_upload.parse_status == "conflict"
    assert "historical" in second_upload.parse_error.lower()


@pytest.mark.django_db
def test_parties_empty_state_and_delete(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    client = Client()
    with override_settings(MEDIA_ROOT=media_root):
        assert client.get(reverse("parties")).status_code == 200
        upload = ReportUpload.objects.create(
            report_type="parties",
            source_file=SimpleUploadedFile("parties.pdf", b"pdf", content_type="application/pdf"),
            source_name="parties.pdf",
        )
        response = client.post(reverse("parties-delete", kwargs={"pk": upload.pk}))
    assert response.status_code == 302
    assert not ReportUpload.objects.filter(pk=upload.pk).exists()


@pytest.mark.django_db
def test_parties_rollups_follow_configured_454_quarter_boundaries() -> None:
    settings = FiscalYearSettings.objects.create(
        fiscal_year_start_date=date(2026, 2, 1), calendar_pattern="454"
    )
    upload = ReportUpload.objects.create(report_type="parties", source_name="parties.pdf")
    rows = [
        {
            "week": f"wk{week}",
            "week_number": week,
            "status": "ACT",
            "fiscal_month": 99,
            "metrics": {
                "ttl_held": {"current": 1, "previous": 1, "variance": 0},
                "ttl_booked": {"current": 1, "previous": 1, "variance": 0},
                "comp_held": {"current": 1, "previous": 1, "variance": 0},
            },
        }
        for week in range(1, 53)
    ]
    summary = PartiesSummary.objects.create(
        report_upload=upload, fiscal_year=2027, fiscal_week=31, rows=rows, raw_json={}
    )

    labels = [row["values"][0] for row in _rows(summary)]
    assert labels[:9] == ["Week 1", "Week 2", "Week 3", "Week 4",
                          "Month Totals (Fiscal Month 1)", "Week 5", "Week 6", "Week 7", "Week 8"]
    assert labels.index("Month Totals (Fiscal Month 3)") < labels.index("Quarter Totals (Q1)")
    assert labels.index("Quarter Totals (Q1)") < labels.index("Month Totals (Fiscal Month 4)")
    assert "Quarter Totals (Q2)" in labels
    assert settings.calendar_pattern == "454"


def test_parties_parser_assigns_exact_454_month_lengths_from_week_sequence() -> None:
    lines = ["Party Summary - Store Report '26 FW52"]
    lines.extend(f"ACT wk{week} 1 1 0 1 1 0 1 1 0" for week in range(1, 53))

    rows = PartiesReport().parse("\n".join(lines)).payload["rows"]
    assert [sum(row["fiscal_month"] == month for row in rows) for month in range(1, 13)] == [4, 5, 4] * 4


@pytest.mark.django_db
def test_parties_rollups_use_week_boundaries_even_when_source_months_are_wrong() -> None:
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1), calendar_pattern="454")
    upload = ReportUpload.objects.create(report_type="parties", source_name="parties.pdf")
    metric = {"current": 1, "previous": 1, "variance": 0}
    rows = [{"week": f"wk{week}", "week_number": week, "fiscal_month": 1,
             "metrics": {"ttl_held": metric, "ttl_booked": metric, "comp_held": metric}}
            for week in range(1, 53)]
    summary = PartiesSummary.objects.create(report_upload=upload, fiscal_year=2027, fiscal_week=52, rows=rows, raw_json={})

    labels = [row["values"][0] for row in _rows(summary)]
    assert labels[:8] == ["Week 1", "Week 2", "Week 3", "Week 4", "Month Totals (Fiscal Month 1)",
                          "Week 5", "Week 6", "Week 7"]
    assert labels.index("Quarter Totals (Q1)") < labels.index("Week 14")
    assert labels[-1] == "Fiscal Year Total"


def test_parties_summary_rows_have_distinct_readable_styles() -> None:
    template = Path("templates/base.html").read_text()
    assert "report-month-total" in template
    assert "report-quarter-total" in template
    assert "report-year-total" in template


@pytest.mark.django_db
def test_parties_are_available_to_agent_context() -> None:
    upload = ReportUpload.objects.create(report_type="parties", source_name="parties.pdf", parse_status="parsed")
    PartiesSummary.objects.create(
        report_upload=upload, fiscal_year=2026, fiscal_week=31,
        rows=[], raw_json={"rows": [{"status": "ACT", "metrics": {"ttl_held": {"current": 1}}}]},
    )
    context = build_bearbiz_chat_context()
    assert any(record["report_type"] == "parties" for record in context["recent_reports"])
