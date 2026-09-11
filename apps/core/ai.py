from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import date
import json
import os
from typing import Any, Mapping, Sequence
from urllib import error, request

from .models import AIIntegrationSettings
from apps.reports.dashboard import build_six_week_dashboard
from apps.reports.models import BonusClubSummary, GiftCardsSummary, RankingSummary, ReportUpload, SegmentsSummary, WeeklySalesSummary


@dataclass(slots=True)
class AIIntegrationConfig:
    enabled: bool = False
    provider_name: str = "openai-compatible"
    api_base_url: str = "https://api.openai.com/v1"
    chat_completions_path: str = "/chat/completions"
    api_key_env_var: str = "BEARBIZ_AI_API_KEY"
    model_name: str = "gpt-4o-mini"
    temperature: float = 0.2
    max_output_tokens: int = 500
    report_summary_prompt: str = (
        "Summarize the weekly sales report for a store manager. "
        "Call out notable trends, weak spots, and a practical next action."
    )
    system_prompt: str = (
        "You are Bearbiz's AI report assistant. Write concise, helpful report summaries "
        "based only on the supplied report data."
    )

    @classmethod
    def from_source(cls, source: Any | None = None) -> "AIIntegrationConfig":
        source = AIIntegrationSettings.current() if source is None else source
        return cls(
            enabled=bool(_source_value(source, "enabled", False)),
            provider_name=str(_source_value(source, "provider_name", cls.provider_name)),
            api_base_url=normalize_api_base_url(
                str(_source_value(source, "api_base_url", cls.api_base_url))
            ),
            chat_completions_path=_normalize_path(
                str(_source_value(source, "chat_completions_path", "/chat/completions"))
            ),
            api_key_env_var=str(_source_value(source, "api_key_env_var", "BEARBIZ_AI_API_KEY")),
            model_name=str(_source_value(source, "model_name", "gpt-4o-mini")),
            temperature=float(_source_value(source, "temperature", 0.2)),
            max_output_tokens=int(_source_value(source, "max_output_tokens", 500)),
            report_summary_prompt=str(
                _source_value(
                    source,
                    "report_summary_prompt",
                    "Summarize the weekly sales report for a store manager. Call out notable trends, weak spots, and a practical next action.",
                )
            ),
            system_prompt=str(
                _source_value(
                    source,
                    "system_prompt",
                    "You are Bearbiz's AI report assistant. Write concise, helpful report summaries based only on the supplied report data.",
                )
            ),
        )


@dataclass(slots=True)
class AIAnalysisResult:
    enabled: bool
    provider: str = ""
    model: str = ""
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.enabled and bool(self.summary) and not self.error


@dataclass(slots=True)
class AIChatResult:
    enabled: bool
    provider: str = ""
    model: str = ""
    reply: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.enabled and bool(self.reply) and not self.error


@dataclass(slots=True)
class AIEndpointProbeResult:
    ok: bool
    message: str = ""
    models: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    provider: str = ""
    base_url: str = ""


def summarize_weekly_sales_report(
    report_payload: Mapping[str, Any],
    *,
    source_name: str = "",
    raw_text: str = "",
    settings: Any | None = None,
) -> AIAnalysisResult:
    config = AIIntegrationConfig.from_source(settings)
    if not config.enabled:
        return AIAnalysisResult(enabled=False, error="AI enrichment is disabled.")

    api_key = os.getenv(config.api_key_env_var, "").strip() if config.api_key_env_var else ""
    if not api_key and config.api_key_env_var:
        return AIAnalysisResult(
            enabled=True,
            provider=config.provider_name,
            model=config.model_name,
            error=f"Missing API key in environment variable {config.api_key_env_var}.",
        )

    prompt = _build_prompt(report_payload, source_name=source_name, raw_text=raw_text, config=config)
    url = _join_url(config.api_base_url, config.chat_completions_path)
    body = {
        "model": config.model_name,
        "messages": [
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(config.temperature),
        "max_tokens": int(config.max_output_tokens),
    }

    try:
        payload = _post_json(url, body, api_key=api_key)
        summary = _extract_message(payload)
        return AIAnalysisResult(
            enabled=True,
            provider=config.provider_name,
            model=config.model_name,
            summary=summary,
            payload=payload,
        )
    except Exception as exc:  # pragma: no cover - exercised through integration paths
        return AIAnalysisResult(
            enabled=True,
            provider=config.provider_name,
            model=config.model_name,
            error=str(exc),
        )


def chat_about_bearbiz(
    message: str,
    *,
    history: Sequence[Mapping[str, Any]] | None = None,
    settings: Any | None = None,
    data_context: Mapping[str, Any] | None = None,
) -> AIChatResult:
    config = AIIntegrationConfig.from_source(settings)
    if not config.enabled:
        return AIChatResult(enabled=False, error="AI chat is disabled.")

    api_key = os.getenv(config.api_key_env_var, "").strip() if config.api_key_env_var else ""
    if not api_key and config.api_key_env_var:
        return AIChatResult(
            enabled=True,
            provider=config.provider_name,
            model=config.model_name,
            error=f"Missing API key in environment variable {config.api_key_env_var}.",
        )

    context = dict(data_context or build_bearbiz_chat_context())
    conversation = _sanitize_chat_history(history or [])
    prompt = [
        config.system_prompt.strip(),
        "",
        "You are Bearbiz's AI agent. Answer questions about the store's reports, uploads, trends, and AI setup.",
        "Use the Bearbiz data context below as the source of truth for factual claims.",
        "If the context does not include an answer, say what is missing instead of guessing.",
        "Keep the response concise, practical, and easy to act on.",
        "",
        "Bearbiz data context (read only):",
        json.dumps(context, ensure_ascii=False, indent=2, default=_json_default),
    ]
    messages: list[dict[str, str]] = [{"role": "system", "content": "\n".join(prompt)}]
    messages.extend(conversation)
    messages.append({"role": "user", "content": message.strip()})

    body = {
        "model": config.model_name,
        "messages": messages,
        "temperature": float(config.temperature),
        "max_tokens": int(config.max_output_tokens),
    }

    try:
        payload = _post_json(_join_url(config.api_base_url, config.chat_completions_path), body, api_key=api_key)
        reply = _extract_message(payload)
        return AIChatResult(
            enabled=True,
            provider=config.provider_name,
            model=config.model_name,
            reply=reply,
            payload=payload,
        )
    except Exception as exc:  # pragma: no cover - environment-specific network errors
        return AIChatResult(
            enabled=True,
            provider=config.provider_name,
            model=config.model_name,
            error=str(exc),
        )


def probe_ai_endpoint(source: Any | None = None) -> AIEndpointProbeResult:
    config = AIIntegrationConfig.from_source(source)
    api_key = os.getenv(config.api_key_env_var, "").strip() if config.api_key_env_var else ""

    if config.api_key_env_var and not api_key:
        return AIEndpointProbeResult(
            ok=False,
            provider=config.provider_name,
            base_url=config.api_base_url,
            error=f"Missing API key in environment variable {config.api_key_env_var}.",
        )

    url = _join_url(config.api_base_url, "/models")
    try:
        payload = _get_json(url, api_key=api_key)
        models = _extract_model_names(payload)
        message = (
            f"Connected to {config.provider_name} and found {len(models)} model(s)."
            if models
            else f"Connected to {config.provider_name}."
        )
        return AIEndpointProbeResult(
            ok=True,
            message=message,
            models=models,
            payload=payload,
            provider=config.provider_name,
            base_url=config.api_base_url,
        )
    except Exception as exc:  # pragma: no cover - network failures are environment-specific
        return AIEndpointProbeResult(
            ok=False,
            provider=config.provider_name,
            base_url=config.api_base_url,
            error=str(exc),
        )


def fetch_available_model_names(source: Any | None = None) -> tuple[str, ...]:
    probe = probe_ai_endpoint(source)
    return probe.models if probe.ok else ()


def build_bearbiz_chat_context(limit: int = 12, *, reference_date: date | None = None) -> dict[str, Any]:
    weekly_summaries = list(
        getattr(WeeklySalesSummary, "objects").select_related("report_upload").order_by("-fiscal_year", "-fiscal_week", "-id")[:limit]
    )
    ranking_summaries = list(
        getattr(RankingSummary, "objects").select_related("report_upload").order_by("-fiscal_year", "-fiscal_week", "-id")[:limit]
    )
    segment_summaries = list(
        getattr(SegmentsSummary, "objects").select_related("report_upload").order_by("-fiscal_year", "-fiscal_week", "-id")[:limit]
    )
    gift_cards_summaries = list(
        getattr(GiftCardsSummary, "objects").select_related("report_upload").order_by("-fiscal_year", "-fiscal_week", "-id")[:limit]
    )
    bonus_club_summaries = list(
        getattr(BonusClubSummary, "objects").select_related("report_upload").order_by("-fiscal_year", "-fiscal_week", "-id")[:limit]
    )
    uploads = list(getattr(ReportUpload, "objects").order_by("-uploaded_at", "-id")[:5])
    report_records: list[dict[str, Any]] = []
    latest_end: date | None = None

    for summary in weekly_summaries:
        raw_json = summary.raw_json if isinstance(summary.raw_json, Mapping) else {}
        kpis_data = raw_json.get("summary_kpis") if isinstance(raw_json, Mapping) else None
        kpis = kpis_data if isinstance(kpis_data, Mapping) else {}
        if isinstance(summary.fiscal_period_end, date):
            latest_end = summary.fiscal_period_end if latest_end is None else max(latest_end, summary.fiscal_period_end)
        report_records.append(
            {
                "report_type": "weekly_sales",
                "fiscal_year": summary.fiscal_year,
                "fiscal_week": summary.fiscal_week,
                "period_start": summary.fiscal_period_start.isoformat() if summary.fiscal_period_start else None,
                "period_end": summary.fiscal_period_end.isoformat() if summary.fiscal_period_end else None,
                "source_name": summary.report_upload.source_name,
                "parse_status": summary.report_upload.parse_status,
                "total_sales": kpis.get("total_sales"),
                "ly_total_sales": kpis.get("ly_total_sales"),
                "target_total_sales": kpis.get("target_total_sales"),
                "traffic": kpis.get("traffic"),
                "conversion_rate": kpis.get("conversion_rate"),
                "sales_trans": kpis.get("sales_trans"),
                "ai_summary": summary.ai_summary,
            }
        )

    for summary in ranking_summaries:
        raw_json = summary.raw_json if isinstance(summary.raw_json, Mapping) else {}
        target = raw_json.get("target_store") if isinstance(raw_json, Mapping) else None
        target_data = target if isinstance(target, Mapping) else {}
        if isinstance(summary.fiscal_period_end, date):
            latest_end = summary.fiscal_period_end if latest_end is None else max(latest_end, summary.fiscal_period_end)
        report_records.append(
            {
                "report_type": "ranking",
                "fiscal_year": summary.fiscal_year,
                "fiscal_week": summary.fiscal_week,
                "period_start": summary.fiscal_period_start.isoformat() if summary.fiscal_period_start else None,
                "period_end": summary.fiscal_period_end.isoformat() if summary.fiscal_period_end else None,
                "source_name": summary.report_upload.source_name,
                "parse_status": summary.report_upload.parse_status,
                "store_count": raw_json.get("store_count"),
                "target_store": {
                    "store_number": target_data.get("store_number"),
                    "store_name": target_data.get("store_name"),
                    "ranks": target_data.get("ranks", {}),
                },
                "ai_summary": summary.ai_summary,
            }
        )

    for summary in gift_cards_summaries:
        raw_json = summary.raw_json if isinstance(summary.raw_json, Mapping) else {}
        associate_rows = raw_json.get("associate_rows") if isinstance(raw_json, Mapping) else None
        store_total = raw_json.get("store_total") if isinstance(raw_json, Mapping) else None
        associate_list = associate_rows if isinstance(associate_rows, list) else []
        if isinstance(summary.fiscal_period_end, date):
            latest_end = summary.fiscal_period_end if latest_end is None else max(latest_end, summary.fiscal_period_end)
        report_records.append(
            {
                "report_type": "gift_cards",
                "fiscal_year": summary.fiscal_year,
                "fiscal_week": summary.fiscal_week,
                "period_start": summary.fiscal_period_start.isoformat() if summary.fiscal_period_start else None,
                "period_end": summary.fiscal_period_end.isoformat() if summary.fiscal_period_end else None,
                "source_name": summary.report_upload.source_name,
                "parse_status": summary.report_upload.parse_status,
                "store_number": raw_json.get("store_number"),
                "associate_count": len(associate_list),
                "weekly_sales_dpt": raw_json.get("weekly_sales_dpt"),
                "weekly_sales_missing": raw_json.get("weekly_sales_missing"),
                "store_total": {
                    "name": store_total.get("name"),
                    "metrics": store_total.get("metrics", {}),
                }
                if isinstance(store_total, Mapping)
                else None,
                "associate_rows": [
                    {
                        "associate_number": row.get("associate_number"),
                        "name": row.get("name"),
                        "metrics": row.get("metrics", {}),
                    }
                    for row in associate_list[:3]
                    if isinstance(row, Mapping)
                ],
                "ai_summary": summary.ai_summary,
            }
        )

    for summary in bonus_club_summaries:
        raw_json = summary.raw_json if isinstance(summary.raw_json, Mapping) else {}
        associate_rows = raw_json.get("associate_rows") if isinstance(raw_json, Mapping) else None
        store_total = raw_json.get("store_total") if isinstance(raw_json, Mapping) else None
        associate_list = associate_rows if isinstance(associate_rows, list) else []
        if isinstance(summary.fiscal_period_end, date):
            latest_end = summary.fiscal_period_end if latest_end is None else max(latest_end, summary.fiscal_period_end)
        report_records.append(
            {
                "report_type": "bonus_club",
                "fiscal_year": summary.fiscal_year,
                "fiscal_week": summary.fiscal_week,
                "period_start": summary.fiscal_period_start.isoformat() if summary.fiscal_period_start else None,
                "period_end": summary.fiscal_period_end.isoformat() if summary.fiscal_period_end else None,
                "source_name": summary.report_upload.source_name,
                "parse_status": summary.report_upload.parse_status,
                "store_number": raw_json.get("store_number"),
                "associate_count": len(associate_list),
                "store_total": {
                    "name": store_total.get("name"),
                    "metrics": store_total.get("metrics", {}),
                }
                if isinstance(store_total, Mapping)
                else None,
                "associate_rows": [
                    {
                        "associate_number": row.get("associate_number"),
                        "name": row.get("name"),
                        "metrics": row.get("metrics", {}),
                    }
                    for row in associate_list[:3]
                    if isinstance(row, Mapping)
                ],
                "ai_summary": summary.ai_summary,
            }
        )

    for summary in segment_summaries:
        raw_json = summary.raw_json if isinstance(summary.raw_json, Mapping) else {}
        manager_rows = raw_json.get("manager_rows") if isinstance(raw_json, Mapping) else None
        store_total = raw_json.get("store_total") if isinstance(raw_json, Mapping) else None
        manager_list = manager_rows if isinstance(manager_rows, list) else []
        if isinstance(summary.fiscal_period_end, date):
            latest_end = summary.fiscal_period_end if latest_end is None else max(latest_end, summary.fiscal_period_end)
        report_records.append(
            {
                "report_type": "segments",
                "fiscal_year": summary.fiscal_year,
                "fiscal_week": summary.fiscal_week,
                "period_start": summary.fiscal_period_start.isoformat() if summary.fiscal_period_start else None,
                "period_end": summary.fiscal_period_end.isoformat() if summary.fiscal_period_end else None,
                "source_name": summary.report_upload.source_name,
                "parse_status": summary.report_upload.parse_status,
                "location": raw_json.get("location"),
                "manager_count": len(manager_list),
                "manager_rows": [
                    {
                        "name": row.get("name"),
                        "job_title": row.get("job_title"),
                        "metrics": row.get("metrics", {}),
                    }
                    for row in manager_list[:3]
                    if isinstance(row, Mapping)
                ],
                "store_total": {
                    "name": store_total.get("name"),
                    "metrics": store_total.get("metrics", {}),
                }
                if isinstance(store_total, Mapping)
                else None,
                "ai_summary": summary.ai_summary,
            }
        )

    report_records.sort(
        key=lambda record: (
            str(record.get("period_end") or ""),
            int(record.get("fiscal_year") or 0),
            int(record.get("fiscal_week") or 0),
            str(record.get("report_type") or ""),
        ),
        reverse=True,
    )

    dashboard_source = [
        {
            "report_type": "weekly_sales",
            "source_name": summary.report_upload.source_name,
            "period_start": summary.fiscal_period_start.isoformat() if summary.fiscal_period_start else None,
            "period_end": summary.fiscal_period_end.isoformat() if summary.fiscal_period_end else None,
            "payload": summary.raw_json if isinstance(summary.raw_json, Mapping) else {},
            "raw_rows": (summary.raw_json.get("summary_rows", []) if isinstance(summary.raw_json, Mapping) else []),
        }
        for summary in weekly_summaries
    ]
    dashboard_reference = latest_end or reference_date or date.today()
    dashboard = build_six_week_dashboard(dashboard_source, selection="all", reference_date=dashboard_reference).to_dict()
    compact_latest_report = _compact_chat_report_record(report_records[0]) if report_records else None
    compact_recent_reports = [_compact_chat_report_record(record) for record in report_records[:limit]]
    return {
        "report_count": len(report_records),
        "latest_report": compact_latest_report,
        "recent_reports": compact_recent_reports,
        "recent_uploads": [
            {
                "source_name": upload.source_name,
                "parse_status": upload.parse_status,
                "uploaded_at": upload.uploaded_at.isoformat() if upload.uploaded_at else None,
            }
            for upload in uploads
        ],
        "dashboard": dashboard,
    }


def _sanitize_chat_history(history: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in list(history)[-12:]:
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        messages.append({"role": role, "content": content})
    return messages


def normalize_api_base_url(base_url: str) -> str:
    cleaned = str(base_url or "").strip().rstrip("/")
    if not cleaned:
        return "https://api.openai.com/v1"
    if cleaned.endswith("/v1"):
        return cleaned
    return f"{cleaned}/v1"


def _build_prompt(
    report_payload: Mapping[str, Any],
    *,
    source_name: str,
    raw_text: str,
    config: AIIntegrationConfig,
) -> str:
    summary_rows = report_payload.get("summary_rows") if isinstance(report_payload, Mapping) else None
    summary_kpis = report_payload.get("summary_kpis") if isinstance(report_payload, Mapping) else None
    fiscal = report_payload.get("fiscal") if isinstance(report_payload, Mapping) else None
    payload = {
        "source_name": source_name,
        "period_start": report_payload.get("period_start"),
        "period_end": report_payload.get("period_end"),
        "fiscal": fiscal,
        "summary_kpis": summary_kpis,
        "summary_rows": summary_rows,
    }
    prompt_parts = [
        config.report_summary_prompt.strip(),
        "",
        "Return a concise report summary with these sections:",
        "- overview",
        "- notable_trends",
        "- risks_or_anomalies",
        "- recommended_next_action",
        "",
        "Report JSON:",
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
    ]
    raw_text_str = str(raw_text).strip()
    if raw_text_str:
        prompt_parts.extend(["", "Raw extracted text:", raw_text_str[:8000]])
    return "\n".join(prompt_parts)


def _post_json(url: str, payload: Mapping[str, Any], *, api_key: str) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "bearbiz-ai/0.9.5",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(
        url,
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = _http_error_detail(exc)
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"AI service returned HTTP {exc.code}{suffix}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Unable to reach AI service at {url}: {exc.reason}") from exc


def _get_json(url: str, *, api_key: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "bearbiz-ai/0.9.5",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(
        url,
        headers=headers,
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = _http_error_detail(exc)
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"AI service returned HTTP {exc.code}{suffix}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Unable to reach AI service at {url}: {exc.reason}") from exc


def _extract_message(payload: Mapping[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload, Mapping) else None
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, Mapping):
            message = first.get("message")
            if isinstance(message, Mapping):
                content = message.get("content")
                if isinstance(content, str):
                    return content.strip()
            text = first.get("text")
            if isinstance(text, str):
                return text.strip()
    raise RuntimeError("AI response did not contain a usable summary.")


def _extract_model_names(payload: Mapping[str, Any]) -> tuple[str, ...]:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, list):
        return ()
    names: list[str] = []
    for item in data:
        if not isinstance(item, Mapping):
            continue
        name = item.get("id") or item.get("name")
        if isinstance(name, str):
            name = name.strip()
            if name and name not in names:
                names.append(name)
    return tuple(names)


def _compact_chat_report_record(record: Mapping[str, Any]) -> dict[str, Any]:
    report_type = str(record.get("report_type") or "")
    compact: dict[str, Any] = {
        "report_type": report_type,
        "fiscal_year": record.get("fiscal_year"),
        "fiscal_week": record.get("fiscal_week"),
        "period_end": record.get("period_end"),
        "source_name": record.get("source_name"),
        "parse_status": record.get("parse_status"),
    }
    if report_type == "weekly_sales":
        compact.update(
            {
                "total_sales": record.get("total_sales"),
                "traffic": record.get("traffic"),
                "conversion_rate": record.get("conversion_rate"),
            }
        )
    elif report_type == "ranking":
        compact.update(
            {
                "store_count": record.get("store_count"),
                "target_store": record.get("target_store"),
            }
        )
    elif report_type == "segments":
        compact.update(
            {
                "location": record.get("location"),
                "manager_count": record.get("manager_count"),
                "store_total": record.get("store_total"),
            }
        )
    elif report_type == "gift_cards":
        compact.update(
            {
                "associate_count": record.get("associate_count"),
                "weekly_sales_missing": record.get("weekly_sales_missing"),
                "store_total": record.get("store_total"),
            }
        )
    elif report_type == "bonus_club":
        compact.update(
            {
                "associate_count": record.get("associate_count"),
                "store_total": record.get("store_total"),
            }
        )
    return compact


def _http_error_detail(exc: error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", "replace").strip()
    except Exception:
        return ""
    if not body:
        return ""
    try:
        payload = json.loads(body)
    except Exception:
        return body
    if isinstance(payload, Mapping):
        error_obj = payload.get("error")
        if isinstance(error_obj, Mapping):
            message = error_obj.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return body


def _join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _normalize_path(path: str) -> str:
    cleaned = str(path or "").strip()
    if not cleaned:
        return "/chat/completions"
    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"
    return cleaned


def _source_value(source: Any, key: str, default: Any) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return str(value)
