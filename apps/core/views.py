from __future__ import annotations

from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .ai import fetch_available_model_names as fetch_ai_model_suggestions, probe_ai_endpoint
from .forms import AIIntegrationSettingsForm, FiscalYearSettingsForm
from .models import AIIntegrationSettings, FiscalYearSettings
from .navigation import settings_tabs, shell_context


def settings_page(request: HttpRequest, slug: str = "theme") -> HttpResponse:
    if slug == "general":
        slug = "theme"
    if slug not in {"theme", "fiscal", "ai"}:
        raise Http404("Unknown settings section.")

    fiscal_settings = FiscalYearSettings.current()
    ai_settings = AIIntegrationSettings.current()
    tabs = settings_tabs(slug)

    if slug == "fiscal":
        if request.method == "POST":
            form = FiscalYearSettingsForm(request.POST, instance=fiscal_settings)
            if form.is_valid():
                form.save()
                return redirect("settings:fiscal")
        else:
            form = FiscalYearSettingsForm(instance=fiscal_settings)

        context = shell_context(
            section="settings",
            page_title="Settings",
            subtitle="Configure calendar and integration settings for Bearbiz.",
            top_tabs=tabs,
            form=form,
            settings=fiscal_settings,
            ai_settings=ai_settings,
            section_slug=slug,
        )
        return render(request, "settings/page.html", context)

    if slug == "ai":
        available_models = fetch_ai_model_suggestions(ai_settings)
        probe_result = None
        if request.method == "POST":
            form = AIIntegrationSettingsForm(request.POST, instance=ai_settings, available_models=available_models)
            action = request.POST.get("action", "save")
            if form.is_valid():
                if action == "test":
                    probe_result = probe_ai_endpoint(form.cleaned_data)
                    available_models = probe_result.models or available_models
                    form = AIIntegrationSettingsForm(
                        form.cleaned_data,
                        instance=ai_settings,
                        available_models=available_models,
                    )
                else:
                    form.save()
                    return redirect("settings:ai")
        else:
            form = AIIntegrationSettingsForm(instance=ai_settings, available_models=available_models)

        context = shell_context(
            section="settings",
            page_title="Settings",
            subtitle="AI integration and assistant settings land here next.",
            top_tabs=tabs,
            form=form,
            settings=ai_settings,
            fiscal_settings=fiscal_settings,
            available_models=available_models,
            probe_result=probe_result,
            section_slug=slug,
        )
        return render(request, "settings/page.html", context)

    if slug == "theme":
        context = shell_context(
            section="settings",
            page_title="Settings",
            subtitle="Customize Bearbiz colors and light/dark mode behavior.",
            top_tabs=tabs,
            fiscal_settings=fiscal_settings,
            ai_settings=ai_settings,
            section_slug=slug,
        )
        return render(request, "settings/page.html", context)

    context = shell_context(
        section="settings",
        page_title="Settings",
        subtitle="General Bearbiz configuration and owners/users will live here.",
        top_tabs=tabs,
        fiscal_settings=fiscal_settings,
        ai_settings=ai_settings,
        section_slug=slug,
    )
    return render(request, "settings/page.html", context)


@require_POST
def ai_connection_test(request: HttpRequest) -> JsonResponse:
    payload = _request_json(request)
    result = probe_ai_endpoint(payload or None)
    status = 200 if result.ok else 400
    return JsonResponse(
        {
            "ok": result.ok,
            "provider": result.provider,
            "model": result.models[0] if result.models else "",
            "model_suggestions": list(result.models),
            "payload": result.payload,
            "error": result.error,
        },
        status=status,
    )


@require_GET
def ai_model_suggestions(request: HttpRequest) -> JsonResponse:
    try:
        suggestions = _fetch_model_suggestions(request.GET or None)
    except Exception as exc:
        return JsonResponse({"ok": False, "models": [], "error": str(exc)}, status=400)

    return JsonResponse({"ok": True, "models": list(suggestions)})


def _fetch_model_suggestions(source: object | None = None) -> tuple[str, ...]:
    try:
        suggestions = fetch_ai_model_suggestions(source)
    except TypeError:
        suggestions = fetch_ai_model_suggestions()
    return tuple(suggestions)


def _request_json(request: HttpRequest) -> dict[str, object]:
    try:
        import json

        if not request.body:
            return {}
        data = json.loads(request.body.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
