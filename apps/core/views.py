from __future__ import annotations

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .forms import FiscalYearSettingsForm
from .models import FiscalYearSettings
from .navigation import settings_tabs, shell_context


def settings_page(request: HttpRequest, slug: str = "general") -> HttpResponse:
    if slug not in {"general", "fiscal", "ai"}:
        raise Http404("Unknown settings section.")

    settings = FiscalYearSettings.current()
    tabs = settings_tabs(slug)

    if slug == "fiscal":
        if request.method == "POST":
            form = FiscalYearSettingsForm(request.POST, instance=settings)
            if form.is_valid():
                form.save()
                return redirect("settings:section", slug="fiscal")
        else:
            form = FiscalYearSettingsForm(instance=settings)

        context = shell_context(
            section="settings",
            page_title="Settings",
            subtitle="Configure calendar and integration settings for Bearbiz.",
            top_tabs=tabs,
            form=form,
            settings=settings,
            section_slug=slug,
        )
        return render(request, "settings/page.html", context)

    if slug == "ai":
        context = shell_context(
            section="settings",
            page_title="Settings",
            subtitle="AI integration and assistant settings land here next.",
            top_tabs=tabs,
            settings=settings,
            section_slug=slug,
        )
        return render(request, "settings/page.html", context)

    context = shell_context(
        section="settings",
        page_title="Settings",
        subtitle="General Bearbiz configuration and owners/users will live here.",
        top_tabs=tabs,
        settings=settings,
        section_slug=slug,
    )
    return render(request, "settings/page.html", context)
