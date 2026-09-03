from __future__ import annotations

from typing import Any

from django.urls import reverse

REPORT_NUMBERS = tuple(range(1, 7))


def left_nav(active_section: str) -> list[dict[str, Any]]:
    return [
        {
            "label": "Dashboard",
            "url": reverse("dashboard"),
            "active": active_section == "dashboard",
        },
        {
            "label": "Report Types",
            "url": reverse("reports:index"),
            "active": active_section == "reports",
        },
        {
            "label": "Settings",
            "url": reverse("settings:index"),
            "active": active_section == "settings",
        },
    ]


def dashboard_tabs(active: str = "overview") -> list[dict[str, Any]]:
    return [
        {
            "label": "Overview",
            "url": reverse("dashboard"),
            "active": active == "overview",
        },
        {
            "label": "Activity",
            "url": reverse("reports:history"),
            "active": active == "activity",
        },
    ]


def report_tabs(active_number: int) -> list[dict[str, Any]]:
    tabs: list[dict[str, Any]] = []
    for number in REPORT_NUMBERS:
        tabs.append(
            {
                "label": f"Report {number}",
                "url": reverse("reports:index") if number == 1 else reverse("reports:report-number", kwargs={"number": number}),
                "active": number == active_number,
            }
        )
    return tabs


def settings_tabs(active: str) -> list[dict[str, Any]]:
    items = [
        ("general", "General", reverse("settings:index")),
        ("fiscal", "Fiscal year", reverse("settings:section", kwargs={"slug": "fiscal"})),
        ("ai", "AI integration", reverse("settings:section", kwargs={"slug": "ai"})),
    ]
    return [
        {"label": label, "url": url, "active": slug == active}
        for slug, label, url in items
    ]


def shell_context(
    *,
    section: str,
    page_title: str,
    top_tabs: list[dict[str, Any]] | None = None,
    primary_action: dict[str, str] | None = None,
    subtitle: str = "",
    **extra: Any,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "section": section,
        "page_title": page_title,
        "page_subtitle": subtitle,
        "left_nav": left_nav(section),
        "top_tabs": top_tabs or [],
        "primary_action": primary_action,
    }
    context.update(extra)
    return context
