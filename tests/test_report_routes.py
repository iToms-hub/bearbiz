from __future__ import annotations

from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
import pytest

from apps.reports.models import ReportUpload, WeeklySalesSummary


@pytest.fixture()
def client() -> Client:
    return Client()


@pytest.mark.django_db()
def test_weekly_sales_upload_history_and_download_routes(client: Client, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    pdf_bytes = _build_weekly_sales_pdf(
        [
            "Weekly Sales Summary",
            "Period Start    2026-08-31",
            "Period End    2026-09-06",
            "Net Sales    1200",
            "Orders    48",
        ]
    )
    upload = SimpleUploadedFile("week-1-sales.pdf", pdf_bytes, content_type="application/pdf")

    with override_settings(MEDIA_ROOT=media_root):
        response = client.post(reverse("reports:upload"), data={"source_file": upload})

        assert response.status_code == 302
        record = ReportUpload.objects.get()
        assert record.source_name == "week-1-sales.pdf"
        assert record.parse_status == "parsed"
        assert record.source_file.name.endswith("week-1-sales.pdf")

        summary = WeeklySalesSummary.objects.get(report_upload=record)
        assert summary.fiscal_year >= 2026
        assert summary.fiscal_week >= 1
        assert summary.raw_json["summary_kpis"]["net_sales"] == 1200
        assert summary.raw_json["summary_kpis"]["orders"] == 48

        history_response = client.get(reverse("reports:history"))
        assert history_response.status_code == 200
        history_html = history_response.content.decode()
        assert "week-1-sales.pdf" in history_html
        assert "Report 1" in history_html
        assert "Report Types" in history_html
        assert "Settings" in history_html

        report_six_response = client.get(reverse("reports:report-number", kwargs={"number": 6}))
        assert report_six_response.status_code == 200
        report_six_html = report_six_response.content.decode()
        assert "Report 6" in report_six_html
        assert "Report 1" in report_six_html

        settings_response = client.get(reverse("settings:index"))
        assert settings_response.status_code == 200
        settings_html = settings_response.content.decode()
        assert "General settings" in settings_html
        assert "Fiscal year" in settings_html
        assert "AI integration" in settings_html

        fiscal_settings_response = client.get(reverse("settings:section", kwargs={"slug": "fiscal"}))
        assert fiscal_settings_response.status_code == 200
        assert "Fiscal year settings" in fiscal_settings_response.content.decode()

        detail_response = client.get(reverse("reports:detail", args=[record.pk]))
        assert detail_response.status_code == 200
        assert "Download original PDF" in detail_response.content.decode()

        download_response = client.get(reverse("reports:download", args=[record.pk]))
        assert download_response.status_code == 200
        assert download_response["Content-Type"] == "application/pdf"
        assert download_response["Content-Disposition"].startswith("attachment;")
        download_bytes = b"".join(download_response.streaming_content)
        assert download_bytes.startswith(b"%PDF")


def _build_weekly_sales_pdf(lines: list[str]) -> bytes:
    body = "\n".join(lines)
    return f"%PDF-1.4\n{body}\n%%EOF".encode("latin1")
