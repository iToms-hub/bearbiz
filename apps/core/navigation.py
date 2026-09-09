from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from django.urls import reverse

from apps.reports.catalog import report_label
from bearbiz import __version__

REPORT_NUMBERS = tuple(range(1, 7))
APP_VERSION = __version__


def left_nav(active_section: str, active_number: int | None = None) -> list[dict[str, Any]]:
    reports_active = active_section == "reports"
    return [
        {
            "label": "Dashboard",
            "url": reverse("dashboard"),
            "active": active_section == "dashboard",
        },
        {
            "label": "Performance",
            "url": reverse("performance"),
            "active": active_section == "performance",
        },
        {
            "label": "Reports",
            "url": reverse("reports:index"),
            "active": reports_active,
            "children": report_tabs(active_number or 1) if reports_active else [],
        },
        {
            "label": "Agent",
            "url": reverse("agent:index"),
            "active": active_section == "agent",
        },
        {
            "label": "Settings",
            "url": reverse("settings:index"),
            "active": active_section == "settings",
            "css_class": "nav-bottom",
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
            "label": "Uploads",
            "url": reverse("reports:history"),
            "active": active == "uploads",
        },
    ]


def report_mode_tabs(active: str) -> list[dict[str, Any]]:
    items = [
        ("uploads", "Upload", reverse("reports:history")),
        ("reports", "View reports", reverse("reports:index")),
    ]
    return [
        {"label": label, "url": url, "active": slug == active}
        for slug, label, url in items
    ]


def report_tabs(
    active_number: int,
    query_params: dict[str, Any] | None = None,
    *,
    upload: bool = False,
) -> list[dict[str, Any]]:
    query = {key: value for key, value in (query_params or {}).items() if value not in (None, "")}
    tabs: list[dict[str, Any]] = []
    for number in REPORT_NUMBERS:
        if upload:
            url = reverse("reports:history") if number == 1 else reverse("reports:history-number", kwargs={"number": number})
        else:
            url = reverse("reports:index") if number == 1 else reverse("reports:report-number", kwargs={"number": number})
        if query:
            url = f"{url}?{urlencode(query, doseq=True)}"
        tabs.append(
            {
                "label": report_label(number),
                "url": url,
                "active": number == active_number,
            }
        )
    return tabs


def report_date_tabs(
    active: str,
    report_number: int,
    query_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    base_url = reverse("reports:index") if report_number == 1 else reverse("reports:report-number", kwargs={"number": report_number})
    query = {key: value for key, value in (query_params or {}).items() if value not in (None, "")}
    active = "last_week" if active == "all" else active

    def _clear_period_params(params: dict[str, Any]) -> None:
        for key in ("week_end", "range_start", "range_end"):
            params.pop(key, None)

    items: list[tuple[str, str, dict[str, Any]]] = [
        ("last_week", "Last week", {"date_filter": "last_week"}),
        ("month", "Current month", {"date_filter": "month"}),
        ("quarter", "Current quarter", {"date_filter": "quarter"}),
    ]
    if report_number in {1, 2}:
        items.append(("year", "Year", {"date_filter": "year"}))
    items.extend(
        [
            ("week", "Specific week", {"date_filter": "week"}),
            ("range", "Week range", {"date_filter": "range"}),
        ]
    )
    tabs: list[dict[str, Any]] = []
    for slug, label, overrides in items:
        params = query.copy()
        params.update(overrides)
        if slug in {"last_week", "month", "quarter", "year"}:
            _clear_period_params(params)
        elif slug == "week":
            params.pop("range_start", None)
            params.pop("range_end", None)
        elif slug == "range":
            params.pop("week_end", None)
        url = base_url if not params else f"{base_url}?{urlencode(params, doseq=True)}"
        tabs.append({"label": label, "url": url, "active": slug == active})
    return tabs


def settings_tabs(active: str) -> list[dict[str, Any]]:
    items = [
        ("theme", "Theme", reverse("settings:index")),
        ("fiscal", "Fiscal year", reverse("settings:fiscal")),
        ("ai", "AI integration", reverse("settings:ai")),
        ("backup", "Backup", reverse("settings:backup")),
    ]
    return [
        {"label": label, "url": url, "active": slug == active}
        for slug, label, url in items
    ]


def shell_context(
    *,
    section: str,
    page_title: str,
    active_number: int | None = None,
    top_tabs: list[dict[str, Any]] | None = None,
    primary_action: dict[str, str] | None = None,
    subtitle: str = "",
    **extra: Any,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "section": section,
        "page_title": page_title,
        "page_subtitle": subtitle,
        "left_nav": left_nav(section, active_number),
        "top_tabs": top_tabs or [],
        "primary_action": primary_action,
        "app_version": APP_VERSION,
    }
    context.update(extra)
    return context
