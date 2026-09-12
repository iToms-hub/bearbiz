from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from apps.core.ai import build_bearbiz_chat_context, chat_about_bearbiz
from apps.core.models import AIIntegrationSettings
from apps.core.navigation import shell_context

CHAT_HISTORY_SESSION_KEY = "bearbiz.agent.chat_history"
CHAT_PROMPTS = (
    "Summarize the latest sales trend.",
    "What changed most in the last week?",
    "Which week is strongest so far?",
    "What should I watch next?",
)
WELCOME_MESSAGE = (
    "Hi Tom — I’m Bearbiz’s AI agent. Ask me about weekly sales, uploads, trends, or AI summaries, "
    "and I’ll use the data we have in the app."
)


def agent_chat(request: HttpRequest) -> HttpResponse:
    ai_settings = AIIntegrationSettings.current()
    if request.method == "POST":
        payload = _request_json(request)
        if payload.get("action") == "new_chat":
            request.session.pop(CHAT_HISTORY_SESSION_KEY, None)
            request.session.modified = True
            return JsonResponse({"ok": True})
        message = str(payload.get("message", "")).strip()
        if not message:
            return JsonResponse({"ok": False, "error": "Message is required."}, status=400)

        history = payload.get("history", [])
        if not isinstance(history, list):
            history = []
        context = build_bearbiz_chat_context(limit=4)
        result = chat_about_bearbiz(message, history=history, settings=ai_settings, data_context=context)
        if not result.ok:
            return JsonResponse(
                {
                    "ok": False,
                    "error": result.error or "AI chat is not available right now.",
                    "provider": result.provider,
                    "model": result.model,
                },
                status=400,
            )

        return JsonResponse(
            {
                "ok": True,
                "reply": result.reply,
                "provider": result.provider,
                "model": result.model,
                "context_summary": _context_summary(context),
            }
        )

    context = shell_context(
        section="agent",
        page_title="Agent",
        subtitle="Chat with Bearbiz’s AI about reports, uploads, and trends.",
        chat_enabled=ai_settings.enabled,
        chat_messages=[],
        chat_prompts=CHAT_PROMPTS,
        chat_welcome=WELCOME_MESSAGE,
        chat_context_summary=_context_summary(build_bearbiz_chat_context(limit=4)),
        ai_settings=ai_settings,
    )
    return render(request, "agent/chat.html", context)


def _request_json(request: HttpRequest) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _context_summary(context: dict[str, Any]) -> dict[str, Any]:
    dashboard = context.get("dashboard") if isinstance(context, dict) else None
    return {
        "report_count": context.get("report_count", 0),
        "recent_upload_count": len(context.get("recent_uploads", [])) if isinstance(context.get("recent_uploads", []), list) else 0,
        "recent_report_count": len(context.get("recent_reports", [])) if isinstance(context.get("recent_reports", []), list) else 0,
        "latest_week": context.get("latest_report", {}).get("fiscal_week") if isinstance(context.get("latest_report"), dict) else None,
        "dashboard_total_metrics": list(dashboard.get("metric_totals", {}).keys()) if isinstance(dashboard, dict) else [],
    }
