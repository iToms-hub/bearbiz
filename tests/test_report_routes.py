from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
import pytest


from apps.core.ai import AIAnalysisResult
from apps.core.models import AIIntegrationSettings
from apps.core.models import FiscalYearSettings
from apps.reports.models import BonusClubSummary, GiftCardsSummary, RankingSummary, ReportUpload, SegmentsSummary, WeeklySalesSummary


@pytest.fixture()
def client() -> Client:
    return Client()


@pytest.mark.django_db()
def test_weekly_sales_upload_history_and_download_routes(client: Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    fake_report = SimpleNamespace(
        payload={
            "fiscal": {"fiscal_year": 2026, "fiscal_week_number": 1, "week_ending_date": "2026-02-07"},
            "summary_kpis": {
                "total_sales": 20366,
                "ly_total_sales": 23198,
                "target_total_sales": 23800,
                "pct_to_target": -17.1,
                "enterprise_sales": 30,
                "traffic_leverage": 4.0,
                "conversion_rate": 18.6,
                "ly_conversion_rate": 17.6,
                "traffic": 2207,
                "ly_traffic": 2668,
                "pct_change_to_ly_traffic": -17.28,
                "sales_trans": 410,
                "dpt": 48.14,
                "ly_dpt": 48.4,
                "upt": 3.9,
                "capture_rate": 66.2,
                "star": 4.9,
            },
            "summary_rows": [],
        },
        period_start="2026-02-01",
        period_end="2026-02-07",
    )
    monkeypatch.setattr("apps.reports.views._extract_pdf_text", lambda path: "fake extracted text")
    monkeypatch.setattr("apps.reports.views.get", lambda slug: SimpleNamespace(parse=lambda raw_text: fake_report))

    pdf_bytes = _build_weekly_sales_pdf(["Weekly Sales Summary", "Period Start    2026-02-01", "Period End    2026-02-07"])
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
        assert summary.raw_json["summary_kpis"]["total_sales"] == 20366
        assert summary.raw_json["summary_kpis"]["ly_total_sales"] == 23198

        history_response = client.get(reverse("reports:history"))
        assert history_response.status_code == 200
        history_html = history_response.content.decode()
        assert "Weekly sales" in history_html
        assert "week-1-sales.pdf" in history_html
        assert '<h1>Weekly sales</h1>' in history_html
        assert 'Weekly sales uploads, parsed rows, and the live report history.' in history_html
        assert 'class="upload-form"' in history_html
        assert 'class="upload-file-row"' in history_html
        assert 'Upload file' in history_html
        assert 'Bearbiz' in history_html
        assert '© 2026 · coded by Claire · itoms.org · v0.9.8' in history_html
        assert "Uploaded reports" in history_html
        assert "Settings" in history_html
        assert 'aria-label="Uploads tabs"' not in history_html

        history_six_response = client.get(reverse("reports:history-number", kwargs={"number": 6}))
        assert history_six_response.status_code == 200
        history_six_html = history_six_response.content.decode()
        assert "Report 6" in history_six_html
        assert "Uploads for this report type are not set up yet." in history_six_html
        assert "Upload file" not in history_six_html

        report_six_response = client.get(reverse("reports:report-number", kwargs={"number": 6}))
        assert report_six_response.status_code == 200
        report_six_html = report_six_response.content.decode()
        assert "Report 6 data" in report_six_html
        assert "report-grid" in report_six_html
        assert "02/07/26" in report_six_html
        assert "$20,366" in report_six_html
        assert 'aria-label="Section tabs"' not in report_six_html
        assert 'class="page-action upload-action"' not in report_six_html
        assert 'Showing totals for last week' in report_six_html
        assert "LY Traffic" not in report_six_html
        assert "Sales Tr" not in report_six_html
        assert "Cap Rate" not in report_six_html
        assert "week-1-sales.pdf" not in report_six_html
        assert "Download" not in report_six_html
        assert "Delete" not in report_six_html

        settings_response = client.get(reverse("settings:index"))
        assert settings_response.status_code == 200
        settings_html = settings_response.content.decode()
        assert "Theme" in settings_html
        assert "System" in settings_html
        assert "Ocean" in settings_html
        assert "General settings" not in settings_html
        assert "Fiscal year" in settings_html
        assert "AI integration" in settings_html

        ai_settings_response = client.get(reverse("settings:section", kwargs={"slug": "ai"}))
        assert ai_settings_response.status_code == 200
        ai_settings_html = ai_settings_response.content.decode()
        assert "AI integration settings" in ai_settings_html
        assert "Provider name" in ai_settings_html

        fiscal_settings_response = client.get(reverse("settings:section", kwargs={"slug": "fiscal"}))
        assert fiscal_settings_response.status_code == 200
        assert "Fiscal year settings" in fiscal_settings_response.content.decode()

        detail_response = client.get(reverse("reports:detail", args=[record.pk]))
        assert detail_response.status_code == 200
        detail_html = detail_response.content.decode()
        assert "Weekly summary metrics" in detail_html
        assert "Week" in detail_html
        assert "02/07/2026" in detail_html
        assert "Sales" in detail_html
        assert "LY Sales" in detail_html
        assert "Target" in detail_html
        assert "Traffic" in detail_html
        assert "Cap Rate" in detail_html
        assert "Parse details" not in detail_html

        download_response = client.get(reverse("reports:download", args=[record.pk]))
        assert download_response.status_code == 200
        assert download_response["Content-Type"] == "application/pdf"
        assert download_response["Content-Disposition"].startswith("attachment;")
        download_bytes = b"".join(download_response.streaming_content)
        assert download_bytes.startswith(b"%PDF")

        delete_response = client.post(reverse("reports:delete", args=[record.pk]))
        assert delete_response.status_code == 302
        assert delete_response["Location"] == reverse("reports:history")
        assert ReportUpload.objects.count() == 0
        assert WeeklySalesSummary.objects.count() == 0

        dashboard_response = client.get(reverse("dashboard"))
        assert dashboard_response.status_code == 200
        dashboard_html = dashboard_response.content.decode()
        assert "Open Report 1" not in dashboard_html
        assert "Overview" not in dashboard_html
        assert "Uploads" not in dashboard_html
        assert "Week window" not in dashboard_html
        assert "Recent uploads" not in dashboard_html
        assert "week-1-sales.pdf" not in dashboard_html


@pytest.mark.django_db()
def test_dashboard_shows_last_six_weekly_sales_rows_with_report_view_headers(client: Client, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    with override_settings(MEDIA_ROOT=media_root):
        for fiscal_week, week_end, sales in [
            (30, date(2026, 7, 26), 1000),
            (31, date(2026, 8, 2), 2000),
            (32, date(2026, 8, 9), 3000),
            (33, date(2026, 8, 16), 4000),
            (34, date(2026, 8, 23), 5000),
            (35, date(2026, 8, 30), 6000),
            (36, date(2026, 9, 6), 7000),
        ]:
            upload = ReportUpload.objects.create(
                source_file=SimpleUploadedFile(f"week-{fiscal_week}-sales.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
                source_name=f"week-{fiscal_week}-sales.pdf",
                report_type="weekly_sales",
                parse_status="parsed",
            )
            WeeklySalesSummary.objects.create(
                report_upload=upload,
                fiscal_year=2026,
                fiscal_week=fiscal_week,
                fiscal_period_start=week_end - timedelta(days=6),
                fiscal_period_end=week_end,
                raw_json={
                    "parse_version": 2,
                    "fiscal": {
                        "fiscal_year": 2026,
                        "fiscal_week_number": fiscal_week,
                        "week_ending_date": week_end.isoformat(),
                    },
                    "summary_kpis": {
                        "total_sales": sales,
                        "ly_total_sales": sales - 100,
                        "target_total_sales": sales + 200,
                        "pct_to_target": 5.5,
                        "enterprise_sales": 42,
                        "traffic_leverage": 3.2,
                        "conversion_rate": 18.1,
                        "ly_conversion_rate": 17.2,
                        "traffic": 2100,
                        "ly_traffic": 2000,
                        "pct_change_to_ly_traffic": 5.0,
                        "sales_trans": 400 + fiscal_week,
                        "dpt": 48.14,
                        "ly_dpt": 47.9,
                        "upt": 3.9,
                        "capture_rate": 66.2,
                        "star": 4.9,
                    },
                    "summary_rows": [],
                },
            )

        response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Weekly Sales Reports" in html
    assert "214 Temecula: Week 36" in html
    assert '<div class="eyebrow">Dashboard</div>' in html
    assert "6-week sales report data" not in html
    assert "Sales" in html
    assert "LY Sales" in html
    assert "Target" in html
    assert "LY Traffic" not in html
    assert "Sales Tr" not in html
    assert "Cap Rate" not in html
    assert html.count('class="report-week-row"') == 5
    assert 'class="report-week-row report-week-row-latest"' in html
    assert 'class="report-spacer-row"' in html
    assert "report-summary-trend" in html
    assert "Trend" in html
    assert "+$5,000" in html


@pytest.mark.django_db()
def test_dashboard_shows_last_four_ranking_reports(client: Client, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    with override_settings(MEDIA_ROOT=media_root):
        for fiscal_week, week_end, rank in [
            (30, date(2026, 7, 26), 5),
            (31, date(2026, 8, 2), 4),
            (32, date(2026, 8, 9), 3),
            (33, date(2026, 8, 16), 2),
            (34, date(2026, 8, 23), 1),
        ]:
            upload = ReportUpload.objects.create(
                source_file=SimpleUploadedFile(f"ranking-{fiscal_week}.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
                source_name=f"ranking-{fiscal_week}.pdf",
                report_type="ranking",
                parse_status="parsed",
            )
            RankingSummary.objects.create(
                report_upload=upload,
                fiscal_year=2026,
                fiscal_week=fiscal_week,
                fiscal_period_start=week_end - timedelta(days=6),
                fiscal_period_end=week_end,
                raw_json={
                    "parse_version": 2,
                    "fiscal": {
                        "fiscal_year": 2026,
                        "fiscal_week_number": fiscal_week,
                        "week_ending_date": week_end.isoformat(),
                    },
                    "store_count": 2,
                    "target_store": {
                        "store_number": "214",
                        "store_name": "Temecula",
                        "ranks": {
                            "sales": {"rank": rank, "total": 5},
                            "sales_v_plan": {"rank": rank, "total": 5},
                            "sales_v_ly": {"rank": rank, "total": 5},
                            "dpt": {"rank": rank, "total": 5},
                            "upt": {"rank": rank, "total": 5},
                            "parties": {"rank": rank, "total": 5},
                            "traffic_bw": {"rank": rank, "total": 5},
                            "conv_ty": {"rank": rank, "total": 5},
                            "conv_bw": {"rank": rank, "total": 5},
                            "stuffers": {"rank": rank, "total": 5},
                        },
                    },
                    "viewer": {
                        "headers": ["Week", "Date", "Sales", "Sales v plan", "Sales v ly", "DPT", "UPT", "Parties", "Traffic b/w", "Conv ty", "Conv b/w", "Stuffers"],
                        "values": [fiscal_week, week_end.strftime("%m/%d/%y"), *([f"{rank}/5"] * 10)],
                    },
                },
            )

        response = client.get(reverse("dashboard"), data={"format": "json"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ranking"]["headers"][:2] == ["Week", "Date"]
    assert len(payload["ranking"]["rows"]) == 4
    assert [row["values"][0] for row in payload["ranking"]["rows"]] == [31, 32, 33, 34]
    assert payload["ranking"]["rows"][-1]["values"][0] == 34
    assert any("1/5" in str(value) for value in payload["ranking"]["rows"][-1]["values"])


@pytest.mark.django_db()
def test_dashboard_shows_last_four_segment_reports_with_managers(client: Client, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    with override_settings(MEDIA_ROOT=media_root):
        for fiscal_week, week_end, manager_name in [
            (30, date(2026, 7, 26), "Avery"),
            (31, date(2026, 8, 2), "Bailey"),
            (32, date(2026, 8, 9), "Casey"),
            (33, date(2026, 8, 16), "Drew"),
            (34, date(2026, 8, 23), "Emery"),
        ]:
            upload = ReportUpload.objects.create(
                source_file=SimpleUploadedFile(f"segments-{fiscal_week}.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
                source_name=f"segments-{fiscal_week}.pdf",
                report_type="segments",
                parse_status="parsed",
            )
            SegmentsSummary.objects.create(
                report_upload=upload,
                fiscal_year=2026,
                fiscal_week=fiscal_week,
                fiscal_period_start=week_end - timedelta(days=6),
                fiscal_period_end=week_end,
                raw_json={
                    "parse_version": 2,
                    "fiscal": {
                        "fiscal_year": 2026,
                        "fiscal_week_number": fiscal_week,
                        "week_ending_date": week_end.isoformat(),
                    },
                    "manager_rows": [
                        {
                            "name": manager_name,
                            "job_title": "SL",
                            "row_kind": "manager",
                            "visible_values": ["10", "25.0 %", "6", "60.0 %", "$6,349", "130", "12.8", "48.82", "3.95"],
                            "metrics": {
                                "segment_count": 10,
                                "segment_total_pct": 25.0,
                                "success_segments": 6,
                                "success_pct": 60.0,
                                "store_sales": 6349,
                                "sales_trans": 130,
                                "conversion": 12.8,
                                "dpt": 48.82,
                                "upt": 3.95,
                            },
                        },
                        {
                            "name": f"{manager_name} Alt",
                            "job_title": "AWM",
                            "row_kind": "manager",
                            "visible_values": ["4", "10.0 %", "2", "50.0 %", "$2,250", "44", "9.1", "45.0", "2.8"],
                            "metrics": {
                                "segment_count": 4,
                                "segment_total_pct": 10.0,
                                "success_segments": 2,
                                "success_pct": 50.0,
                                "store_sales": 2250,
                                "sales_trans": 44,
                                "conversion": 9.1,
                                "dpt": 45.0,
                                "upt": 2.8,
                            },
                        },
                    ],
                    "store_total": {
                        "name": "Store Total",
                        "visible_values": ["36", "100.0 %", "15", "41.7 %", "$19,158", "399", "12.4", "48", "3.72"],
                    },
                },
            )

        response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Segment Accountability" in html
    assert "Avery" not in html
    assert "Bailey" in html
    assert "Casey" in html
    assert "Drew" in html
    assert "Emery" in html
    assert "report-grid-associate" in html
    assert html.count('class="report-week-row"') >= 4


@pytest.mark.django_db()
def test_dashboard_shows_last_week_store_bonus_club_and_gift_cards_metrics(client: Client, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    with override_settings(MEDIA_ROOT=media_root):
        for fiscal_week, week_end, store_sales, bonus_pct, gc_bonus_pct in [
            (33, date(2026, 8, 16), 6100, 46.0, 9.5),
            (34, date(2026, 8, 23), 7200, 58.0, 12.5),
        ]:
            bonus_upload = ReportUpload.objects.create(
                source_file=SimpleUploadedFile(f"bonus-club-{fiscal_week}.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
                source_name=f"bonus-club-{fiscal_week}.pdf",
                report_type="bonus_club",
                parse_status="parsed",
            )
            BonusClubSummary.objects.create(
                report_upload=bonus_upload,
                fiscal_year=2026,
                fiscal_week=fiscal_week,
                fiscal_period_start=week_end - timedelta(days=6),
                fiscal_period_end=week_end,
                raw_json={
                    "parse_version": 2,
                    "fiscal": {
                        "fiscal_year": 2026,
                        "fiscal_week_number": fiscal_week,
                        "week_ending_date": week_end.isoformat(),
                    },
                    "associate_rows": [
                        {
                            "row_kind": "associate",
                            "associate_number": "0079555",
                            "name": "Montejano, Mindy",
                            "metrics": {"total_transactions": 75, "transactions_with_club": 40, "capture_rate": 53.3},
                        }
                    ],
                    "store_total": {
                        "name": "Store Sales",
                        "associate_number": "",
                        "metrics": {
                            "total_transactions": 100,
                            "transactions_with_club": 58,
                            "capture_rate": bonus_pct,
                        },
                    },
                },
            )

            gift_upload = ReportUpload.objects.create(
                source_file=SimpleUploadedFile(f"gift-cards-{fiscal_week}.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
                source_name=f"gift-cards-{fiscal_week}.pdf",
                report_type="gift_cards",
                parse_status="parsed",
            )
            GiftCardsSummary.objects.create(
                report_upload=gift_upload,
                fiscal_year=2026,
                fiscal_week=fiscal_week,
                fiscal_period_start=week_end - timedelta(days=6),
                fiscal_period_end=week_end,
                raw_json={
                    "parse_version": 2,
                    "fiscal": {
                        "fiscal_year": 2026,
                        "fiscal_week_number": fiscal_week,
                        "week_ending_date": week_end.isoformat(),
                    },
                    "associate_rows": [
                        {
                            "row_kind": "associate",
                            "associate_number": "0079555",
                            "name": "Montejano, Mindy",
                            "metrics": {"total_transactions": 75, "gc_bonus_transactions": 16, "bonus_percent": 21.0, "missed_opportunities": None},
                        }
                    ],
                    "store_total": {
                        "name": "Store Sales",
                        "associate_number": "",
                        "metrics": {
                            "total_transactions": 409,
                            "gc_bonus_transactions": 41,
                            "bonus_percent": gc_bonus_pct,
                            "missed_opportunities": 123.45,
                        },
                    },
                },
            )

        response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Bonus Club" in html
    assert "Gift Card Bonus" in html
    assert "dashboard-split-grid" in html
    assert "dashboard-top-metrics" in html
    assert "class=\"panel dashboard-card stack\"" in html
    assert "08/23/26" not in html
    assert "08/16/26" not in html
    assert "Montejano, Mindy" not in html
    assert "Store Sales" not in html
    assert "7200" not in html
    assert "6100" not in html
    assert "58.0 %" in html or "58%" in html
    assert "12.5 %" in html or "12.5%" in html
    assert "46.0 %" not in html
    assert "9.5 %" not in html


@pytest.mark.django_db()
def test_weekly_sales_upload_enriches_summary_when_ai_enabled(client: Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    AIIntegrationSettings.objects.create(enabled=True)
    monkeypatch.setattr(
        "apps.reports.views.summarize_weekly_sales_report",
        lambda report_payload, source_name="", raw_text="": AIAnalysisResult(
            enabled=True,
            provider="openai-compatible",
            model="gpt-4o-mini",
            summary="AI summary from the weekly report.",
            payload={"insights": ["Revenue climbed week over week."]},
        ),
    )

    pdf_bytes = _build_weekly_sales_pdf(
        [
            "Weekly Sales Summary",
            "Period Start    2026-08-31",
            "Period End    2026-09-06",
            "Net Sales    1200",
            "Orders    48",
        ]
    )
    upload = SimpleUploadedFile("week-2-sales.pdf", pdf_bytes, content_type="application/pdf")

    with override_settings(MEDIA_ROOT=media_root):
        response = client.post(reverse("reports:upload"), data={"source_file": upload})

    assert response.status_code == 302
    record = ReportUpload.objects.get()
    summary = WeeklySalesSummary.objects.get(report_upload=record)
    assert summary.ai_summary == "AI summary from the weekly report."
    assert summary.ai_provider == "openai-compatible"
    assert summary.ai_model == "gpt-4o-mini"
    assert summary.ai_payload["insights"] == ["Revenue climbed week over week."]

    detail_response = client.get(reverse("reports:detail", args=[record.pk]))
    assert detail_response.status_code == 200
    detail_html = detail_response.content.decode()
    assert "AI summary from the weekly report." in detail_html
    assert "openai-compatible" in detail_html


@pytest.mark.django_db()
def test_report_view_date_filters(client: Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    monkeypatch.setattr("apps.reports.views._current_date", lambda: date(2026, 9, 15))

    weekly_rows = [
        ("week-36-sales.pdf", date(2026, 9, 6), 36, 1000),
        ("week-35-sales.pdf", date(2026, 8, 30), 35, 900),
        ("week-26-sales.pdf", date(2026, 6, 27), 26, 800),
    ]

    with override_settings(MEDIA_ROOT=media_root):
        for source_name, week_end, fiscal_week, sales in weekly_rows:
            upload = ReportUpload.objects.create(
                source_file=SimpleUploadedFile(source_name, b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
                source_name=source_name,
                parse_status="parsed",
            )
            WeeklySalesSummary.objects.create(
                report_upload=upload,
                fiscal_year=2026,
                fiscal_week=fiscal_week,
                fiscal_period_end=week_end,
                raw_json={
                    "fiscal": {
                        "fiscal_year": 2026,
                        "fiscal_week_number": fiscal_week,
                        "week_ending_date": week_end.isoformat(),
                    },
                    "summary_kpis": {
                        "total_sales": sales,
                        "ly_total_sales": sales - 50,
                        "target_total_sales": sales + 100,
                        "pct_to_target": 5.0,
                        "enterprise_sales": 10,
                        "traffic_leverage": 2.1,
                        "conversion_rate": 3.2,
                        "ly_conversion_rate": 3.0,
                        "traffic": 111,
                        "ly_traffic": 99,
                        "pct_change_to_ly_traffic": 12.12,
                        "sales_trans": 44,
                        "dpt": 23.4,
                        "ly_dpt": 22.8,
                        "upt": 1.8,
                        "capture_rate": 66.0,
                        "star": 4.5,
                    },
                    "summary_rows": [],
                },
            )

        last_week_response = client.get(reverse("reports:index"))
        assert last_week_response.status_code == 200
        last_week_html = last_week_response.content.decode()
        assert "report-grid" in last_week_html
        assert "Last week" in last_week_html
        assert "Year" in last_week_html
        assert "All reports" not in last_week_html
        assert "09/06/26" in last_week_html
        assert "08/30/26" not in last_week_html
        assert "06/27/26" not in last_week_html

        year_response = client.get(reverse("reports:index"), data={"date_filter": "year"})
        assert year_response.status_code == 200
        year_html = year_response.content.decode()
        assert "Jun 2026" in year_html
        assert "Aug 2026" in year_html
        assert "Sep 2026" in year_html
        assert "Q2 2026" in year_html
        assert "Q3 2026" in year_html
        assert "2026 Total" in year_html
        june_week = year_html.index("06/27/26")
        june_month = year_html.index("Jun 2026")
        q2_row = year_html.index("Q2 2026")
        aug_week = year_html.index("08/30/26")
        aug_month = year_html.index("Aug 2026")
        sep_week = year_html.index("09/06/26")
        sep_month = year_html.index("Sep 2026")
        q3_row = year_html.index("Q3 2026")
        year_total = year_html.index("2026 Total")
        assert june_week < june_month < q2_row < aug_week < aug_month < sep_week < sep_month < q3_row < year_total
        assert "report-summary-row" in year_html
        assert "report-week-row-even" in year_html or "report-week-row-odd" in year_html

        month_response = client.get(reverse("reports:index"), data={"date_filter": "month"})
        month_html = month_response.content.decode()
        assert "09/06/26" in month_html
        assert "08/30/26" not in month_html
        assert "06/27/26" not in month_html
        assert "Sep 2026" in month_html
        assert month_html.index("09/06/26") < month_html.index("Sep 2026")

        quarter_response = client.get(reverse("reports:index"), data={"date_filter": "quarter"})
        quarter_html = quarter_response.content.decode()
        assert "09/06/26" in quarter_html
        assert "08/30/26" in quarter_html
        assert "06/27/26" not in quarter_html
        assert "Aug 2026" in quarter_html
        assert "Sep 2026" in quarter_html
        assert "Q3 2026" in quarter_html
        assert quarter_html.index("08/30/26") < quarter_html.index("Aug 2026") < quarter_html.index("09/06/26") < quarter_html.index("Sep 2026") < quarter_html.index("Q3 2026")

        week_response = client.get(reverse("reports:index"), data={"date_filter": "week", "week_end": "2026-09-06"})
        week_html = week_response.content.decode()
        assert "09/06/26" in week_html
        assert "08/30/26" not in week_html

        range_response = client.get(
            reverse("reports:index"),
            data={"date_filter": "range", "range_start": "2026-08-01", "range_end": "2026-09-06"},
        )
        range_html = range_response.content.decode()
        assert "09/06/26" in range_html
        assert "08/30/26" in range_html
        assert "06/27/26" not in range_html


@pytest.mark.django_db()
def test_weekly_sales_view_repairs_week_numbers_from_fiscal_settings(client: Client, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))

    with override_settings(MEDIA_ROOT=media_root):
        upload = ReportUpload.objects.create(
            source_file=SimpleUploadedFile("week-1-sales.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
            source_name="week-1-sales.pdf",
            report_type="weekly_sales",
            parse_status="parsed",
        )
        WeeklySalesSummary.objects.create(
            report_upload=upload,
            fiscal_year=2026,
            fiscal_week=6,
            fiscal_period_start=date(2026, 2, 1),
            fiscal_period_end=date(2026, 2, 7),
            raw_json={
                "parse_version": 1,
                "raw_text": """Weekly Sales Summary
Period Start    2026-02-01
Period End    2026-02-07
Net Sales    20366
Orders    410
""",
                "fiscal": {
                    "fiscal_year": 2026,
                    "fiscal_week_number": 6,
                    "week_ending_date": "2026-02-07",
                },
                "summary_kpis": {"total_sales": 20366},
                "summary_rows": [],
            },
        )

        response = client.get(reverse("reports:report-number", kwargs={"number": 6}))

    assert response.status_code == 200
    refreshed = WeeklySalesSummary.objects.get(report_upload=upload)
    assert refreshed.fiscal_week == 1
    assert refreshed.raw_json["parse_version"] == 2


@pytest.mark.django_db()
def test_ranking_upload_history_and_view_routes(client: Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    fake_report = SimpleNamespace(
        payload={
            "fiscal": {"fiscal_year": 2026, "fiscal_week_number": 1, "week_ending_date": "2026-02-07"},
            "store_count": 2,
            "target_store": {
                "store_number": "214",
                "store_name": "Temecula",
                "ranks": {
                    "sales": {"rank": 1, "total": 2},
                    "sales_v_plan": {"rank": 1, "total": 2},
                    "sales_v_ly": {"rank": 1, "total": 2},
                    "dpt": {"rank": 1, "total": 2},
                    "upt": {"rank": 1, "total": 2},
                    "parties": {"rank": 1, "total": 2},
                    "traffic_bw": {"rank": 2, "total": 2},
                    "conv_ty": {"rank": 2, "total": 2},
                    "conv_bw": {"rank": 1, "total": 2},
                    "stuffers": {"rank": 1, "total": 2},
                },
            },
            "viewer": {
                "headers": ["Week", "Date", "Sales", "Sales v plan", "Sales v ly", "DPT", "UPT", "Parties", "Traffic b/w", "Conv ty", "Conv b/w", "Stuffers"],
                "values": [1, "02/07/26", "1/2", "1/2", "1/2", "1/2", "1/2", "1/2", "2/2", "2/2", "1/2", "1/2"],
            },
        },
        period_start="2026-02-01",
        period_end="2026-02-07",
    )
    monkeypatch.setattr("apps.reports.views._extract_pdf_text", lambda path: "fake ranking text")
    monkeypatch.setattr("apps.reports.views.get", lambda slug: SimpleNamespace(parse=lambda raw_text: fake_report))

    pdf_bytes = _build_weekly_sales_pdf(["FW: Week ending '26 FW01 (run for week ending 02/07/2026)", "214 Temecula", "$20,248", "-14.9 %"])
    upload = SimpleUploadedFile("store-by-store.pdf", pdf_bytes, content_type="application/pdf")

    with override_settings(MEDIA_ROOT=media_root):
        response = client.post(reverse("reports:history-number", kwargs={"number": 2}), data={"source_file": upload})

        assert response.status_code == 302
        record = ReportUpload.objects.get(report_type="ranking")
        assert record.source_name == "store-by-store.pdf"
        assert record.parse_status == "parsed"
        summary = RankingSummary.objects.get(report_upload=record)
        assert summary.fiscal_week == 1
        assert summary.raw_json["target_store"]["store_name"] == "Temecula"

        history_response = client.get(reverse("reports:history-number", kwargs={"number": 2}))
        assert history_response.status_code == 200
        history_html = history_response.content.decode()
        assert "Ranking" in history_html
        assert "Upload file" in history_html
        assert "store-by-store.pdf" in history_html

        report_response = client.get(reverse("reports:report-number", kwargs={"number": 2}))
        assert report_response.status_code == 200
        report_html = report_response.content.decode()
        assert "Last week" in report_html
        assert "Year" in report_html
        assert "Store ranking data" in report_html
        assert "Week" in report_html
        assert "Date" in report_html
        assert "Sales" in report_html
        assert "Stuffers" in report_html
        assert "1/2" in report_html

        ranking_year_response = client.get(reverse("reports:report-number", kwargs={"number": 2}), data={"date_filter": "year"})
        assert ranking_year_response.status_code == 200
        ranking_year_html = ranking_year_response.content.decode()
        assert "Year" in ranking_year_html
        assert "1/2" in ranking_year_html
        assert "2/2" in report_html

        detail_response = client.get(reverse("reports:detail", args=[record.pk]))
        assert detail_response.status_code == 200
        detail_html = detail_response.content.decode()
        assert "Ranking report metrics" in detail_html
        assert "1/2" in detail_html


@pytest.mark.django_db()
def test_ranking_view_repairs_partial_summary(client: Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    partial_report = SimpleNamespace(
        payload={
            "fiscal": {"fiscal_year": 2026, "fiscal_week_number": 1, "week_ending_date": "2026-02-07"},
            "store_count": 2,
            "target_store": {
                "store_number": "214",
                "store_name": "Temecula",
                "ranks": {"sales": {"rank": 1, "total": 2}},
            },
        },
        period_start="2026-02-01",
        period_end="2026-02-07",
    )
    full_report = SimpleNamespace(
        payload={
            "fiscal": {"fiscal_year": 2026, "fiscal_week_number": 1, "week_ending_date": "2026-02-07"},
            "store_count": 2,
            "target_store": {
                "store_number": "214",
                "store_name": "Temecula",
                "ranks": {
                    "sales": {"rank": 1, "total": 2},
                    "sales_v_plan": {"rank": 1, "total": 2},
                    "sales_v_ly": {"rank": 1, "total": 2},
                    "dpt": {"rank": 1, "total": 2},
                    "upt": {"rank": 1, "total": 2},
                    "parties": {"rank": 1, "total": 2},
                    "traffic_bw": {"rank": 2, "total": 2},
                    "conv_ty": {"rank": 2, "total": 2},
                    "conv_bw": {"rank": 1, "total": 2},
                    "stuffers": {"rank": 1, "total": 2},
                },
            },
        },
        period_start="2026-02-01",
        period_end="2026-02-07",
    )
    monkeypatch.setattr("apps.reports.views.get", lambda slug: SimpleNamespace(parse=lambda raw_text: full_report))

    pdf_bytes = _build_weekly_sales_pdf(["FW: Week ending '26 FW01 (run for week ending 02/07/2026)", "214 Temecula", "$20,248", "-14.9 %"])
    upload = SimpleUploadedFile("store-by-store.pdf", pdf_bytes, content_type="application/pdf")

    with override_settings(MEDIA_ROOT=media_root):
        record = ReportUpload.objects.create(
            source_file=upload,
            source_name="store-by-store.pdf",
            report_type="ranking",
            parse_status="parsed",
        )
        RankingSummary.objects.create(
            report_upload=record,
            fiscal_year=2026,
            fiscal_week=1,
            fiscal_period_start=date(2026, 2, 1),
            fiscal_period_end=date(2026, 2, 7),
            raw_json={**partial_report.payload, "raw_text": "fake ranking text"},
        )

        response = client.get(reverse("reports:report-number", kwargs={"number": 2}))

        assert response.status_code == 200
        html = response.content.decode()
        assert "1/2" in html
        assert "2/2" in html

        refreshed = RankingSummary.objects.get(report_upload=record)
        ranks = refreshed.raw_json["target_store"]["ranks"]
        assert len(ranks) == 10


@pytest.mark.django_db()
def test_segments_upload_history_view_and_detail_routes(client: Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    fake_report = SimpleNamespace(
        payload={
            "fiscal": {"fiscal_year": 2026, "fiscal_week_number": 35, "week_ending_date": "2026-08-29"},
            "manager_rows": [
                {
                    "name": "Vanessa Esparza",
                    "job_title": "SL",
                    "row_kind": "manager",
                    "visible_values": ["9", "25.0 %", "6", "66.7 %", "$6,349", "130", "12.8", "48.82", "3.95"],
                    "metrics": {
                        "segment_count": 9,
                        "segment_total_pct": 25.0,
                        "success_segments": 6,
                        "success_pct": 66.7,
                        "store_sales": "$6,349",
                        "sales_trans": 130,
                        "conversion": 12.8,
                        "dpt": 48.82,
                        "upt": 3.95,
                        "visit_value": "6.27",
                    },
                    "viewer": {"values": ["Vanessa Esparza", "9", "25.0 %", "6", "66.7 %", "$6,349", "130", "12.8", "48.82", "3.95"]},
                }
            ],
            "store_total": {
                "name": "Store Total",
                "visible_values": ["36", "100.0 %", "15", "41.7 %", "$19,158", "399", "12.4", "$48", "3.72"],
                "metrics": {
                    "segment_count": 36,
                    "segment_total_pct": 100.0,
                    "success_segments": 15,
                    "success_pct": 41.7,
                    "store_sales": "$19,158",
                    "sales_trans": 399,
                    "conversion": 12.4,
                    "dpt": 48,
                    "upt": 3.72,
                    "visit_value": "$5.93",
                },
            },
            "viewer": {
                "headers": ["Name", "#seg", "% Total", "Success Segments", "% Success", "Store Sales", "Sales Trans", "Conversion", "DPT", "UPT"],
                "rows": [
                    {"values": ["Vanessa Esparza", "9", "25.0 %", "6", "66.7 %", "$6,349", "130", "12.8", "48.82", "3.95"]},
                ],
            },
        },
        period_start="2026-08-23",
        period_end="2026-08-29",
    )
    monkeypatch.setattr("apps.reports.views._extract_pdf_text", lambda path: "fake segments text")
    monkeypatch.setattr("apps.reports.views.get", lambda slug: SimpleNamespace(parse=lambda raw_text: fake_report))

    pdf_bytes = _build_pdf(["Segment Accountability Report", "Vanessa Esparza", "Store Total"])
    upload = SimpleUploadedFile("segments.pdf", pdf_bytes, content_type="application/pdf")

    with override_settings(MEDIA_ROOT=media_root):
        response = client.post(reverse("reports:history-number", kwargs={"number": 3}), data={"source_file": upload})

        assert response.status_code == 302
        record = ReportUpload.objects.get(report_type="segments")
        assert record.source_name == "segments.pdf"
        assert record.parse_status == "parsed"
        summary = SegmentsSummary.objects.get(report_upload=record)
        assert summary.fiscal_week == 35
        assert summary.raw_json["store_total"]["name"] == "Store Total"

        history_response = client.get(reverse("reports:history-number", kwargs={"number": 3}))
        assert history_response.status_code == 200
        history_html = history_response.content.decode()
        assert "Segments" in history_html
        assert "Upload file" in history_html
        assert "segments.pdf" in history_html

        report_response = client.get(reverse("reports:report-number", kwargs={"number": 3}))
        assert report_response.status_code == 200
        report_html = report_response.content.decode()
        assert "Manager segment accountability" in report_html
        assert "Week" in report_html
        assert "Date" in report_html
        assert "08/29/26" in report_html
        assert "Vanessa Esparza" in report_html
        assert "$6,349" in report_html
        assert "Store Total" in report_html
        assert report_html.index("Store Total") > report_html.index("Vanessa Esparza")

        detail_response = client.get(reverse("reports:detail", args=[record.pk]))
        assert detail_response.status_code == 200
        detail_html = detail_response.content.decode()
        assert "Store total metrics" in detail_html
        assert "Store Total" in detail_html


@pytest.mark.django_db()
def test_segments_range_view_with_manager_totals_and_average(client: Client, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    with override_settings(MEDIA_ROOT=media_root):
        weeks = [
            (
                35,
                date(2026, 8, 29),
                {
                    "segment_count": 9,
                    "segment_total_pct": 25.0,
                    "success_segments": 6,
                    "success_pct": 66.7,
                    "store_sales": "$6,349",
                    "sales_trans": 130,
                    "conversion": 12.8,
                    "dpt": 48.82,
                    "upt": 3.95,
                    "visit_value": "6.27",
                },
            ),
            (
                36,
                date(2026, 9, 5),
                {
                    "segment_count": 12,
                    "segment_total_pct": 30.0,
                    "success_segments": 7,
                    "success_pct": 58.3,
                    "store_sales": "$7,000",
                    "sales_trans": 140,
                    "conversion": 13.4,
                    "dpt": 50.0,
                    "upt": 4.0,
                    "visit_value": "6.43",
                },
            ),
        ]
        for fiscal_week, week_end, metrics in weeks:
            upload = ReportUpload.objects.create(
                source_file=SimpleUploadedFile(f"segments-{fiscal_week}.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
                source_name=f"segments-{fiscal_week}.pdf",
                report_type="segments",
                parse_status="parsed",
            )
            SegmentsSummary.objects.create(
                report_upload=upload,
                fiscal_year=2026,
                fiscal_week=fiscal_week,
                fiscal_period_start=week_end.replace(day=1),
                fiscal_period_end=week_end,
                raw_json={
                    "parse_version": 99,
                    "fiscal": {
                        "fiscal_year": 2026,
                        "fiscal_week_number": fiscal_week,
                        "week_ending_date": week_end.isoformat(),
                    },
                    "manager_rows": [
                        {
                            "name": "Vanessa Esparza",
                            "job_title": "SL",
                            "row_kind": "manager",
                            "visible_values": [
                                str(metrics["segment_count"]),
                                f'{metrics["segment_total_pct"]} %',
                                str(metrics["success_segments"]),
                                f'{metrics["success_pct"]} %',
                                metrics["store_sales"],
                                str(metrics["sales_trans"]),
                                str(metrics["conversion"]),
                                str(metrics["dpt"]),
                                str(metrics["upt"]),
                            ],
                            "metrics": metrics,
                        },
                        {
                            "name": "Jordan Lee",
                            "job_title": "AWM",
                            "row_kind": "manager",
                            "visible_values": ["4", "11.1 %", "2", "50.0 %", "$2,250", "44", "9.1", "45.0", "2.8"],
                            "metrics": {
                                "segment_count": 4,
                                "segment_total_pct": 11.1,
                                "success_segments": 2,
                                "success_pct": 50.0,
                                "store_sales": "$2,250",
                                "sales_trans": 44,
                                "conversion": 9.1,
                                "dpt": 45.0,
                                "upt": 2.8,
                            },
                        },
                    ],
                    "store_total": {
                        "name": "Store Total",
                        "visible_values": ["36", "100.0 %", "15", "41.7 %", "$19,158", "399", "12.4", "48", "3.72"],
                    },
                },
            )

        response = client.get(
            reverse("reports:report-number", kwargs={"number": 3}),
            data={"date_filter": "range", "range_start": "2026-08-23", "range_end": "2026-09-12", "associate": "Vanessa Esparza"},
        )

    assert response.status_code == 200
    html = response.content.decode()
    assert "Manager" in html
    assert "Vanessa Esparza" in html
    assert "Jordan Lee" in html
    assert "Store Total" not in html
    assert "<td>Total</td>" in html
    assert "<tr class=\"report-spacer-row\">" in html
    assert "<td>Average</td>" in html
    assert "21" in html
    assert "$13,349" in html
    assert html.index("<td>Total</td>") > html.index("Vanessa Esparza")
    assert html.index("<td>Average</td>") > html.index("<td>Total</td>")


@pytest.mark.django_db()
def test_gift_cards_upload_history_view_and_weekly_sales_dependency(client: Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    fake_report = SimpleNamespace(
        payload={
            "fiscal": {"fiscal_year": 2026, "fiscal_week_number": 1, "week_ending_date": "2026-02-07"},
            "store_number": "1214",
            "weekly_sales_dpt": None,
            "weekly_sales_missing": True,
            "associate_rows": [
                {
                    "row_kind": "associate",
                    "associate_number": "0079555",
                    "name": "Montejano, Mindy",
                    "metrics": {
                        "total_transactions": 75,
                        "total_qualifying_transactions": 75,
                        "gc_bonus_transactions": 16,
                        "bonus_percent": 21.0,
                        "goal_transactions": 13.5,
                        "transaction_gap": -2.5,
                        "weekly_sales_dpt": None,
                        "missed_opportunities": None,
                    },
                    "viewer": {"values": ["0079555", "Montejano, Mindy", "75", "16", "21%", ""]},
                }
            ],
            "store_total": {
                "row_kind": "store_total",
                "associate_number": "",
                "name": "Store Sales",
                "metrics": {
                    "total_transactions": 409,
                    "total_qualifying_transactions": 409,
                    "gc_bonus_transactions": 41,
                    "bonus_percent": 10.0,
                    "goal_transactions": 73.62,
                    "transaction_gap": 32.62,
                    "weekly_sales_dpt": None,
                    "missed_opportunities": None,
                },
                "viewer": {"values": ["", "Store Sales", "409", "41", "10%", ""]},
            },
            "viewer": {
                "headers": ["Associate #", "Name", "Total Transactions", "Total Transactions with GC Bonus", "% Transactions w/ GC Bonus", "Missed Opportunities"],
                "rows": [{"values": ["0079555", "Montejano, Mindy", "75", "16", "21%", ""]}],
            },
        },
        period_start="2026-02-01",
        period_end="2026-02-07",
    )
    monkeypatch.setattr("apps.reports.views._extract_pdf_text", lambda path: "fake gift cards text")
    monkeypatch.setattr("apps.reports.views.get", lambda slug: SimpleNamespace(parse=lambda raw_text: fake_report))

    pdf_bytes = _build_pdf(["Gift Card Bonus Report", "Montejano, Mindy", "Totals"])
    upload = SimpleUploadedFile("gift-cards.pdf", pdf_bytes, content_type="application/pdf")

    with override_settings(MEDIA_ROOT=media_root):
        response = client.post(reverse("reports:history-number", kwargs={"number": 4}), data={"source_file": upload})
        assert response.status_code == 302
        record = ReportUpload.objects.get(report_type="gift_cards")
        assert record.source_name == "gift-cards.pdf"
        summary = GiftCardsSummary.objects.get(report_upload=record)
        assert summary.raw_json["weekly_sales_missing"] is True

        history_response = client.get(reverse("reports:history-number", kwargs={"number": 4}))
        assert history_response.status_code == 200
        history_html = history_response.content.decode()
        assert "Gift Cards" in history_html
        assert "Upload file" in history_html
        assert "gift-cards.pdf" in history_html

        report_response = client.get(reverse("reports:report-number", kwargs={"number": 4}))
        assert report_response.status_code == 200
        report_html = report_response.content.decode()
        assert "Associate gift card bonus performance" in report_html
        assert "Waiting on weekly sales." in report_html
        assert "Montejano, Mindy" in report_html
        assert "Store Sales" in report_html
        assert report_html.index("Store Sales") > report_html.index("Montejano, Mindy")

        weekly_upload = ReportUpload.objects.create(
            source_file=SimpleUploadedFile("week-1-sales.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
            source_name="week-1-sales.pdf",
            report_type="weekly_sales",
            parse_status="parsed",
        )
        WeeklySalesSummary.objects.create(
            report_upload=weekly_upload,
            fiscal_year=2026,
            fiscal_week=1,
            fiscal_period_start=date(2026, 2, 1),
            fiscal_period_end=date(2026, 2, 7),
            raw_json={
                "fiscal": {"fiscal_year": 2026, "fiscal_week_number": 1, "week_ending_date": "2026-02-07"},
                "summary_kpis": {"dpt": 48.14},
            },
        )

        refreshed_response = client.get(reverse("reports:report-number", kwargs={"number": 4}))
        assert refreshed_response.status_code == 200
        refreshed_html = refreshed_response.content.decode()
        assert "Waiting on weekly sales." not in refreshed_html
        assert "$1,570.33" in refreshed_html

        refreshed_summary = GiftCardsSummary.objects.get(report_upload=record)
        assert refreshed_summary.raw_json["weekly_sales_missing"] is False
        assert refreshed_summary.raw_json["weekly_sales_dpt"] == 48.14
        assert refreshed_summary.raw_json["store_total"]["metrics"]["missed_opportunities"] == 1570.33


@pytest.mark.django_db()
def test_bonus_club_upload_history_and_detail(client: Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    fake_report = SimpleNamespace(
        payload={
            "fiscal": {"fiscal_year": 2026, "fiscal_week_number": 1, "week_ending_date": "2026-02-07"},
            "store_number": "1214",
            "associate_rows": [
                {
                    "row_kind": "associate",
                    "associate_number": "0079555",
                    "name": "Montejano, Mindy",
                    "metrics": {
                        "total_transactions": 75,
                        "transactions_with_club": 40,
                        "capture_rate": 53.0,
                    },
                    "viewer": {"values": ["0079555", "Montejano, Mindy", "75", "40", "53%"]},
                }
            ],
            "store_total": {
                "row_kind": "store_total",
                "associate_number": "",
                "name": "Store Sales",
                "metrics": {
                    "total_transactions": 409,
                    "transactions_with_club": 274,
                    "capture_rate": 67.0,
                },
                "viewer": {"values": ["", "Store Sales", "409", "274", "67%"]},
            },
            "viewer": {
                "headers": ["Associate #", "Name", "Total Transactions", "Transactions With Club #", "Bonus Club Capture Rate"],
                "rows": [{"values": ["0079555", "Montejano, Mindy", "75", "40", "53%"]}],
            },
        },
        period_start="2026-02-01",
        period_end="2026-02-07",
    )
    monkeypatch.setattr("apps.reports.views._extract_pdf_text", lambda path: "fake bonus club text")
    monkeypatch.setattr("apps.reports.views.get", lambda slug: SimpleNamespace(parse=lambda raw_text: fake_report))

    pdf_bytes = _build_pdf(["Bonus Club Capture Report", "Montejano, Mindy", "Totals"])
    upload = SimpleUploadedFile("bonus-club.pdf", pdf_bytes, content_type="application/pdf")

    with override_settings(MEDIA_ROOT=media_root):
        response = client.post(reverse("reports:history-number", kwargs={"number": 5}), data={"source_file": upload})
        assert response.status_code == 302
        record = ReportUpload.objects.get(report_type="bonus_club")
        assert record.source_name == "bonus-club.pdf"
        summary = BonusClubSummary.objects.get(report_upload=record)
        assert summary.raw_json["store_number"] == "1214"

        history_response = client.get(reverse("reports:history-number", kwargs={"number": 5}))
        assert history_response.status_code == 200
        history_html = history_response.content.decode()
        assert "Bonus Club" in history_html
        assert "bonus-club.pdf" in history_html
        assert '<h1>Bonus Club</h1>' in history_html
        assert 'Weekly sales uploads, parsed rows, and the live report history.' not in history_html
        assert 'class="upload-form"' in history_html
        assert 'class="upload-file-row"' in history_html
        assert 'Select a PDF' in history_html
        assert 'Upload file' in history_html
        assert 'Bearbiz' in history_html
        assert '© 2026 · coded by Claire · itoms.org · v0.9.8' in history_html
        assert 'aria-label="Uploads tabs"' not in history_html
        assert 'aria-label="Section tabs"' not in history_html

        report_response = client.get(reverse("reports:report-number", kwargs={"number": 5}))
        assert report_response.status_code == 200
        report_html = report_response.content.decode()
        assert "Associate bonus club performance" in report_html
        assert "Missed Opportunities" not in report_html
        assert 'aria-label="Report date selector"' in report_html
        assert reverse("reports:history-number", kwargs={"number": 5}) in report_html
        assert '<a class="page-action upload-action"' in report_html
        assert """.report-toolbar {
        display: flex;
        flex-wrap: wrap;
        justify-content: space-between;
        align-items: center;
        gap: 0.75rem 1rem;
        padding-top: 0.65rem;""" in report_html
        assert """.report-toolbar .report-date-tabs {
        margin: 0;""" in report_html
        assert """.report-toolbar > .report-date-tabs,
      .report-toolbar > .page-action {
        align-self: center;""" in report_html
        assert """.report-toolbar .tab,
      .report-toolbar .page-action {
        padding: 0.42rem 0.7rem;
        font-size: 0.9rem;
        line-height: 1.1;
        border-radius: 0.45rem;""" in report_html
        assert 'Showing totals for last week' in report_html
        assert 'aria-label="Section tabs"' not in report_html

        detail_response = client.get(reverse("reports:detail", args=[record.pk]))
        assert detail_response.status_code == 200
        detail_html = detail_response.content.decode()
        assert "Bonus club rows" in detail_html
        assert "Montejano, Mindy" in detail_html
        assert "Store Sales" in detail_html
        assert "Missed Opportunities" not in detail_html
        detail_table_html = detail_html.split("Bonus club rows", 1)[1]
        assert detail_table_html.index("Store Sales") > detail_table_html.index("Montejano, Mindy")


@pytest.mark.django_db()
def test_gift_cards_associate_range_view(client: Client, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    with override_settings(MEDIA_ROOT=media_root):
        weeks = [
            (
                1,
                date(2026, 2, 7),
                {
                    "total_transactions": 75,
                    "gc_bonus_transactions": 16,
                    "bonus_percent": 21.0,
                    "missed_opportunities": 1570.33,
                },
            ),
            (
                2,
                date(2026, 2, 14),
                {
                    "total_transactions": 80,
                    "gc_bonus_transactions": 18,
                    "bonus_percent": 22.5,
                    "missed_opportunities": 1600.0,
                },
            ),
        ]
        for fiscal_week, week_end, metrics in weeks:
            upload = ReportUpload.objects.create(
                source_file=SimpleUploadedFile(f"gift-cards-{fiscal_week}.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
                source_name=f"gift-cards-{fiscal_week}.pdf",
                report_type="gift_cards",
                parse_status="parsed",
            )
            GiftCardsSummary.objects.create(
                report_upload=upload,
                fiscal_year=2026,
                fiscal_week=fiscal_week,
                fiscal_period_start=week_end.replace(day=1),
                fiscal_period_end=week_end,
                raw_json={
                    "parse_version": 99,
                    "fiscal": {
                        "fiscal_year": 2026,
                        "fiscal_week_number": fiscal_week,
                        "week_ending_date": week_end.isoformat(),
                    },
                    "weekly_sales_dpt": 48.14,
                    "weekly_sales_missing": False,
                    "associate_rows": [
                        {
                            "row_kind": "associate",
                            "associate_number": "0079555",
                            "name": "Montejano, Mindy",
                            "metrics": {**metrics, "total_qualifying_transactions": metrics["total_transactions"], "goal_transactions": 0.0, "transaction_gap": 0.0, "weekly_sales_dpt": 48.14},
                        },
                        {
                            "row_kind": "associate",
                            "associate_number": "0099999",
                            "name": "Vega, Alex",
                            "metrics": {
                                "total_transactions": 10 + fiscal_week,
                                "total_qualifying_transactions": 10 + fiscal_week,
                                "gc_bonus_transactions": 2 + fiscal_week,
                                "bonus_percent": 18.0 + fiscal_week,
                                "goal_transactions": 0.0,
                                "transaction_gap": 0.0,
                                "weekly_sales_dpt": 48.14,
                                "missed_opportunities": 100.0 + fiscal_week,
                            },
                        },
                    ],
                    "store_total": {
                        "row_kind": "store_total",
                        "associate_number": "",
                        "name": "Store Sales",
                        "metrics": {
                            "total_transactions": 409,
                            "total_qualifying_transactions": 409,
                            "gc_bonus_transactions": 41,
                            "bonus_percent": 10.0,
                            "goal_transactions": 73.62,
                            "transaction_gap": 32.62,
                            "weekly_sales_dpt": 48.14,
                            "missed_opportunities": 1570.33,
                        },
                    },
                },
            )

        response = client.get(
            reverse("reports:report-number", kwargs={"number": 4}),
            data={"date_filter": "range", "range_start": "2026-02-01", "range_end": "2026-02-28", "associate": "0079555"},
        )

    assert response.status_code == 200
    html = response.content.decode()
    assert "Associate" in html
    assert "Montejano, Mindy" in html
    assert "Vega, Alex" in html
    assert "Store Sales" not in html
    assert "Average" not in html
    assert "<td>Total</td>" in html
    assert "02/01/26–02/28/26" in html
    assert "$3,170.33" in html
    assert "155" in html
    assert "34" in html
    assert "21.94%" in html


@pytest.mark.django_db()
def test_bonus_club_associate_range_view(client: Client, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    with override_settings(MEDIA_ROOT=media_root):
        weeks = [
            (1, date(2026, 2, 7), {"total_transactions": 75, "transactions_with_club": 40, "capture_rate": 53.0}),
            (2, date(2026, 2, 14), {"total_transactions": 80, "transactions_with_club": 42, "capture_rate": 52.5}),
        ]
        for fiscal_week, week_end, metrics in weeks:
            upload = ReportUpload.objects.create(
                source_file=SimpleUploadedFile(f"bonus-club-{fiscal_week}.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
                source_name=f"bonus-club-{fiscal_week}.pdf",
                report_type="bonus_club",
                parse_status="parsed",
            )
            BonusClubSummary.objects.create(
                report_upload=upload,
                fiscal_year=2026,
                fiscal_week=fiscal_week,
                fiscal_period_start=week_end.replace(day=1),
                fiscal_period_end=week_end,
                raw_json={
                    "parse_version": 99,
                    "fiscal": {
                        "fiscal_year": 2026,
                        "fiscal_week_number": fiscal_week,
                        "week_ending_date": week_end.isoformat(),
                    },
                    "associate_rows": [
                        {
                            "row_kind": "associate",
                            "associate_number": "0079555",
                            "name": "Montejano, Mindy",
                            "metrics": metrics,
                        },
                        {
                            "row_kind": "associate",
                            "associate_number": "0099999",
                            "name": "Vega, Alex",
                            "metrics": {
                                "total_transactions": 10 + fiscal_week,
                                "transactions_with_club": 5 + fiscal_week,
                                "capture_rate": 45.0 + fiscal_week,
                            },
                        },
                    ],
                    "store_total": {
                        "row_kind": "store_total",
                        "associate_number": "",
                        "name": "Store Sales",
                        "metrics": {
                            "total_transactions": 409,
                            "transactions_with_club": 274,
                            "capture_rate": 67.0,
                        },
                    },
                },
            )

        response = client.get(
            reverse("reports:report-number", kwargs={"number": 5}),
            data={"date_filter": "range", "range_start": "2026-02-01", "range_end": "2026-02-28", "associate": "0079555"},
        )

    assert response.status_code == 200
    html = response.content.decode()
    assert "Associate" in html
    assert "Montejano, Mindy" in html
    assert "Vega, Alex" in html
    assert "Store Sales" not in html
    assert "Missed Opportunities" not in html
    assert "Average" not in html
    assert "<td>Total</td>" in html
    assert "02/01/26–02/28/26" in html
    assert "155" in html
    assert "82" in html
    assert "52.9%" in html


@pytest.mark.django_db()
def test_gift_cards_failed_detail_view_repairs_summary(client: Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    fake_report = SimpleNamespace(
        payload={
            "fiscal": {"fiscal_year": 2026, "fiscal_week_number": 1, "week_ending_date": "2026-02-07"},
            "store_number": "1214",
            "weekly_sales_dpt": None,
            "weekly_sales_missing": True,
            "associate_rows": [
                {
                    "row_kind": "associate",
                    "associate_number": "0079555",
                    "name": "Montejano, Mindy",
                    "metrics": {
                        "total_transactions": 75,
                        "gc_bonus_transactions": 16,
                        "bonus_percent": 21.0,
                        "missed_opportunities": None,
                    },
                    "viewer": {"values": ["0079555", "Montejano, Mindy", "75", "16", "21%", ""]},
                }
            ],
            "store_total": {
                "row_kind": "store_total",
                "associate_number": "",
                "name": "Store Sales",
                "metrics": {
                    "total_transactions": 409,
                    "gc_bonus_transactions": 41,
                    "bonus_percent": 10.0,
                    "missed_opportunities": None,
                },
                "viewer": {"values": ["", "Store Sales", "409", "41", "10%", ""]},
            },
            "viewer": {"headers": ["Associate #", "Name", "Total Transactions", "Total Transactions with GC Bonus", "% Transactions w/ GC Bonus", "Missed Opportunities"], "rows": [{"values": ["0079555", "Montejano, Mindy", "75", "16", "21%", ""]}]},
        },
        period_start="2026-02-01",
        period_end="2026-02-07",
    )
    monkeypatch.setattr("apps.reports.views._extract_pdf_text", lambda path: "fake gift cards text")
    monkeypatch.setattr("apps.reports.views.get", lambda slug: SimpleNamespace(parse=lambda raw_text: fake_report))

    pdf_bytes = _build_pdf(["Gift Card Bonus Report", "Totals"])
    upload = SimpleUploadedFile("gift-cards.pdf", pdf_bytes, content_type="application/pdf")

    with override_settings(MEDIA_ROOT=media_root):
        record = ReportUpload.objects.create(
            source_file=upload,
            source_name="gift-cards.pdf",
            report_type="gift_cards",
            parse_status="failed",
            parse_error="invalid literal for int() with base 10: 'None'",
        )

        response = client.get(reverse("reports:detail", kwargs={"pk": record.pk}))
        assert response.status_code == 200
        detail_html = response.content.decode()
        assert "Gift card rows" in detail_html
        assert "Montejano, Mindy" in detail_html
        assert "Store Sales" in detail_html
        gift_table_html = detail_html.split("Gift card rows", 1)[1]
        assert gift_table_html.index("Store Sales") > gift_table_html.index("Montejano, Mindy")
        record.refresh_from_db()
        assert record.parse_status == "parsed"
        summary = GiftCardsSummary.objects.get(report_upload=record)
        assert summary.raw_json["store_number"] == "1214"
        assert summary.raw_json["weekly_sales_missing"] is True


def _build_weekly_sales_pdf(lines: list[str]) -> bytes:
    body = "\n".join(lines)
    return f"%PDF-1.4\n{body}\n%%EOF".encode("latin1")


@pytest.mark.django_db()
def test_report_pdf_action_is_the_only_export_for_all_report_types_and_preserves_filters(client: Client) -> None:
    query = {
        "date_filter": "range",
        "range_start": "2026-02-01",
        "range_end": "2026-02-28",
        "associate": "0079555",
    }

    for number in range(1, 7):
        response = client.get(reverse("reports:report-number", kwargs={"number": number}), data=query)
        assert response.status_code == 200
        html = response.content.decode()
        assert "Print" not in html
        assert "window.print" not in html
        assert "print-action" not in html
        assert "PDF" in html
        assert "Uploads" not in html if number == 6 else "Uploads" in html
        assert "date_filter=range" in html
        assert "range_start=2026-02-01" in html
        assert "range_end=2026-02-28" in html
        assert "associate=0079555" in html
        assert 'class="report-toolbar-actions"' in html
        assert 'class="page-action pdf-action"' in html
        assert 'class="page-action upload-action"' not in html if number == 6 else 'class="page-action upload-action"' in html
        assert ".page-action.pdf-action" in html
        assert "background: #005ea8;" in html
        assert "color: #fff;" in html
        if number != 6:
            assert html.index('class="page-action pdf-action"') < html.index('class="page-action upload-action"')
        assert 'download="' in html
        assert ".report-week-row-latest" in html
        assert ".report-summary-row" in html
        assert ".report-spacer-row" in html

        pdf_response = client.get(reverse("reports:report-pdf", kwargs={"number": number}), data=query)
        assert pdf_response.status_code == 200
        assert pdf_response["Content-Type"] == "application/pdf"
        assert pdf_response["Content-Disposition"].startswith("attachment;")
        report_names = {
            1: "Weekly Sales Report",
            2: "Ranking Report",
            3: "Segments Report",
            4: "Gift Cards Report",
            5: "Bonus Club Report",
            6: "Report 6",
        }
        assert pdf_response["Content-Disposition"].endswith(
            f'filename="{report_names[number]}: 02-01-26 to 02-28-26.pdf"'
        )
        assert b"%PDF" in pdf_response.content[:16]


@pytest.mark.django_db()
def test_report_pdf_uses_compact_layout_and_fits_current_report_on_one_page(client: Client) -> None:
    pdf_template = Path("templates/reports/report_pdf.html").read_text()
    assert "size: Letter portrait;" in pdf_template
    assert "position: fixed;" in pdf_template
    assert "class=\"pdf-footer\"" in pdf_template
    assert "class=\"pdf-footer-table\"" in pdf_template
    assert 'alt="BEARbiZ banner logo"' in pdf_template
    assert "© BEARbiZ 2026" in pdf_template
    assert "For internal use only" in pdf_template
    assert "Page {{ page_number }} of {{ page_count }}" not in pdf_template
    assert "report_pdf_logo_url" in pdf_template
    assert ".pdf-footer-table td { width: 33.333%;" in pdf_template
    assert '<td class="pdf-footer-left"><img src="{{ report_pdf_logo_url }}" alt="BEARbiZ banner logo"></td>' in pdf_template
    assert '<td class="pdf-footer-center">© BEARbiZ 2026 | For internal use only</td>' in pdf_template
    assert "font-size: 7pt;" in pdf_template
    assert "padding: 0.06cm 0.08cm;" in pdf_template
    assert "th, td {" in pdf_template
    assert "text-align: center;" in pdf_template
    fitz = pytest.importorskip("fitz")
    response = client.get(reverse("reports:report-pdf", kwargs={"number": 1}), data={"date_filter": "last_week"})

    assert response.status_code == 200
    document = fitz.open(stream=response.content, filetype="pdf")
    assert document.page_count == 1
    assert (document[0].rect.width, document[0].rect.height) == (612, 792)
    pdf_text = document[0].get_text()
    assert "© BEARbiZ 2026" in pdf_text
    assert "For internal use only" in pdf_text
    assert "© BEARbiZ 2026 | For internal use only" in pdf_text.replace("\n", " ")
    assert "Page 1 of 1" in pdf_text
    footer_images = document[0].get_images(full=True)
    assert footer_images
    assert any(width / height == pytest.approx(1559 / 941, rel=0.02) for _, _, width, height, *_ in footer_images)
    assert "BEARbiZ banner logo" not in pdf_text


@pytest.mark.django_db()
@pytest.mark.parametrize(
    ("query", "filename"),
    [
        ({"date_filter": "year"}, "Weekly Sales Report: year.pdf"),
        ({"date_filter": "week", "week_end": "2026-02-07"}, "Weekly Sales Report: 02-07-26.pdf"),
        ({"date_filter": "last_week"}, "Weekly Sales Report: last week.pdf"),
        ({"date_filter": "month"}, "Weekly Sales Report: current month.pdf"),
        ({"date_filter": "quarter"}, "Weekly Sales Report: current quarter.pdf"),
        ({"date_filter": "all"}, "Weekly Sales Report: all.pdf"),
    ],
)
def test_report_pdf_filename_reflects_date_selection(client: Client, query: dict[str, str], filename: str) -> None:
    response = client.get(reverse("reports:report-pdf", kwargs={"number": 1}), data=query)

    assert response.status_code == 200
    assert response["Content-Disposition"].endswith(f'filename="{filename}"')


@pytest.mark.django_db()
def test_report_pdf_preserves_title_and_row_classes_in_pdf_template(client: Client) -> None:
    response = client.get(reverse("reports:report-pdf", kwargs={"number": 1}), data={"date_filter": "last_week"})

    assert response.status_code == 200
    assert response["Content-Disposition"].endswith('filename="Weekly Sales Report: last week.pdf"')
    assert b"%PDF" in response.content[:16]
    html_response = client.get(reverse("reports:report-number", kwargs={"number": 1}), data={"date_filter": "last_week"})
    html = html_response.content.decode()
    assert 'download="Weekly Sales Report: last week.pdf"' in html
    assert "report-week-row-latest" in html or "report-summary-row" in html


def _build_pdf(lines: list[str]) -> bytes:
    return _build_weekly_sales_pdf(lines)
