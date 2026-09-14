from datetime import date
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse

from apps.reports.models import PayrollSummary, ReportUpload
from apps.reports.modules.payroll import PayrollReport
from apps.reports.payroll_views import _percentage_class


def test_payroll_parser_preserves_tracker_columns_and_nulls() -> None:
    text = """Week | HOO | Sales Plan | Trend % from Bearnet | Actual Sales | SUN | MON | TUE | WED | THU | FRI | SAT | Total Hours Actual + Scheduled | Labor Calculator Target Hours | Current +/- | NOTES
    5 | 10 | $20,000 | 101% | $21,000 | 8 | 8 | - | 8 | 8 | 8 | 8 | 48 | 49 | -1 | 08/26/2026
    6 | 10 | $22,000 |  |  |  |  |  |  |  |  |  |  |  |  |
    Actual Sales | $98,207
    Sales Plan | $114,557
    """
    parsed = PayrollReport().parse(text)
    assert parsed.report_type == "payroll"
    assert parsed.period_start == "2026-08-26"
    assert parsed.payload["rows"][0]["TUE"] is None
    assert parsed.payload["rows"][1]["Week"] == 6
    assert parsed.payload["monthly_summary"]["Actual Sales"] == 98207


def test_week_31_fixture_parses_all_completed_weeks() -> None:
    fixture = Path("/home/tome/.hermes/profiles/claire/attachments/week 31 payroll.pdf")
    if not fixture.exists():
        pytest.skip("Claire's supplied Week 31 payroll fixture is unavailable")
    import pdfplumber

    with pdfplumber.open(fixture) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    parsed = PayrollReport().parse(text)
    assert [row["Week"] for row in parsed.payload["rows"]] == [1, 2, 3, 4, 5]
    assert parsed.payload["rows"][1]["Actual Sales"] == 24360
    assert parsed.payload["source_week"] == 1
    assert parsed.payload["monthly_summary"] == {
        "Sales Plan": 114557,
        "Actual Sales": 98207,
        "Labor Calculator Target Hours": 994.85,
    }


def test_actual_vs_earned_percentage_color_bands() -> None:
    assert _percentage_class(90) == "payroll-percent-green"
    assert _percentage_class(94.99) == "payroll-percent-green"
    assert _percentage_class(95) == "payroll-percent-blue"
    assert _percentage_class(101) == "payroll-percent-blue"
    assert _percentage_class(89.99) == "payroll-percent-red"
    assert _percentage_class(101.01) == "payroll-percent-red"


@pytest.mark.django_db
def test_payroll_upload_display_filter_and_read_only_layout(tmp_path: Path) -> None:
    fixture = Path("/home/tome/.hermes/profiles/claire/attachments/week 31 payroll.pdf")
    if not fixture.exists():
        pytest.skip("Claire's supplied Week 31 payroll fixture is unavailable")
    media_root = tmp_path / "media"
    client = Client()
    with override_settings(MEDIA_ROOT=media_root), fixture.open("rb") as source:
        response = client.post(
            reverse("payroll-uploads"),
            {"source_file": SimpleUploadedFile("week 31 payroll.pdf", source.read(), content_type="application/pdf")},
        )
    assert response.status_code == 302
    assert response.url == reverse("payroll-uploads")
    with override_settings(MEDIA_ROOT=media_root):
        uploads_html = client.get(reverse("payroll-uploads")).content.decode()
    assert "Payroll uploads" in uploads_html
    assert "week 31 payroll.pdf" in uploads_html
    assert "Download" in uploads_html
    upload = ReportUpload.objects.get(report_type="payroll")
    summary = PayrollSummary.objects.get(report_upload=upload)
    assert upload.parse_status == "parsed"
    assert len(summary.rows) == 5

    with override_settings(MEDIA_ROOT=media_root):
        html = client.get(reverse("payroll") + "?month=8&quarter=3&year=2026").content.decode()
    assert 'name="month"' in html and '<option value="8" selected>' in html
    assert '<option value="3" selected>' in html
    assert 'value="2026"' in html
    assert 'class="report-toolbar payroll-toolbar"' in html
    assert 'class="page-action primary"' in html
    assert 'class="page-action upload-action"' in html
    assert 'Month Totals' in html
    assert 'Actual vs Earned' in html
    assert '$24,360' in html
    assert '-14.3%' in html
    assert '105.9%' in html
    assert 'payroll-percent-red' in html
    assert 'Week Ending' in html
    assert '>Trend<' in html
    assert '>Total Hours<' in html
    assert '>Target Hours<' in html
    assert '>31<' in html and '>32<' in html and '>33<' in html and '>34<' in html and '>35<' in html
    assert '1053.93' in html
    assert '68.93' in html
    assert 'Save edit' not in html
    assert 'NOTES' not in html
    assert '>HOO<' not in html
    assert 'NOTES' in summary.rows[0]
    assert 'HOO' in summary.rows[0]


@pytest.mark.django_db
def test_reuploaded_week_replaces_visible_version(tmp_path: Path) -> None:
    fixture = Path("/home/tome/.hermes/profiles/claire/attachments/week 31 payroll.pdf")
    if not fixture.exists():
        pytest.skip("Claire's supplied Week 31 payroll fixture is unavailable")
    media_root = tmp_path / "media"
    client = Client()
    for name in ("week 31 payroll.pdf", "week 31 payroll replacement.pdf"):
        with override_settings(MEDIA_ROOT=media_root), fixture.open("rb") as source:
            response = client.post(
                reverse("payroll-uploads"),
                {"source_file": SimpleUploadedFile(name, source.read(), content_type="application/pdf")},
            )
        assert response.status_code == 302

    assert PayrollSummary.objects.count() == 2
    with override_settings(MEDIA_ROOT=media_root):
        response = client.get(reverse("payroll"))
    assert response.status_code == 200
    assert len(response.context["summaries"]) == 1
    assert response.context["summaries"][0].report_upload.source_name.endswith("replacement.pdf")


@pytest.mark.django_db
def test_payroll_month_quarter_and_year_grouping_from_fixture(tmp_path: Path) -> None:
    fixture = Path("/home/tome/.hermes/profiles/claire/attachments/week 31 payroll.pdf")
    if not fixture.exists():
        pytest.skip("Claire's supplied Week 31 payroll fixture is unavailable")
    media_root = tmp_path / "media"
    client = Client()
    with override_settings(MEDIA_ROOT=media_root), fixture.open("rb") as source:
        client.post(
            reverse("payroll-uploads"),
            {"source_file": SimpleUploadedFile("week 31 payroll.pdf", source.read(), content_type="application/pdf")},
        )
    for query, expected in (
        ("month=8&quarter=3&year=2026", True),
        ("month=7&quarter=3&year=2026", False),
        ("month=8&quarter=2&year=2026", False),
        ("month=8&quarter=3&year=2025", False),
    ):
        with override_settings(MEDIA_ROOT=media_root):
            response = client.get(reverse("payroll") + "?" + query)
        assert bool(response.context["summaries"]) is expected


@pytest.mark.django_db
def test_payroll_upload_can_be_deleted(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    client = Client()
    with override_settings(MEDIA_ROOT=media_root):
        upload = ReportUpload.objects.create(
            report_type="payroll",
            source_file=SimpleUploadedFile("payroll.pdf", b"pdf", content_type="application/pdf"),
            source_name="payroll.pdf",
        )
        response = client.post(reverse("payroll-delete", kwargs={"pk": upload.pk}))
    assert response.status_code == 302
    assert response.url == reverse("payroll-uploads")
    assert not ReportUpload.objects.filter(pk=upload.pk).exists()
