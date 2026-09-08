from __future__ import annotations

from typing import Any

REPORTS_BY_NUMBER: dict[int, dict[str, Any]] = {
    1: {
        "slug": "weekly_sales",
        "label": "Weekly sales",
        "title": "Weekly Sales Summary",
        "subtitle": "Weekly sales uploads, parsed rows, and the live report history.",
        "viewer_title": "Weekly report data",
        "viewer_note": "Newest week first, with each week in its own row.",
        "upload_supported": True,
        "summary_relation": "weekly_sales_summary",
    },
    2: {
        "slug": "ranking",
        "label": "Ranking",
        "title": "Ranking: Store-by-store comparison",
        "subtitle": "Weekly ranking uploads with Temecula versus the rest of the district.",
        "viewer_title": "Store ranking data",
        "viewer_note": "Lower numbers mean a stronger ranking against the other stores.",
        "upload_supported": True,
        "summary_relation": "ranking_summary",
    },
    3: {
        "slug": "segments",
        "label": "Segments",
        "title": "Segments: manager accountability",
        "subtitle": "Weekly segment accountability uploads and parsed manager rows.",
        "viewer_title": "Manager segment accountability",
        "viewer_note": "One row per manager with the accountability columns the team asked for.",
        "upload_supported": True,
        "summary_relation": "segments_summary",
    },
    4: {
        "slug": "gift_cards",
        "label": "Gift Cards",
        "title": "Gift Cards: associate GC bonus performance",
        "subtitle": "Weekly gift card bonus uploads with associate performance and store totals.",
        "viewer_title": "Associate gift card bonus performance",
        "viewer_note": "One row per associate, store total at bottom.",
        "upload_supported": True,
        "summary_relation": "gift_cards_summary",
    },
    5: {
        "slug": "bonus_club",
        "label": "Bonus Club",
        "title": "Bonus Club: associate capture performance",
        "subtitle": "Weekly bonus club uploads with associate capture performance and store totals.",
        "viewer_title": "Associate bonus club performance",
        "viewer_note": "One row per associate, store total at bottom.",
        "upload_supported": True,
        "summary_relation": "bonus_club_summary",
    },
    6: {
        "slug": None,
        "label": "Report 6",
        "title": "Report 6",
        "subtitle": "Coming soon.",
        "viewer_title": "Report 6 data",
        "viewer_note": "This report type is not wired yet.",
        "upload_supported": False,
        "summary_relation": None,
    },
}


def report_config(number: int) -> dict[str, Any] | None:
    return REPORTS_BY_NUMBER.get(number)


def report_label(number: int) -> str:
    config = report_config(number)
    if config:
        return str(config.get("label") or f"Report {number}")
    return f"Report {number}"


def report_slug(number: int) -> str | None:
    config = report_config(number)
    if not config:
        return None
    slug = config.get("slug")
    return str(slug) if slug else None


def report_relation(number: int) -> str | None:
    config = report_config(number)
    if not config:
        return None
    relation = config.get("summary_relation")
    return str(relation) if relation else None
