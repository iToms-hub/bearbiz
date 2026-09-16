from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.models import ReviewTemplate


ROOT = Path(__file__).parents[1]


@pytest.mark.django_db()
def test_templates_settings_can_create_save_load_and_delete_template() -> None:
    client = Client()
    page = client.get(reverse("settings:templates"))
    assert page.status_code == 200
    created = client.post(reverse("settings:templates"), {"action": "create", "name": "Weekly Review"})
    assert created.status_code == 200
    html = created.content.decode()
    assert "Review templates" in html
    assert "Bonus Club &amp; Gift Cards" in html
    assert "Weekly Sales Trend" in html
    assert "template-module-library" in html
    assert "template-mock-page" in html

    template = ReviewTemplate.objects.get(name="Weekly Review")
    layout = [{"type": "notes", "title": "Notes", "text": "Manager notes"}, {"type": "rankings", "title": "Rankings · Last 5 Weeks"}]
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
    assert "Page 1 of" in pdf_text
    pdf_template = (ROOT / "templates/reports/dashboard_review_pdf.html").read_text()
    assert "td.review-above-store" in pdf_template
    assert ".payroll-metric { display: table-cell; width: 25%" in pdf_template

    deleted = client.post(reverse("settings:templates"), {"action": "delete", "template_id": str(template.pk)})
    assert deleted.status_code == 200
    assert not ReviewTemplate.objects.filter(pk=template.pk).exists()
