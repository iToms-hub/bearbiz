from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
import re
from typing import Any

import pdfplumber

DAY_NAMES = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
DAY_ROW_RE = re.compile(
    r"^(?P<day>Sun|Mon|Tue|Wed|Thu|Fri|Sat)\s+"
    r"(?P<store_sales>\$[\d,]+)\s+"
    r"(?P<traffic>[\d,]+)\s+"
    r"(?P<star>[\d.]+)\s+"
    r"(?P<trans>[\d,]+)\s+"
    r"(?P<conversion>[\d.]+)\s+%\s+"
    r"(?P<dpt>\$[\d.]+)\s+"
    r"(?P<upt>[\d.]+)"
    r"(?:\s+(?P<missed_customers>[\d,]+)\s+(?P<missed_store_sales>\$[\d,]+))?$"
)
SUMMARY_ROW_RE = re.compile(
    r"^(?P<label>Total|Target)\s+"
    r"(?P<store_sales>\$[\d,]+)\s+"
    r"(?P<traffic>[\d,]+)\s+"
    r"(?P<star>[\d.]+)\s+"
    r"(?P<conversion>[\d.]+)\s+%\s+"
    r"(?P<dpt>\$[\d.]+)\s+"
    r"(?P<upt>[\d.]+)"
    r"(?:\s+(?P<missed_customers>[\d,]+)\s+(?P<missed_store_sales>\$[\d,]+))?$"
)


def _clean_number(value: str | None) -> str:
    return (value or "").strip()


def _row(match: re.Match[str]) -> dict[str, Any]:
    data = {key: _clean_number(value) for key, value in match.groupdict().items()}
    data["has_missed_opportunity"] = bool(data.get("missed_customers") or data.get("missed_store_sales"))
    return data


def parse_missed_opportunity_text(text: str, source_name: str = "") -> dict[str, Any]:
    week_match = re.search(r"Week:\s*(\d+)\.\s*Week Ending Date:\s*(\d{1,2}/\d{1,2}/\d{4})", text)
    if not week_match:
        raise ValueError("Could not find the fiscal week and week-ending date.")

    day_rows: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        day_match = DAY_ROW_RE.match(line)
        if day_match:
            day_rows.append(_row(day_match))
            continue
        summary_match = SUMMARY_ROW_RE.match(line)
        if summary_match:
            summaries[summary_match.group("label").lower()] = _row(summary_match)

    if tuple(row["day"] for row in day_rows) != DAY_NAMES:
        raise ValueError("Expected seven daily rows in Sun–Sat order.")
    if "total" not in summaries or "target" not in summaries:
        raise ValueError("Could not find both Total and Target rows.")

    week_end = datetime.strptime(week_match.group(2), "%m/%d/%Y").date()
    return {
        "fiscal_week": int(week_match.group(1)),
        "week_end": week_end.isoformat(),
        "days": day_rows,
        "total": summaries["total"],
        "target": summaries["target"],
        "source_name": source_name,
    }


def parse_missed_opportunity_report(content: bytes, source_name: str = "") -> dict[str, Any]:
    with pdfplumber.open(BytesIO(content)) as pdf:
        text = "\n".join(page.extract_text(x_tolerance=2, y_tolerance=3) or "" for page in pdf.pages)
    return parse_missed_opportunity_text(text, source_name=source_name)
