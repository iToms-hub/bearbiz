from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.models import ReviewTemplate
from apps.reports.views import _dashboard_segment_rows


ROOT = Path(__file__).parents[1]


def test_review_segments_highlight_best_latest_week_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"row_kind": "manager", "summary": SimpleNamespace(pk=1, fiscal_year=2026, fiscal_week=30), "week": "30", "date": "08/02/26", "metrics": {"success_segments": 9, "success_pct": 90, "store_sales": 2000, "sales_trans": 20, "conversion": 30, "dpt": 4, "upt": 2}},
        {"row_kind": "manager", "summary": SimpleNamespace(pk=2, fiscal_year=2026, fiscal_week=31), "week": "31", "date": "08/09/26", "metrics": {"success_segments": 2, "success_pct": 50, "store_sales": 1000, "sales_trans": 10, "conversion": 20, "dpt": 3, "upt": 1.2}},
        {"row_kind": "manager", "summary": SimpleNamespace(pk=2, fiscal_year=2026, fiscal_week=31), "week": "31", "date": "08/09/26", "metrics": {"success_segments": 3, "success_pct": 60, "store_sales": 1200, "sales_trans": 12, "conversion": 18, "dpt": 3.5, "upt": 1.2}},
        {"row_kind": "store_total", "metrics": {"success_pct": 99, "conversion": 99, "dpt": 99, "upt": 99}},
    ]
    monkeypatch.setattr("apps.reports.views._segments_report_rows", lambda summaries: rows)

    highlighted = _dashboard_segment_rows([])

    assert highlighted[0]["highlight_success"] is True
    assert highlighted[1]["highlight_success"] is False
    assert highlighted[2]["highlight_success"] is True
    assert highlighted[2]["highlight_success_segments"] is True
    assert highlighted[2]["highlight_store_sales"] is True
    assert highlighted[2]["highlight_sales_trans"] is True
    assert highlighted[1]["highlight_conversion"] is True
    assert highlighted[2]["highlight_conversion"] is False
    assert highlighted[2]["highlight_dpt"] is True
    assert highlighted[1]["highlight_upt"] is True
    assert highlighted[2]["highlight_upt"] is True


@pytest.mark.django_db()
def test_templates_settings_can_create_save_load_and_delete_template() -> None:
    client = Client()
    page = client.get(reverse("settings:templates"))
    assert page.status_code == 200
    assert getattr(page, "cookies", {}).get("bearbiz_csrftoken") is not None
    created = client.post(reverse("settings:templates"), {"action": "create", "name": "Weekly Review"})
    assert created.status_code == 200
    html = created.content.decode()
    assert "Review templates" in html
    assert "Last Weeks Bonus Club &amp; Gift Cards" in html
    assert "Weekly Sales Trend" in html
    assert "template-module-library" in html
    assert "template-mock-page" in html
    assert "template-move-button" in html
    assert 'data-move-module="up"' in html
    assert 'data-move-module="down"' in html
    assert 'name="action" value="delete"' in html
    assert "template-delete-button" in html
    assert "template-card-actions" in html
    rendered_dropzone = html.split("data-dropzone>", 1)[1].split("</section>", 1)[0]
    assert rendered_dropzone.count('<article class="template-layout-module"') == 8

    template = ReviewTemplate.objects.get(name="Weekly Review")
    layout = [{"type": "notes", "title": "Notes", "text": "Manager notes"}, {"type": "rankings", "title": "Rankings · Last 5 Weeks"}]
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_page = csrf_client.get(reverse("settings:templates"), {"template": template.pk})
    csrf_token = getattr(csrf_page, "cookies")["bearbiz_csrftoken"].value
    csrf_saved = csrf_client.post(reverse("settings:templates"), {
        "action": "save", "template_id": str(template.pk), "name": "Weekly Review", "subtitle": "",
        "layout": json.dumps(layout), "csrfmiddlewaretoken": csrf_token,
    })
    assert getattr(csrf_saved, "status_code") == 200
    saved = client.post(reverse("settings:templates"), {
        "action": "save", "template_id": str(template.pk), "name": "Weekly Review Updated", "subtitle": "Leadership review · Week 7", "layout": json.dumps(layout),
    })
    assert saved.status_code == 200
    template.refresh_from_db()
    assert template.name == "Weekly Review Updated"
    assert template.subtitle == "Leadership review · Week 7"
    assert [item["type"] for item in template.layout] == ["notes", "rankings"]

    review = client.get(reverse("dashboard-review"), {"template": template.pk})
    assert review.status_code == 200
    review_html = review.content.decode()
    assert "Weekly Review Updated" in review_html
    assert review_html.index("Manager notes") < review_html.index("Rankings · Last 5 Weeks")

    saved_note = client.post(reverse("dashboard-review"), {
        "action": "save-note", "template_id": str(template.pk), "module_index": "0",
        "note_title": "One-off business note", "note_text": "<p>Follow up on staffing next week.</p><ul><li>Review coverage</li></ul><script>alert('bad')</script>",
    })
    assert saved_note.status_code == 302
    template.refresh_from_db()
    assert template.layout[0]["title"] == "One-off business note"
    assert template.layout[0]["text"] == "<p>Follow up on staffing next week.</p><ul><li>Review coverage</li></ul>alert(&#x27;bad&#x27;)"
    saved_review_html = client.get(reverse("dashboard-review"), {"template": template.pk}).content.decode()
    assert "One-off business note" in saved_review_html
    assert "Follow up on staffing next week." in saved_review_html

    pdf = client.get(reverse("dashboard-review-pdf"), {"template": template.pk})
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"
    assert pdf["Content-Disposition"] == 'attachment; filename="Last Week Review.pdf"'
    assert pdf.content.startswith(b"%PDF")

    fitz = pytest.importorskip("fitz")
    pdf_text = "\n".join(page.get_text() for page in fitz.open(stream=pdf.content, filetype="pdf"))
    assert "Store 214 Review: Week " in pdf_text
    assert "Last Weeks Performance Review" in pdf_text
    assert "Weekly Review Updated" not in pdf_text
    assert "For internal use only" in pdf_text
    assert "Manager Sign Off" in pdf_text
    assert "Reviewed by manager initials:" not in pdf_text
    assert "Review date:" not in pdf_text
    assert "Page 2 of 2" in pdf_text
    pdf_template = (ROOT / "templates/reports/dashboard_review_pdf.html").read_text()
    assert "td.review-above-store" in pdf_template
    assert "tbody tr.report-week-row-latest" in pdf_template
    assert "tbody tr.report-ranking-row-latest" in pdf_template
    assert "td.review-best-performance" in pdf_template
    assert "Goal: Club % 80%" in pdf_template
    assert "Goal: GC% 18%" in pdf_template
    assert "Fiscal Year {{ module.latest_year }}, Week {{ module.latest_week }}" not in pdf_template
    assert "class=\"sign-off-page\"" in pdf_template
    assert pdf_template.count('class="sign-off-line"') == 4

    deleted = client.post(reverse("settings:templates"), {"action": "delete", "template_id": str(template.pk)})
    assert deleted.status_code == 200
    assert not ReviewTemplate.objects.filter(pk=template.pk).exists()


@pytest.mark.django_db()
def test_template_module_buttons_have_server_side_fallback() -> None:
    template = ReviewTemplate.objects.create(
        name="Button fallback",
        layout=[
            {"type": "product-top-10", "title": "Product"},
            {"type": "payroll", "title": "Payroll"},
            {"type": "notes", "title": "Notes"},
        ],
    )
    client = Client()
    url = reverse("settings:templates")

    def post(layout: list[dict[str, object]], module_action: str):
        return client.post(url, {
            "action": "save", "template_id": str(template.pk), "name": template.name,
            "subtitle": "", "layout": json.dumps(layout), "module_action": module_action,
        })

    post(template.layout, "down:0")
    template.refresh_from_db()
    assert [item["type"] for item in template.layout] == ["payroll", "product-top-10", "notes"]

    post(template.layout, "toggle:1")
    template.refresh_from_db()
    assert template.layout[1]["enabled"] is False

    post(template.layout, "remove:1")
    template.refresh_from_db()
    assert [item["type"] for item in template.layout] == ["payroll", "notes"]
