from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse

from apps.core.models import AIIntegrationSettings
from apps.reports.models import ReportUpload, WeeklySalesSummary


@pytest.fixture()
def client() -> Client:
    return Client()


@pytest.mark.django_db()
def test_agent_page_and_chat_use_bearbiz_data(client: Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    AIIntegrationSettings.objects.create(enabled=True, api_key="", provider_name="openai-compatible", model_name="gpt-4o-mini")

    with override_settings(MEDIA_ROOT=media_root):
        upload = ReportUpload.objects.create(
            source_file=SimpleUploadedFile("week-1-sales.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
            source_name="week-1-sales.pdf",
            parse_status="parsed",
        )
        WeeklySalesSummary.objects.create(
            report_upload=upload,
            fiscal_year=2026,
            fiscal_week=1,
            fiscal_period_end=date(2026, 2, 7),
            raw_json={
                "fiscal": {
                    "fiscal_year": 2026,
                    "fiscal_week_number": 1,
                    "week_ending_date": "2026-02-07",
                },
                "summary_kpis": {
                    "total_sales": 20366,
                    "ly_total_sales": 23198,
                    "target_total_sales": 23800,
                    "traffic": 2207,
                    "conversion_rate": 18.6,
                    "sales_trans": 410,
                },
                "summary_rows": [],
            },
            ai_summary="AI summary from the weekly report.",
        )

    captured: dict[str, object] = {}

    def fake_post_json(url: str, payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        captured["url"] = url
        captured["payload"] = payload
        captured["api_key"] = api_key
        return {"choices": [{"message": {"content": "The latest weekly sales trend is healthy."}}]}

    monkeypatch.setattr("apps.core.ai._post_json", fake_post_json)

    response = client.get(reverse("agent:index"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "Agent" in html
    assert "Ask Bearbiz anything" in html
    assert "AI connected" in html
    assert "event.key === 'Enter'" in html
    assert "requestSubmit()" in html

    chat_response = client.post(
        reverse("agent:index"),
        data=json.dumps({"message": "What is the latest sales trend?"}),
        content_type="application/json",
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["ok"] is True
    assert payload["reply"] == "The latest weekly sales trend is healthy."
    assert payload["context_summary"]["report_count"] == 1

    assert str(captured["url"]).endswith("/chat/completions")
    body = captured["payload"]
    assert isinstance(body, dict)
    messages = body["messages"]
    assert isinstance(messages, list)
    assert "Bearbiz data context" in messages[0]["content"]
    assert "20366" in messages[0]["content"]
    assert "week-1-sales.pdf" in messages[0]["content"]
    assert messages[-1]["content"] == "What is the latest sales trend?"

    followup_response = client.get(reverse("agent:index"))
    followup_html = followup_response.content.decode()
    assert "What is the latest sales trend?" in followup_html
    assert "The latest weekly sales trend is healthy." in followup_html
