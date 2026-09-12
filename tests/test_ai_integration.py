from __future__ import annotations

from pathlib import Path
import io
import json
from email.message import Message
from datetime import date
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings

from apps.core.ai import AIAnalysisResult, CHAT_DATA_CONTEXT_MAX_CHARS, build_bearbiz_chat_context
from apps.core.forms import AIIntegrationSettingsForm
from apps.core.models import AIIntegrationSettings
from apps.reports.models import BonusClubSummary, GiftCardsSummary, RankingSummary, ReportUpload, SegmentsSummary, WeeklySalesSummary
from apps.reports.views import _parse_and_store_summary


@pytest.mark.django_db
def test_ai_settings_page_renders(client) -> None:
    response = client.get("/settings/ai/")

    assert response.status_code == 200
    assert b"AI integration" in response.content
    assert b"API key (optional)" in response.content
    assert b'placeholder="https://api.openai.com/v1"' in response.content
    assert b"Test connection" in response.content
    assert b"leave blank" in response.content
    assert b"Chat completions path" not in response.content
    assert b"Report summary prompt" not in response.content
    assert b"System prompt" not in response.content
    assert b"Current AI configuration" not in response.content


@pytest.mark.django_db
def test_ai_model_suggestions_and_connection_test_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.core.views.fetch_ai_model_suggestions",
        lambda source=None: ["gpt-4o-mini", "gpt-4.1"],
    )
    monkeypatch.setattr(
        "apps.core.views.probe_ai_endpoint",
        lambda source=None: __import__("apps.core.ai", fromlist=["AIEndpointProbeResult"]).AIEndpointProbeResult(
            ok=True,
            message="Connected to openai-compatible and found 2 model(s).",
            models=("gpt-4o-mini", "gpt-4.1"),
            payload={"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4.1"}]},
            provider="openai-compatible",
            base_url="https://api.openai.com/v1",
        ),
    )

    client = Client()
    models_response = client.get("/settings/ai/models/")
    assert models_response.status_code == 200
    assert models_response.json() == {"ok": True, "models": ["gpt-4o-mini", "gpt-4.1"]}

    test_response = client.post("/settings/ai/test/", data={})
    assert test_response.status_code == 200
    payload = test_response.json()
    assert payload["ok"] is True
    assert payload["provider"] == "openai-compatible"
    assert payload["model_suggestions"] == ["gpt-4o-mini", "gpt-4.1"]

    page = client.post("/settings/ai/", data={"action": "test"})
    assert page.status_code == 200
    assert b"Test connection" in page.content
    assert b"success" in page.content


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/bearbiz-test-media")
def test_report_upload_persists_ai_summary(monkeypatch) -> None:
    upload = ReportUpload.objects.create(
        source_file=SimpleUploadedFile("weekly-sales.pdf", b"%PDF-1.4 fake pdf"),
        source_name="weekly-sales.pdf",
    )
    fake_report = SimpleNamespace(
        payload={
            "fiscal": {"fiscal_year": 2026, "fiscal_week_number": 1},
            "summary_kpis": {"net_sales": 20366},
            "summary_rows": [],
        },
        period_start="2026-02-01",
        period_end="2026-02-07",
    )

    monkeypatch.setattr("apps.reports.views._extract_pdf_text", lambda path: "fake extracted text")
    monkeypatch.setattr("apps.reports.views.get", lambda slug: SimpleNamespace(parse=lambda raw: fake_report))
    monkeypatch.setattr(
        "apps.reports.views.summarize_weekly_sales_report",
        lambda *args, **kwargs: AIAnalysisResult(
            enabled=True,
            provider="openai-compatible",
            model="gpt-4o-mini",
            summary="AI summary for the store manager.",
            payload={"choices": [{"message": {"content": "AI summary for the store manager."}}]},
        ),
    )

    _parse_and_store_summary(upload)

    summary = WeeklySalesSummary.objects.get(report_upload=upload)
    assert summary.ai_summary == "AI summary for the store manager."
    assert summary.ai_model == "gpt-4o-mini"
    assert summary.ai_provider == "openai-compatible"
    assert summary.ai_error == ""
    assert summary.ai_generated_at is not None


@pytest.mark.django_db
def test_report_upload_uses_no_auth_when_api_key_blank(monkeypatch) -> None:
    settings = AIIntegrationSettings.objects.create(
        enabled=True,
        api_key="",
        provider_name="openai-compatible",
        api_base_url="http://lms.itoms.org/v1",
        model_name="local-model",
    )
    captured: dict[str, object] = {}

    def fake_post_json(url, payload, *, api_key):
        captured["url"] = url
        captured["api_key"] = api_key
        return {"choices": [{"message": {"content": "Local summary"}}]}

    monkeypatch.setattr("apps.core.ai._post_json", fake_post_json)

    result = __import__("apps.core.ai", fromlist=["summarize_weekly_sales_report"]).summarize_weekly_sales_report(
        {"summary_kpis": {"net_sales": 1}, "summary_rows": []},
        source_name="weekly-sales.pdf",
        raw_text="Sample text",
        settings=settings,
    )

    assert result.ok is True
    assert result.summary == "Local summary"
    assert captured["api_key"] == ""
    assert str(captured["url"]).endswith("/chat/completions")


@pytest.mark.django_db
def test_configured_api_key_is_sent_without_being_rendered_or_returned(monkeypatch) -> None:
    secret = "test-only-secret"
    settings = AIIntegrationSettings.objects.create(
        enabled=True,
        api_key=secret,
        api_base_url="http://lms.itoms.org/v1",
        model_name="local-model",
    )
    captured: dict[str, object] = {}

    def fake_post_json(url, payload, *, api_key):
        captured["api_key"] = api_key
        return {"choices": [{"message": {"content": "Local summary"}}]}

    monkeypatch.setattr("apps.core.ai._post_json", fake_post_json)
    result = __import__("apps.core.ai", fromlist=["summarize_weekly_sales_report"]).summarize_weekly_sales_report(
        {"summary_kpis": {}, "summary_rows": []}, settings=settings
    )

    assert result.ok is True
    assert captured["api_key"] == secret
    assert secret not in result.error
    assert secret not in str(result.payload)


def test_ai_settings_form_uses_optional_api_key_field() -> None:
    form = AIIntegrationSettingsForm()

    assert "api_key" in form.fields
    assert form.fields["api_key"].required is False
    assert "optional" in form.fields["api_key"].help_text.lower()
    assert form.fields["api_key"].widget.input_type == "password"
    assert "clear_api_key" in form.fields


@pytest.mark.django_db
def test_ai_settings_blank_api_key_submission_preserves_saved_key(client) -> None:
    settings = AIIntegrationSettings.objects.create(enabled=True, api_key="stored-key")
    response = client.post(
        "/settings/ai/",
        data={
            "action": "save",
            "enabled": "on",
            "provider_name": settings.provider_name,
            "api_base_url": settings.api_base_url,
            "api_key": "",
            "model_name": settings.model_name,
            "temperature": settings.temperature,
            "max_output_tokens": settings.max_output_tokens,
        },
    )
    assert response.status_code == 302
    settings.refresh_from_db()
    assert settings.api_key == "stored-key"


@pytest.mark.django_db
def test_ai_settings_explicit_clear_removes_saved_key(client) -> None:
    settings = AIIntegrationSettings.objects.create(enabled=True, api_key="stored-key")
    response = client.post(
        "/settings/ai/",
        data={
            "action": "save",
            "enabled": "on",
            "provider_name": settings.provider_name,
            "api_base_url": settings.api_base_url,
            "api_key": "",
            "clear_api_key": "on",
            "model_name": settings.model_name,
            "temperature": settings.temperature,
            "max_output_tokens": settings.max_output_tokens,
        },
    )
    assert response.status_code == 302
    settings.refresh_from_db()
    assert settings.api_key == ""


def _ai_settings_post_data(settings, **overrides):
    data = {
        "action": "test",
        "enabled": "on",
        "provider_name": settings.provider_name,
        "api_base_url": settings.api_base_url,
        "api_key": "",
        "model_name": settings.model_name,
        "temperature": settings.temperature,
        "max_output_tokens": settings.max_output_tokens,
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_ai_connection_test_saves_submitted_configuration_before_probe(client, monkeypatch) -> None:
    settings = AIIntegrationSettings.objects.create(enabled=False, api_key="")
    observed = {}

    monkeypatch.setattr("apps.core.views.fetch_ai_model_suggestions", lambda source=None: [])

    def fake_probe(source):
        source.refresh_from_db()
        observed.update(enabled=source.enabled, api_key=source.api_key, provider=source.provider_name)
        return __import__("apps.core.ai", fromlist=["AIEndpointProbeResult"]).AIEndpointProbeResult(
            ok=True, message="Connected", provider=source.provider_name, base_url=source.api_base_url
        )

    monkeypatch.setattr("apps.core.views.probe_ai_endpoint", fake_probe)
    response = client.post(
        "/settings/ai/",
        data=_ai_settings_post_data(settings, enabled="on", provider_name="test-provider", api_key="fixture-key"),
    )

    assert response.status_code == 200
    settings.refresh_from_db()
    assert settings.enabled is True
    assert settings.provider_name == "test-provider"
    assert settings.api_key == "fixture-key"
    assert observed == {"enabled": True, "api_key": "fixture-key", "provider": "test-provider"}
    assert "fixture-key" not in response.content.decode()


@pytest.mark.django_db
def test_ai_connection_test_blank_key_preserves_saved_key(client, monkeypatch) -> None:
    settings = AIIntegrationSettings.objects.create(enabled=True, api_key="stored-key")
    monkeypatch.setattr("apps.core.views.fetch_ai_model_suggestions", lambda source=None: [])
    monkeypatch.setattr(
        "apps.core.views.probe_ai_endpoint",
        lambda source: __import__("apps.core.ai", fromlist=["AIEndpointProbeResult"]).AIEndpointProbeResult(
            ok=True, message="Connected", provider=source.provider_name, base_url=source.api_base_url
        ),
    )

    response = client.post("/settings/ai/", data=_ai_settings_post_data(settings))

    assert response.status_code == 200
    settings.refresh_from_db()
    assert settings.api_key == "stored-key"


@pytest.mark.django_db
def test_ai_connection_test_explicit_clear_removes_saved_key(client, monkeypatch) -> None:
    settings = AIIntegrationSettings.objects.create(enabled=True, api_key="stored-key")
    monkeypatch.setattr("apps.core.views.fetch_ai_model_suggestions", lambda source=None: [])
    monkeypatch.setattr(
        "apps.core.views.probe_ai_endpoint",
        lambda source: __import__("apps.core.ai", fromlist=["AIEndpointProbeResult"]).AIEndpointProbeResult(
            ok=True, message="Connected", provider=source.provider_name, base_url=source.api_base_url
        ),
    )

    response = client.post("/settings/ai/", data=_ai_settings_post_data(settings, clear_api_key="on"))

    assert response.status_code == 200
    settings.refresh_from_db()
    assert settings.api_key == ""


@pytest.mark.django_db
def test_ai_connection_test_failure_still_saves_configuration(client, monkeypatch) -> None:
    settings = AIIntegrationSettings.objects.create(enabled=False, api_key="")
    monkeypatch.setattr("apps.core.views.fetch_ai_model_suggestions", lambda source=None: [])
    monkeypatch.setattr(
        "apps.core.views.probe_ai_endpoint",
        lambda source: __import__("apps.core.ai", fromlist=["AIEndpointProbeResult"]).AIEndpointProbeResult(
            ok=False, error="Endpoint unavailable", provider=source.provider_name, base_url=source.api_base_url
        ),
    )

    response = client.post(
        "/settings/ai/",
        data=_ai_settings_post_data(settings, enabled="on", api_key="fixture-key"),
    )

    assert response.status_code == 200
    assert b"Endpoint unavailable" in response.content
    settings.refresh_from_db()
    assert settings.enabled is True
    assert settings.model_name == "gpt-4o-mini"
    assert settings.api_key == "fixture-key"


@pytest.mark.django_db
def test_ai_settings_saved_key_is_never_rendered_on_reload(client) -> None:
    settings = AIIntegrationSettings.objects.create(enabled=True, api_key="configured-test-key")
    response = client.get("/settings/ai/")
    assert response.status_code == 200
    assert "configured-test-key" not in response.content.decode()
    assert settings.api_key == "configured-test-key"


def test_http_helpers_omit_authorization_for_blank_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"data": []}'

    def fake_urlopen(req, timeout):
        captured["headers"] = dict(req.header_items())
        return Response()

    monkeypatch.setattr("apps.core.ai.request.urlopen", fake_urlopen)
    from apps.core.ai import _get_json

    _get_json("http://example.com/v1/models", api_key="")
    assert "Authorization" not in {key.title() for key in captured["headers"]}


def test_http_helpers_send_bearer_authorization_for_configured_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"data": []}'

    def fake_urlopen(req, timeout):
        captured["headers"] = dict(req.header_items())
        return Response()

    monkeypatch.setattr("apps.core.ai.request.urlopen", fake_urlopen)
    from apps.core.ai import _get_json

    _get_json("http://example.com/v1/models", api_key="configured-test-key")
    headers = {key.title(): value for key, value in captured["headers"].items()}
    assert headers["Authorization"] == "Bearer configured-test-key"


@pytest.mark.django_db
def test_bearbiz_chat_context_includes_segments_reports(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    with override_settings(MEDIA_ROOT=media_root):
        upload = ReportUpload.objects.create(
            report_type="segments",
            source_file=SimpleUploadedFile("segments.pdf", b"%PDF-1.4 fake segments pdf"),
            source_name="segments.pdf",
            parse_status="parsed",
        )
        SegmentsSummary.objects.create(
            report_upload=upload,
            fiscal_year=2026,
            fiscal_week=35,
            fiscal_period_start=date(2026, 8, 23),
            fiscal_period_end=date(2026, 8, 29),
            raw_json={
                "fiscal": {"fiscal_year": 2026, "fiscal_week_number": 35, "week_ending_date": "2026-08-29"},
                "location": "1214 The Promenade in Temecula",
                "manager_rows": [
                    {
                        "name": "Vanessa Esparza",
                        "job_title": "SL",
                        "metrics": {"segment_count": 9, "success_segments": 6},
                    }
                ],
                "store_total": {"name": "Store Total", "metrics": {"segment_count": 36, "success_segments": 15}},
            },
        )

    context = build_bearbiz_chat_context()
    assert context["report_count"] == 1
    assert context["latest_report"]["report_type"] == "segments"
    assert context["latest_report"]["manager_count"] == 1
    assert context["latest_report"]["store_total"]["name"] == "Store Total"


@pytest.mark.django_db
def test_bearbiz_chat_context_includes_gift_cards_reports(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    with override_settings(MEDIA_ROOT=media_root):
        upload = ReportUpload.objects.create(
            report_type="gift_cards",
            source_file=SimpleUploadedFile("gift-cards.pdf", b"%PDF-1.4 fake gift cards pdf"),
            source_name="gift-cards.pdf",
            parse_status="parsed",
        )
        GiftCardsSummary.objects.create(
            report_upload=upload,
            fiscal_year=2026,
            fiscal_week=1,
            fiscal_period_start=date(2026, 2, 1),
            fiscal_period_end=date(2026, 2, 7),
            raw_json={
                "fiscal": {"fiscal_year": 2026, "fiscal_week_number": 1, "week_ending_date": "2026-02-07"},
                "store_number": "1214",
                "weekly_sales_dpt": 48.14,
                "weekly_sales_missing": False,
                "associate_rows": [
                    {
                        "row_kind": "associate",
                        "associate_number": "0079555",
                        "name": "Montejano, Mindy",
                        "metrics": {"total_transactions": 75, "gc_bonus_transactions": 16, "missed_opportunities": 0},
                    }
                ],
                "store_total": {
                    "row_kind": "store_total",
                    "associate_number": "",
                    "name": "Store Sales",
                    "metrics": {"total_transactions": 409, "gc_bonus_transactions": 41, "missed_opportunities": 1570.33},
                },
            },
        )

    context = build_bearbiz_chat_context()
    assert context["report_count"] == 1
    assert context["latest_report"]["report_type"] == "gift_cards"
    assert context["latest_report"]["associate_count"] == 1
    assert context["latest_report"]["weekly_sales_missing"] is False
    assert context["latest_report"]["store_total"]["name"] == "Store Sales"


@pytest.mark.django_db
def test_bearbiz_chat_context_includes_bonus_club_reports(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    with override_settings(MEDIA_ROOT=media_root):
        upload = ReportUpload.objects.create(
            report_type="bonus_club",
            source_file=SimpleUploadedFile("bonus-club.pdf", b"%PDF-1.4 fake bonus club pdf"),
            source_name="bonus-club.pdf",
            parse_status="parsed",
        )
        BonusClubSummary.objects.create(
            report_upload=upload,
            fiscal_year=2026,
            fiscal_week=1,
            fiscal_period_start=date(2026, 2, 1),
            fiscal_period_end=date(2026, 2, 7),
            raw_json={
                "fiscal": {"fiscal_year": 2026, "fiscal_week_number": 1, "week_ending_date": "2026-02-07"},
                "store_number": "1214",
                "associate_rows": [
                    {
                        "row_kind": "associate",
                        "associate_number": "0079555",
                        "name": "Montejano, Mindy",
                        "metrics": {"total_transactions": 75, "transactions_with_club": 40, "capture_rate": 53.0},
                    }
                ],
                "store_total": {
                    "row_kind": "store_total",
                    "associate_number": "",
                    "name": "Store Sales",
                    "metrics": {"total_transactions": 409, "transactions_with_club": 274, "capture_rate": 67.0},
                },
            },
        )

    context = build_bearbiz_chat_context()
    assert context["report_count"] == 1
    assert context["latest_report"]["report_type"] == "bonus_club"
    assert context["latest_report"]["associate_count"] == 1
    assert context["latest_report"]["store_total"]["name"] == "Store Sales"


def test_ai_http_error_detail_uses_backend_message() -> None:
    from urllib.error import HTTPError

    from apps.core.ai import _http_error_detail

    payload = io.BytesIO(b'{"error": {"message": "No models loaded. Please load a model first."}}')
    exc = HTTPError("http://example.com", 400, "Bad Request", hdrs=Message(), fp=payload)

    assert _http_error_detail(exc) == "No models loaded. Please load a model first."


@pytest.mark.django_db
def test_question_context_selects_gift_cards_and_excludes_unrelated_data() -> None:
    upload = ReportUpload.objects.create(
        source_file=None, source_name="gc.pdf", parse_status="parsed", report_type="gift_cards"
    )
    GiftCardsSummary.objects.create(
        report_upload=upload, fiscal_year=2026, fiscal_week=5,
        fiscal_period_start=date(2026, 2, 1), fiscal_period_end=date(2026, 2, 7),
        raw_json={"associate_rows": [{"name": "Mindy Montejano", "associate_number": "7", "metrics": {"total_transactions": 75, "gc_bonus_transactions": 16, "missed_opportunities": 2}}], "store_total": {"name": "Store Sales", "metrics": {}}},
    )
    other = ReportUpload.objects.create(
        source_file=None, source_name="ranking.pdf", parse_status="parsed", report_type="ranking"
    )
    RankingSummary.objects.create(report_upload=other, fiscal_year=2026, fiscal_week=5, fiscal_period_end=date(2026, 2, 7), raw_json={"store_rows": [{"secret_detail": "unrelated"}]})

    context = build_bearbiz_chat_context(question="Show Mindy Montejano's Gift Cards results for February")
    serialized = json.dumps(context, default=str)
    assert context["deterministic_query"]["status"] == "ok"
    assert context["deterministic_query"]["matches"][0]["metrics"]["gc_bonus_transactions"] == 16
    assert {record["report_type"] for record in context["report_details"]} == {"gift_cards"}
    assert "dashboard" not in context
    assert "unrelated" not in serialized
    assert len(serialized) <= CHAT_DATA_CONTEXT_MAX_CHARS


@pytest.mark.django_db
def test_question_context_keeps_bounded_bonus_club_trend_rows() -> None:
    for week in range(1, 9):
        upload = ReportUpload.objects.create(
            source_file=None, source_name=f"bonus-{week}.pdf", parse_status="parsed", report_type="bonus_club"
        )
        BonusClubSummary.objects.create(
            report_upload=upload, fiscal_year=2026, fiscal_week=week, fiscal_period_end=date(2026, 1, week),
            raw_json={"store_total": {"name": "Store Sales", "metrics": {"total_transactions": 100 + week, "transactions_with_club": 50 + week}}, "associate_rows": []},
        )
    context = build_bearbiz_chat_context(question="Show the Bonus Club 8 week trend")
    query = context["deterministic_query"]
    assert query["type"] == "bonus_club_8_week_trend"
    assert query["week_count"] == 8
    assert len(query["weeks"]) == 8
    assert len(json.dumps(context, default=str)) <= CHAT_DATA_CONTEXT_MAX_CHARS


@pytest.mark.django_db
def test_general_question_context_omits_detailed_rows_and_dashboard() -> None:
    upload = ReportUpload.objects.create(
        source_file=None, source_name="sales.pdf", parse_status="parsed", report_type="weekly_sales"
    )
    WeeklySalesSummary.objects.create(
        report_upload=upload, fiscal_year=2026, fiscal_week=1, fiscal_period_end=date(2026, 2, 7),
        raw_json={"summary_kpis": {"total_sales": 123}, "summary_rows": [{"private": "detail"}]},
    )
    context = build_bearbiz_chat_context(question="What should I watch next?")
    assert "report_details" not in context
    assert "dashboard" not in context
    assert "private" not in json.dumps(context, default=str)


