from __future__ import annotations

import re
import threading
import time
from urllib import error as url_error
from urllib import request as url_request
from typing import Any
from urllib.parse import urlencode

from django.urls import reverse

from apps.reports.catalog import report_label
from bearbiz import __version__

REPORT_NUMBERS = tuple(range(1, 7))
APP_VERSION = __version__
REMOTE_VERSION_URL = "https://raw.githubusercontent.com/iToms-hub/bearbiz/main/VERSION"
VERSION_CACHE_SECONDS = 15 * 60
_version_cache: tuple[float, str | None] | None = None
_version_cache_lock = threading.Lock()
_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def left_nav(active_section: str, active_number: int | None = None) -> list[dict[str, Any]]:
    reports_active = active_section == "reports"
    items: list[dict[str, Any]] = [
        {
            "label": "Dashboard",
            "url": reverse("dashboard"),
            "active": active_section == "dashboard",
            "icon_asset": "bearbiz-dashboard.png",
            "icon_alt": "Stitched Bearbiz house dashboard icon",
        },
        {
            "label": "Reports",
            "url": reverse("reports:index"),
            "active": reports_active,
            "children": report_tabs(active_number or 1) if reports_active else [],
            "icon_asset": "bearbiz-reports.png",
            "icon_alt": "Stitched reports document icon",
        },
        {
            "label": "Performance",
            "url": reverse("performance"),
            "active": active_section == "performance",
            "icon_asset": "bearbiz-performance.png",
            "icon_alt": "Stitched performance chart icon",
        },
        {
            "label": "Missed Ops",
            "url": reverse("missed-ops"),
            "active": active_section == "missed-ops",
            "icon_asset": "bearbiz-missed-ops.png",
            "icon_alt": "Stitched shopping bag with a red X icon",
        },
        {
            "label": "Payroll",
            "url": reverse("payroll"),
            "active": active_section == "payroll",
            "icon_asset": "bearbiz-payroll.png",
            "icon_alt": "Stitched wallet with coin icon",
        },
        {
            "label": "Product",
            "url": reverse("product"),
            "active": active_section == "product",
            "icon_asset": "bearbiz-product.png",
            "icon_alt": "Stitched bear product box icon",
        },
        {
            "label": "Parties",
            "url": reverse("parties"),
            "active": active_section == "parties",
            "icon_asset": "bearbiz-parties.png",
            "icon_alt": "Stitched party popper icon",
        },
        {
            "label": "Agent",
            "url": reverse("agent:index"),
            "active": active_section == "agent",
            "icon_asset": "bearbiz-agent.png",
            "icon_alt": "Stitched Bearbiz agent headset icon",
        },
    ]
    update = update_notification()
    if update:
        items.append(update)
    items.append({
            "label": "Settings",
            "url": reverse("settings:index"),
            "active": active_section == "settings",
            "css_class": "nav-bottom",
        })
    return items


def update_notification() -> dict[str, Any] | None:
    remote_version = latest_remote_version()
    if not remote_version or not _is_newer_version(remote_version, APP_VERSION):
        return None
    return {
        "label": "Update available",
        "url": "https://github.com/iToms-hub/bearbiz/releases/latest",
        "active": False,
        "css_class": "nav-update",
        "icon": "⬆",
        "title": f"Update available: Bearbiz {remote_version}",
    }


def latest_remote_version() -> str | None:
    """Return the cached valid VERSION value, failing closed on any error."""
    global _version_cache
    now = time.monotonic()
    with _version_cache_lock:
        if _version_cache and now - _version_cache[0] < VERSION_CACHE_SECONDS:
            return _version_cache[1]
    version: str | None = None
    response = None
    try:
        response = url_request.urlopen(
            url_request.Request(REMOTE_VERSION_URL, headers={"User-Agent": "Bearbiz"}),
            timeout=2,
        )
        raw = response.read(128).decode("utf-8").strip()
        if _parse_version(raw):
            version = raw
    except (OSError, UnicodeError, ValueError, url_error.URLError):
        version = None
    finally:
        if response is not None:
            response.close()
    with _version_cache_lock:
        _version_cache = (time.monotonic(), version)
    return version


def clear_version_cache() -> None:
    """Clear the remote version cache (primarily useful for focused tests)."""
    global _version_cache
    with _version_cache_lock:
        _version_cache = None


def _parse_version(value: str) -> tuple[int, int, int, tuple[str, ...]] | None:
    match = _SEMVER_PATTERN.fullmatch(value)
    if not match:
        return None
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
    if any(identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0") for identifier in prerelease):
        return None
    return (
        int(match.group(1)), int(match.group(2)), int(match.group(3)),
        prerelease,
    )


def _is_newer_version(remote: str, installed: str) -> bool:
    remote_parts = _parse_version(remote)
    installed_parts = _parse_version(installed)
    if not remote_parts or not installed_parts:
        return False
    if remote_parts[:3] != installed_parts[:3]:
        return remote_parts[:3] > installed_parts[:3]
    remote_pre, installed_pre = remote_parts[3], installed_parts[3]
    if not remote_pre or not installed_pre:
        return bool(not remote_pre and installed_pre)
    for remote_id, installed_id in zip(remote_pre, installed_pre):
        if remote_id == installed_id:
            continue
        if remote_id.isdigit() and installed_id.isdigit():
            return int(remote_id) > int(installed_id)
        if remote_id.isdigit() != installed_id.isdigit():
            return remote_id.isdigit()
        return remote_id > installed_id
    return len(remote_pre) > len(installed_pre)


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
