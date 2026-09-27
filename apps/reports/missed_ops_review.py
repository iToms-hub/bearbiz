from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .models import GanttReport, MissedOpportunityReport, SegmentReport
from .segment_views import _opportunity_days
from .segments import display_rows

DEFAULT_REVIEW_CRITERIA = {
    "leverage_below": Decimal("0"),
    "dpt_below": Decimal("45"),
    "conversion_below": Decimal("15"),
    "star_above": Decimal("12"),
}


def _minutes(value: str) -> int:
    from datetime import datetime
    parsed = datetime.strptime(value.strip().upper(), "%I:%M %p")
    return parsed.hour * 60 + parsed.minute


def _decimal(value: str) -> Decimal | None:
    cleaned = str(value or "").replace("$", "").replace("%", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _floor_leader(gantt: GanttReport | None, segment: str) -> str:
    if not gantt:
        return "Gantt needed"
    try:
        minute = _minutes(segment)
    except ValueError:
        return "Not identified"
    names: list[str] = []
    for employee in gantt.employees or []:
        for assignment in employee.get("assignments", []):
            if assignment.get("label") != "Floor Leader":
                continue
            start = assignment.get("start_minutes")
            end = assignment.get("end_minutes")
            if start is None or end is None:
                try:
                    start, end = _minutes(assignment["start"]), _minutes(assignment["end"])
                except (KeyError, TypeError, ValueError):
                    continue
            if int(start) <= minute < int(end):
                names.append(str(employee.get("name", "")).lstrip("*"))
                break
    return ", ".join(dict.fromkeys(name for name in names if name)) or "Not identified"


def _segment_values(row: dict[str, Any]) -> dict[str, str]:
    values = list(row.get("values") or [])
    return {
        "segment": str(values[0]) if len(values) > 0 else "",
        "leverage": str(values[3]) if len(values) > 3 else "",
        "conversion": str(values[4]) if len(values) > 4 else "",
        "dpt": str(values[5]) if len(values) > 5 else "",
        "star": str(values[6]) if len(values) > 6 else "",
    }


def _underperformance(values: dict[str, str], criteria: dict[str, Decimal]) -> tuple[dict[str, bool], list[str]]:
    leverage = _decimal(values["leverage"])
    dpt = _decimal(values["dpt"])
    conversion = _decimal(values["conversion"])
    star = _decimal(values["star"])
    flags = {
        "leverage": leverage is not None and leverage < criteria["leverage_below"],
        "dpt": dpt is not None and dpt < criteria["dpt_below"],
        "conversion": conversion is not None and conversion < criteria["conversion_below"],
        "star": star is not None and star > criteria["star_above"],
    }
    reasons = []
    if flags["leverage"]:
        reasons.append("Leverage below threshold")
    if flags["dpt"]:
        reasons.append("DPT below threshold")
    if flags["conversion"]:
        reasons.append("Conversion below threshold")
    if flags["star"]:
        reasons.append("STAR above threshold")
    return flags, reasons


def build_review_rows(report: MissedOpportunityReport | None, criteria: dict[str, Decimal] | None = None) -> list[dict[str, Any]]:
    if not report:
        return []
    active_criteria = {**DEFAULT_REVIEW_CRITERIA, **(criteria or {})}
    required_days = _opportunity_days(report)
    segment_reports = {item.day_of_week: item for item in SegmentReport.objects.filter(fiscal_year=report.fiscal_year, fiscal_week=report.fiscal_week)}
    gantts = {item.day_of_week: item for item in GanttReport.objects.filter(fiscal_year=report.fiscal_year, fiscal_week=report.fiscal_week)}
    rows: list[dict[str, Any]] = []
    for day in required_days:
        segment_report = segment_reports.get(day)
        if not segment_report:
            continue
        for raw_row in display_rows({"rows": segment_report.rows}):
            if not raw_row.get("highlight"):
                continue
            values = _segment_values(raw_row)
            flags, reasons = _underperformance(values, active_criteria)
            rows.append({
                "date": segment_report.day_date.strftime("%m/%d/%y"),
                "day": day,
                "floor_leader": _floor_leader(gantts.get(day), values["segment"]),
                "reasons": reasons,
                "flags": flags,
                **values,
            })
    return rows
