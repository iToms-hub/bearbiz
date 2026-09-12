from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse

from apps.reports.models import BonusClubSummary, GiftCardsSummary, ReportUpload, SegmentsSummary
from apps.reports.views import _normalize_person_name, _performance_chart_series, _performance_chart_svg


@pytest.fixture()
def client() -> Client:
    return Client()


def _upload(name: str, report_type: str) -> ReportUpload:
    return ReportUpload.objects.create(
        source_file=SimpleUploadedFile(name, b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
        source_name=name,
        report_type=report_type,
        parse_status="parsed",
    )


def _gift_payload(total: int, bonus: int, name: str = "Avery Bear") -> dict[str, object]:
    return {
        "parse_version": 1,
        "associate_rows": [{"associate_number": "1234567", "name": name, "metrics": {"total_transactions": total, "gc_bonus_transactions": bonus, "bonus_percent": bonus / total * 100}}],
        "store_total": {"metrics": {}},
        "fiscal": {"week_ending_date": "2026-08-09"},
    }


def _bonus_payload(total: int, club: int, name: str = "Avery Bear") -> dict[str, object]:
    return {
        "parse_version": 1,
        "associate_rows": [{"associate_number": "1234567", "name": name, "metrics": {"total_transactions": total, "transactions_with_club": club, "capture_rate": club / total * 100}}],
        "store_total": {"metrics": {}},
        "fiscal": {"week_ending_date": "2026-08-09"},
    }


@pytest.mark.django_db()
def test_performance_associates_combines_reports_filters_range_and_renders_chart(client: Client, tmp_path: Path) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        gift_upload = _upload("gift.pdf", "gift_cards")
        GiftCardsSummary.objects.create(report_upload=gift_upload, fiscal_year=2026, fiscal_week=31, fiscal_period_end=date(2026, 8, 9), raw_json=_gift_payload(100, 20))
        bonus_upload = _upload("bonus.pdf", "bonus_club")
        BonusClubSummary.objects.create(report_upload=bonus_upload, fiscal_year=2026, fiscal_week=31, fiscal_period_end=date(2026, 8, 9), raw_json=_bonus_payload(80, 32))

        response = client.get(reverse("performance"), {"date_filter": "range", "range_start": "2026-08-01", "range_end": "2026-08-10"})

    assert response.status_code == 200
    html = response.content.decode()
    assert "Performance" in html
    assert "Associates" in html
    assert "Last week" in html
    assert "Avery Bear" in html
    assert "Bonus Club + Gift Cards" in html
    assert "100" in html and "80" in html
    assert "Total" in html and "Average" in html
    combined = html[html.index("data-performance-combined"):]
    assert 'aria-label="Bonus Club and Gift Cards summary"' not in combined
    assert combined.index("Bonus Club") < combined.index("Gift Cards")
    assert combined.index("Total") < combined.index("Average") < combined.index("Trend")
    assert '<tr class="report-summary-row report-summary-trend"><td>Trend</td>' in combined
    assert "Associate performance trend line graph" in html
    assert "Gift Card Bonus %" in html
    assert "Bonus Club Capture %" in html
    assert "Weekly percentage performance across the selected timeframe." not in html
    assert 'class="chart-y-label"' in html
    assert '<g class="chart-legend" aria-label="Chart legend">' in html
    assert 'y="14"' not in html
    assert "Store tab" not in html


@pytest.mark.django_db()
def test_performance_shows_segment_not_listed_state_for_selected_associate(client: Client, tmp_path: Path) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        gift_upload = _upload("gift.pdf", "gift_cards")
        GiftCardsSummary.objects.create(report_upload=gift_upload, fiscal_year=2026, fiscal_week=31, fiscal_period_end=date(2026, 8, 9), raw_json=_gift_payload(100, 20, "Avery Bear"))
        bonus_upload = _upload("bonus.pdf", "bonus_club")
        BonusClubSummary.objects.create(report_upload=bonus_upload, fiscal_year=2026, fiscal_week=31, fiscal_period_end=date(2026, 8, 9), raw_json=_bonus_payload(80, 32, "Avery Bear"))
        segment_upload = _upload("segments.pdf", "segments")
        SegmentsSummary.objects.create(
            report_upload=segment_upload,
            fiscal_year=2026,
            fiscal_week=31,
            fiscal_period_end=date(2026, 8, 9),
            raw_json={"parse_version": 2, "manager_rows": [{"name": "Someone Else", "metrics": {"success_pct": 50}}], "store_total": {}},
        )

        html = client.get(reverse("performance")).content.decode()

    assert "<h2>Segment Accountability</h2>" not in html
    assert "Store tab" not in html


@pytest.mark.django_db()
def test_performance_places_segment_before_summary_and_shows_range_trends(client: Client, tmp_path: Path) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        gift_upload = _upload("gift.pdf", "gift_cards")
        GiftCardsSummary.objects.create(report_upload=gift_upload, fiscal_year=2026, fiscal_week=30, fiscal_period_end=date(2026, 8, 2), raw_json=_gift_payload(90, 9))
        gift_upload_latest = _upload("gift-latest.pdf", "gift_cards")
        GiftCardsSummary.objects.create(report_upload=gift_upload_latest, fiscal_year=2026, fiscal_week=31, fiscal_period_end=date(2026, 8, 9), raw_json=_gift_payload(100, 20))
        bonus_upload = _upload("bonus.pdf", "bonus_club")
        BonusClubSummary.objects.create(report_upload=bonus_upload, fiscal_year=2026, fiscal_week=30, fiscal_period_end=date(2026, 8, 2), raw_json=_bonus_payload(80, 16))
        bonus_upload_latest = _upload("bonus-latest.pdf", "bonus_club")
        BonusClubSummary.objects.create(report_upload=bonus_upload_latest, fiscal_year=2026, fiscal_week=31, fiscal_period_end=date(2026, 8, 9), raw_json=_bonus_payload(80, 32))
        segment_upload = _upload("segments.pdf", "segments")
        SegmentsSummary.objects.create(report_upload=segment_upload, fiscal_year=2026, fiscal_week=31, fiscal_period_end=date(2026, 8, 9), raw_json={"manager_rows": [{"name": "Avery Bear", "metrics": {"success_pct": 50}}], "store_total": {}})

        html = client.get(reverse("performance"), {"date_filter": "range", "range_start": "2026-08-01", "range_end": "2026-08-10"}).content.decode()

    assert html.index("Segment Accountability") < html.index("data-performance-combined")
    assert "↑ 10.00 pts" in html
    assert "↑ 20.00 pts" in html


@pytest.mark.django_db()
def test_performance_matches_segment_name_case_and_whitespace_for_selected_dates(client: Client, tmp_path: Path) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        gift_upload = _upload("gift.pdf", "gift_cards")
        GiftCardsSummary.objects.create(
            report_upload=gift_upload, fiscal_year=2026, fiscal_week=31,
            fiscal_period_end=date(2026, 8, 9), raw_json=_gift_payload(100, 20, "Avery Bear"),
        )
        segment_upload = _upload("segments.pdf", "segments")
        SegmentsSummary.objects.create(
            report_upload=segment_upload, fiscal_year=2026, fiscal_week=31,
            fiscal_period_end=date(2026, 8, 9),
            raw_json={"parse_version": 2, "manager_rows": [{"name": "  aVERY   bEAR ", "metrics": {"success_pct": 50}}], "store_total": {}},
        )

        response = client.get(reverse("performance"), {"date_filter": "range", "range_start": "2026-08-09", "range_end": "2026-08-09"})
        html = response.content.decode()

    assert "<h2>Segment Accountability</h2>" in html
    assert "50%" in html


@pytest.mark.django_db()
def test_performance_matches_reordered_segment_name_forms(client: Client, tmp_path: Path) -> None:
    assert _normalize_person_name("Elofson, Tom") == _normalize_person_name("Tom Elofson")
    with override_settings(MEDIA_ROOT=tmp_path):
        gift_upload = _upload("gift.pdf", "gift_cards")
        GiftCardsSummary.objects.create(
            report_upload=gift_upload, fiscal_year=2026, fiscal_week=31,
            fiscal_period_end=date(2026, 8, 9), raw_json=_gift_payload(100, 20, "Elofson, Tom"),
        )
        segment_upload = _upload("segments.pdf", "segments")
        SegmentsSummary.objects.create(
            report_upload=segment_upload, fiscal_year=2026, fiscal_week=31,
            fiscal_period_end=date(2026, 8, 9),
            raw_json={"parse_version": 2, "manager_rows": [{"name": "Tom Elofson", "metrics": {"success_pct": 50}}], "store_total": {}},
        )

        html = client.get(reverse("performance"), {"date_filter": "range", "range_start": "2026-08-09", "range_end": "2026-08-09"}).content.decode()

    assert "<h2>Segment Accountability</h2>" in html
    assert "50%" in html


@pytest.mark.django_db()
def test_performance_does_not_merge_different_segment_names(client: Client, tmp_path: Path) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        gift_upload = _upload("gift.pdf", "gift_cards")
        GiftCardsSummary.objects.create(
            report_upload=gift_upload, fiscal_year=2026, fiscal_week=31,
            fiscal_period_end=date(2026, 8, 9), raw_json=_gift_payload(100, 20, "Elofson, Tom"),
        )
        segment_upload = _upload("segments.pdf", "segments")
        SegmentsSummary.objects.create(
            report_upload=segment_upload, fiscal_year=2026, fiscal_week=31,
            fiscal_period_end=date(2026, 8, 9),
            raw_json={"manager_rows": [{"name": "Tom Ellofson", "metrics": {"success_pct": 50}}], "store_total": {}},
        )

        html = client.get(reverse("performance"), {"date_filter": "range", "range_start": "2026-08-09", "range_end": "2026-08-09"}).content.decode()

    assert "<h2>Segment Accountability</h2>" not in html


def test_performance_filter_uses_compact_responsive_layout_markup() -> None:
    template_root = Path(__file__).parents[1] / "templates"
    assert "performance-filter-grid" in (template_root / "performance" / "associates.html").read_text()
    assert "performance-filter-form" in (template_root / "base.html").read_text()


@pytest.mark.django_db()
def test_performance_does_not_render_inactive_associates_top_pill(client: Client, tmp_path: Path) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        html = client.get(reverse("performance")).content.decode()

    assert '<nav class="section-tabs" aria-label="Section tabs">' not in html
    assert '<span class="tab active" aria-current="page">Associates</span>' not in html


def test_performance_chart_uses_tight_bottom_spacing() -> None:
    svg = _performance_chart_svg([{"label": "Gift Card Bonus %", "points": [20]}, {"labels": ["08/09/26"]}])

    assert 'viewBox="0 0 720 280"' in svg
    assert 'y="258"' in svg


def test_performance_pdf_uses_compact_heading_sizes_and_short_dates() -> None:
    template = (Path(__file__).parents[1] / "templates" / "performance" / "associates_pdf.html").read_text()

    assert "h1 { color: #123b66; font-size: 15pt;" in template
    assert "h2 { color: #123b66; font-size: 10pt;" in template


def test_performance_apply_and_pdf_actions_share_exact_button_sizing() -> None:
    template_root = Path(__file__).parents[1] / "templates"
    markup = (template_root / "performance" / "associates.html").read_text()
    styles = (template_root / "base.html").read_text()

    assert '<button type="submit" class="performance-filter-action">Apply</button>' in markup
    assert 'class="page-action pdf-action performance-pdf-action performance-filter-action"' in markup
    assert ".performance-filter-action" in styles
    assert "width: 4.25rem" in styles
    assert "height: 2.15rem" in styles
    assert "padding: 0.55rem 0.9rem" in styles
    assert "font-size: 1rem" in styles
    assert "border-radius: 999px" in styles


@pytest.mark.django_db()
def test_performance_trend_uses_selected_rates_and_first_week_store_series(client: Client, tmp_path: Path) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        gift_upload = _upload("gift.pdf", "gift_cards")
        GiftCardsSummary.objects.create(
            report_upload=gift_upload, fiscal_year=2026, fiscal_week=30, fiscal_period_end=date(2026, 8, 2),
            raw_json={**_gift_payload(100, 10), "store_total": {"metrics": {"bonus_percent": 15}}},
        )
        gift_upload_latest = _upload("gift-latest.pdf", "gift_cards")
        GiftCardsSummary.objects.create(
            report_upload=gift_upload_latest, fiscal_year=2026, fiscal_week=31, fiscal_period_end=date(2026, 8, 9),
            raw_json={**_gift_payload(100, 30), "store_total": {"metrics": {"bonus_percent": 25}}},
        )
        bonus_upload = _upload("bonus.pdf", "bonus_club")
        BonusClubSummary.objects.create(
            report_upload=bonus_upload, fiscal_year=2026, fiscal_week=30, fiscal_period_end=date(2026, 8, 2),
            raw_json={**_bonus_payload(100, 20), "store_total": {"metrics": {"capture_rate": 25}}},
        )
        bonus_upload_latest = _upload("bonus-latest.pdf", "bonus_club")
        BonusClubSummary.objects.create(
            report_upload=bonus_upload_latest, fiscal_year=2026, fiscal_week=31, fiscal_period_end=date(2026, 8, 9),
            raw_json={**_bonus_payload(100, 40), "store_total": {"metrics": {"capture_rate": 35}}},
        )

        html = client.get(reverse("performance"), {"date_filter": "range", "range_start": "2026-08-01", "range_end": "2026-08-10"}).content.decode()

    assert "<th>Summary</th>" not in html
    assert "↑ 20.00 pts" in html
    assert 'points="52.0,195.0 692.0,157.0"' in html
    assert "08/02/26" in html and "08/09/26" in html
    assert "08/01/26 – 08/10/26" in html
    assert 'data-series-label="Store Gift Card Bonus %"' in html
    assert 'data-series-label="Store Bonus Club Capture %"' in html
    assert 'stroke="#dc2626"' in html


@pytest.mark.django_db()
def test_performance_omits_store_series_when_store_metrics_are_unavailable(tmp_path: Path) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        gift_upload = _upload("gift.pdf", "gift_cards")
        gift = GiftCardsSummary.objects.create(report_upload=gift_upload, fiscal_year=2026, fiscal_week=31, fiscal_period_end=date(2026, 8, 9), raw_json=_gift_payload(100, 20))
        series = _performance_chart_series([gift], [], [], "1234567", "Avery Bear")

    assert not any(str(item.get("label", "")).startswith("Store ") for item in series)


def test_performance_chart_uses_compact_legend_and_color_matched_point_labels() -> None:
    svg = _performance_chart_svg([
        {"label": "Gift Card Bonus %", "points": [20, None, 80]},
        {"label": "Store Gift Card Bonus %", "points": [50, 60, None]},
        {"labels": ["08/02", "08/09", "08/16"]},
    ])

    assert 'class="chart-legend-item" font-size="8"' in svg
    assert '<text' in svg and 'class="chart-point-label"' in svg
    assert '<text x="52.0" y="' in svg and '>20%</text>' in svg
    assert '>80%</text>' in svg
    assert '>50%</text>' in svg and '>60%</text>' in svg
    assert 'class="chart-point-label" font-size="9" fill="#5b7cfa"' in svg
    assert 'class="chart-point-label" font-size="9" fill="#dc2626"' in svg
    assert svg.count('class="chart-point-label"') == 4


def test_performance_chart_consolidates_store_legend_and_keeps_desktop_items_on_one_row() -> None:
    svg = _performance_chart_svg([
        {"label": "Gift Card Bonus %", "points": [20]},
        {"label": "Bonus Club Capture %", "points": [30]},
        {"label": "Store Gift Card Bonus %", "points": [50]},
        {"label": "Store Bonus Club Capture %", "points": [60]},
        {"labels": ["08/09"]},
    ])

    legend = svg[svg.index('<g class="chart-legend"'):svg.index("</g>", svg.index('<g class="chart-legend"'))]
    assert legend.count("Store Performance") == 1
    assert "Store Gift Card Bonus %" not in legend
    assert "Store Bonus Club Capture %" not in legend
    assert legend.count('class="chart-legend-item"') == 3
    assert legend.count('y="258"') == 3


@pytest.mark.django_db()
def test_performance_pdf_preserves_selection_and_is_portrait(client: Client, tmp_path: Path) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        gift_upload = _upload("gift.pdf", "gift_cards")
        GiftCardsSummary.objects.create(
            report_upload=gift_upload, fiscal_year=2026, fiscal_week=31,
            fiscal_period_end=date(2026, 8, 9), raw_json=_gift_payload(100, 20),
        )
        bonus_upload = _upload("bonus.pdf", "bonus_club")
        BonusClubSummary.objects.create(
            report_upload=bonus_upload, fiscal_year=2026, fiscal_week=31,
            fiscal_period_end=date(2026, 8, 9), raw_json=_bonus_payload(80, 32),
        )
        query = {"associate": "1234567", "date_filter": "range", "range_start": "2026-08-01", "range_end": "2026-08-10"}
        response = client.get(reverse("performance-pdf"), query)
        page = client.get(reverse("performance"), query).content.decode()

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"].startswith('attachment; filename="Performance Associates: Avery Bear -')
    assert response.content.startswith(b"%PDF-")
    assert "performance/pdf/?associate=1234567" in page
    toolbar = page[page.index('<form method="get" class="performance-filter-form'):]
    assert toolbar.index(">Apply<") < toolbar.index("performance-pdf-action")
    assert '<div class="performance-filter-actions">' in toolbar
    assert toolbar.count("performance-pdf-action") == 1

    template = Path(__file__).parents[1] / "templates" / "performance" / "associates_pdf.html"
    template_text = template.read_text()
    assert "size: Letter portrait;" in template_text
    assert "position: fixed;" in template_text
    assert "class=\"pdf-footer\"" in template_text
    assert "class=\"pdf-footer-table\"" in template_text
    assert 'alt="BEARbiZ banner logo"' in template_text
    assert "© BEARbiZ 2026" in template_text
    assert "For internal use only" in template_text
    assert "report_pdf_logo_url" in template_text
    assert ".pdf-footer-table td { width: 33.333%;" in template_text
    assert '<td class="pdf-footer-left"><img src="{{ report_pdf_logo_url }}" alt="BEARbiZ banner logo"></td>' in template_text
    assert '<td class="pdf-footer-center">© BEARbiZ 2026 | For internal use only</td>' in template_text

    fitz = pytest.importorskip("fitz")
    document = fitz.open(stream=response.content, filetype="pdf")
    assert document.page_count >= 1
    assert all((page.rect.width, page.rect.height) == (612, 792) for page in document)
    pdf_text = "\n".join(str(pdf_page.get_text()) for pdf_page in document)
    assert "Bonus Club + Gift Cards" in pdf_text
    assert "Week ending" in pdf_text
    assert "Club capture %" in pdf_text
    assert "Performance trend" in pdf_text
    assert "Avery Bear" in pdf_text
    assert "08/01/26" in pdf_text
    assert "08/09/26" in pdf_text
    assert "© BEARbiZ 2026" in pdf_text
    assert "For internal use only" in pdf_text
    assert "© BEARbiZ 2026 | For internal use only" in pdf_text.replace("\n", " ")
    assert "Page 1 of 1" in pdf_text
    page_images = [page.get_images(full=True) for page in document]
    assert all(page_images)
    assert any(width / height == pytest.approx(1559 / 941, rel=0.02) for images in page_images for _, _, width, height, *_ in images)
    assert "BEARbiZ banner logo" not in pdf_text


@pytest.mark.django_db()
def test_gift_cards_multi_week_range_renders_one_combined_associate_result(client: Client, tmp_path: Path) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        for week, period_end, total, bonus in [
            (30, date(2026, 8, 2), 100, 10),
            (31, date(2026, 8, 9), 200, 80),
        ]:
            upload = _upload(f"gift-{week}.pdf", "gift_cards")
            GiftCardsSummary.objects.create(
                report_upload=upload, fiscal_year=2026, fiscal_week=week,
                fiscal_period_end=period_end, raw_json={**_gift_payload(total, bonus), "weekly_sales_dpt": 0},
            )
        html = client.get(reverse("reports:report-number", kwargs={"number": 4}), {
            "date_filter": "range", "range_start": "2026-08-01", "range_end": "2026-08-10",
            "associate": "1234567",
        }).content.decode()

    assert "300" in html and "90" in html and "30%" in html
    assert "08/02/26" not in html and "08/09/26" not in html
    assert "Showing totals for 08/01/26–08/10/26" in html


@pytest.mark.django_db()
def test_bonus_club_single_week_range_keeps_exact_week_row(client: Client, tmp_path: Path) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        upload = _upload("bonus.pdf", "bonus_club")
        BonusClubSummary.objects.create(
            report_upload=upload, fiscal_year=2026, fiscal_week=31,
            fiscal_period_end=date(2026, 8, 9), raw_json=_bonus_payload(80, 32),
        )
        html = client.get(reverse("reports:report-number", kwargs={"number": 5}), {
            "date_filter": "range", "range_start": "2026-08-09", "range_end": "2026-08-09",
            "associate": "1234567",
        }).content.decode()

    assert "08/09/26" in html and "80" in html and "32" in html and "40%" in html
    assert "Showing totals for 08/09/26" in html
