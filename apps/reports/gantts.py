from __future__ import annotations

from datetime import datetime
from io import BytesIO
import re
from typing import Any

import pdfplumber

HEADER_RE = re.compile(
    r"Week:\s*(?P<date>\d{1,2}/\d{1,2}/\d{4}),\s*(?P<day>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)",
    re.I,
)
TIME_RE = re.compile(r"^(\d{1,2}:\d{2})\s*(AM|PM)$", re.I)
YELLOW = (1.0, 1.0, 0.6)
GRAY = {(0.827451, 0.827451, 0.827451), (0.662745, 0.662745, 0.662745)}


def _near_color(value: Any, expected: tuple[float, float, float], tolerance: float = 0.01) -> bool:
    return isinstance(value, (tuple, list)) and len(value) == 3 and all(abs(float(a) - b) <= tolerance for a, b in zip(value, expected))


def _clean(value: str) -> str:
    return " ".join(value.split()).strip()


def _time_minutes(value: str) -> int:
    parsed = datetime.strptime(value.upper(), "%I:%M %p")
    return parsed.hour * 60 + parsed.minute


def _time_label(minutes: int) -> str:
    hour, minute = divmod(minutes, 60)
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {suffix}"


def _row_bounds(page: pdfplumber.page.Page) -> list[tuple[float, float]]:
    values = sorted({
        (round(float(rect["top"]), 2), round(float(rect["bottom"]), 2))
        for rect in page.rects
        if float(rect["top"]) >= 35 and float(rect["bottom"]) <= 180
    })
    return values


def _header_times(page: pdfplumber.page.Page) -> list[tuple[str, float]]:
    words = page.extract_words(x_tolerance=2, y_tolerance=3)
    header_words = [
        word for word in sorted(words, key=lambda item: float(item["x0"]))
        if 20 <= float(word["top"]) <= 33
    ]
    explicit: list[tuple[str, float]] = []
    bare: list[tuple[str, float]] = []
    pending: tuple[str, float] | None = None
    for word in header_words:
        text = str(word["text"])
        center = (float(word["x0"]) + float(word["x1"])) / 2
        if re.fullmatch(r"\d{1,2}:\d{2}", text):
            bare.append((text, center))
            pending = (text, center)
        elif pending and text.upper() in {"AM", "PM"}:
            explicit.append((f"{pending[0]} {text.upper()}", center))
            pending = None
    if explicit and len(explicit) == len(bare):
        return explicit
    if not bare:
        raise ValueError("Could not find Gantt time columns.")
    start = _time_minutes(f"{bare[0][0]} AM")
    return [(_time_label(start + index * 30), center) for index, (_value, center) in enumerate(bare)]


def _assignment_text(page: pdfplumber.page.Page, rect: dict[str, Any]) -> str:
    crop = page.crop((float(rect["x0"]), float(rect["top"]), float(rect["x1"]), float(rect["bottom"])))
    return _clean(crop.extract_text(x_tolerance=2, y_tolerance=3) or "")


def parse_gantt_report(content: bytes, source_name: str = "") -> dict[str, Any]:
    with pdfplumber.open(BytesIO(content)) as pdf:
        if not pdf.pages:
            raise ValueError("The Gantt PDF has no pages.")
        page = pdf.pages[0]
        text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
        match = HEADER_RE.search(text)
        if not match:
            raise ValueError("Could not find the Gantt report date and day.")
        week_end = datetime.strptime(match.group("date"), "%m/%d/%Y").date()
        day_offsets = {"Monday": 5, "Tuesday": 4, "Wednesday": 3, "Thursday": 2, "Friday": 1, "Saturday": 0, "Sunday": 6}
        day_date = week_end.fromordinal(week_end.toordinal() - day_offsets[match.group("day").title()])
        header_times = _header_times(page)
        centers = [center for _label, center in header_times]
        boundaries = [centers[0] - (centers[1] - centers[0]) / 2]
        boundaries.extend((left + right) / 2 for left, right in zip(centers, centers[1:]))
        boundaries.append(centers[-1] + (centers[-1] - centers[-2]) / 2)
        row_bounds = _row_bounds(page)
        words = page.extract_words(x_tolerance=2, y_tolerance=3)
        employees: list[dict[str, Any]] = []
        for top, bottom in row_bounds[1:]:
            name_words = [
                word for word in words
                if top - 1 <= float(word["top"]) <= bottom + 1 and float(word["x0"]) < boundaries[0] - 2
            ]
            name = _clean(" ".join(str(word["text"]) for word in name_words)).lstrip("*")
            if not name:
                continue
            assignments: list[dict[str, Any]] = []
            for rect in page.rects:
                rect_top, rect_bottom = float(rect["top"]), float(rect["bottom"])
                if abs(rect_top - top) > 1.5 or abs(rect_bottom - bottom) > 1.5:
                    continue
                color = rect.get("non_stroking_color")
                if _near_color(color, YELLOW) or color in GRAY or color in (None, 0):
                    continue
                label = _assignment_text(page, rect)
                if not label:
                    continue
                start_index = min(range(len(boundaries) - 1), key=lambda index: abs(float(rect["x0"]) - boundaries[index]))
                end_index = min(range(1, len(boundaries)), key=lambda index: abs(float(rect["x1"]) - boundaries[index]))
                start_minutes = _time_minutes(header_times[start_index][0])
                end_minutes = _time_minutes(header_times[end_index - 1][0]) + 30
                if end_minutes <= start_minutes:
                    end_minutes += 12 * 60
                assignments.append({
                    "label": label,
                    "start": _time_label(start_minutes),
                    "end": _time_label(end_minutes),
                    "start_minutes": start_minutes,
                    "end_minutes": end_minutes,
                })
            employees.append({"name": name, "manager": name_words[0]["text"].startswith("*"), "assignments": assignments})
    if not employees:
        raise ValueError("No employee rows were found in the Gantt PDF.")
    return {
        "day": match.group("day").title(),
        "day_date": day_date.isoformat(),
        "week_end": week_end.isoformat(),
        "time_slots": [label for label, _center in header_times],
        "employees": employees,
        "source_name": source_name,
    }
