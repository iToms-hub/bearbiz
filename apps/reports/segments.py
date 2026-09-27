from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
import re
from typing import Any

import pdfplumber


DISPLAY_FIELDS = (
    ("Time", 0),
    ("Total Sales", 1),
    ("% to Target", 2),
    ("Traffic Leverage", 10),
    ("Conversion", 11),
    ("DPT", 20),
    ("STAR", 30),
)

DATE_RANGE_RE = re.compile(r"Statistics\s+(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})", re.I)
DAY_RE = re.compile(r"\b(sunday|monday|tuesday|wednesday|thursday|friday|saturday)\b", re.I)
DAY_OFFSETS = {"Sunday": 0, "Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4, "Friday": 5, "Saturday": 6}


def _clean(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if "$" in text:
        text = re.sub(r"\s+", "", text)
    elif "%" in text:
        text = re.sub(r"\s+", "", text)
    return text


def _coordinate_rows(pdf: pdfplumber.pdf.PDF) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for page in pdf.pages:
        tables = page.extract_tables(table_settings={"vertical_strategy": "text", "horizontal_strategy": "lines"})
        if not tables:
            continue
        for raw in tables[0]:
            if len(raw) < 3:
                continue
            first = _clean(raw[0])
            second = _clean(raw[1]) if len(raw) > 1 else ""
            time = re.sub(r"\s+", "", f"{first} {second}")
            if not re.match(r"^\d{1,2}:\d{2}(AM|PM)$", time, re.I):
                continue
            time = time[:-2] + " " + time[-2:].upper()
            values = [_clean(value) for value in raw]
            rows[time] = values
    return rows


def _coordinate_requested_values(source_row: list[str]) -> dict[int, str]:
    result: dict[int, str] = {}
    result[1], result[2] = source_row[2], source_row[3]
    percent = lambda value: "%" in value
    for index in range(10, len(source_row) - 3):
        if all(percent(source_row[index + offset]) for offset in range(3)) and source_row[index + 3].replace(",", "").isdigit():
            result[10], result[11] = source_row[index], source_row[index + 1]
            break
    for index in range(16, len(source_row) - 3):
        if source_row[index].startswith("$") and source_row[index + 1].startswith("$") and re.match(r"^[\d.]+$", source_row[index + 2]):
            result[20], result[30] = source_row[index], source_row[index + 10]
            break
    return result


def _table_rows(pdf: pdfplumber.pdf.PDF) -> tuple[list[str], list[list[str]]]:
    coordinate_rows = _coordinate_rows(pdf)
    headers: list[str] = []
    rows: list[list[str]] = []
    for page in pdf.pages:
        for table in page.extract_tables():
            if not table:
                continue
            first = _clean(table[0][0])
            if re.match(r"^\d{1,2}:\d{2}\s+(AM|PM)$", first, re.I):
                rows.append([_clean(cell) for cell in table[0]])
                continue
            if first.lower() == "time":
                first_row = [_clean(cell) for cell in table[0]]
                if len(first_row) >= 2 and re.match(r"^\d{1,2}:\d{2}\s+(AM|PM)$", first_row[0], re.I):
                    rows.append(first_row)
                    continue
                if not headers:
                    headers = first_row
                for row in table[1:]:
                    values = [_clean(cell) for cell in row]
                    if values and re.match(r"^\d{1,2}:\d{2}\s+(AM|PM)$", values[0], re.I):
                        rows.append(values)
            elif table and _clean(table[0][0]).lower() == "time period":
                # The hourly table can be split across pages; page 1 carries its first row.
                continue
    if not headers or not rows:
        raise ValueError("Could not find the hourly Time table in this PDF.")
    expected_times = [
        "2:00 AM", "4:00 AM", "6:00 AM", "8:00 AM", "10:00 AM", "12:00 PM",
        "2:00 PM", "4:00 PM", "6:00 PM", "8:00 PM", "10:00 PM", "12:00 AM", "2:00 AM",
    ]
    zero_template = next((row for row in rows if row[0] in {"6:00 AM", "10:00 PM", "2:00 AM"} and all(value in {"$0", "0", "0.0", "0%", "0.0%", "0.00%", "0.00", "$0.00"} for value in row[1:])), None)
    if zero_template:
        queues: dict[str, list[list[str]]] = {}
        for row in rows:
            queues.setdefault(row[0], []).append(row)
        completed = []
        for time in expected_times:
            if queues.get(time):
                completed.append(queues[time].pop(0))
            else:
                generated = [time, *zero_template[1:]]
                source_row = coordinate_rows.get(time)
                if source_row:
                    for canonical_index, value in _coordinate_requested_values(source_row).items():
                        generated[canonical_index] = value
                completed.append(generated)
        rows = completed
    return headers, rows


def parse_segment_report(file_bytes: bytes, source_name: str = "") -> dict[str, Any]:
    match = DATE_RANGE_RE.search("")
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        full_text = "\n".join(page.extract_text(x_tolerance=2, y_tolerance=3) or "" for page in pdf.pages)
        match = DATE_RANGE_RE.search(full_text)
        if not match:
            raise ValueError("Could not find the report date range.")
        start = datetime.strptime(match.group(1), "%m/%d/%Y").date()
        end = datetime.strptime(match.group(2), "%m/%d/%Y").date()
        headers, rows = _table_rows(pdf)

    day_match = DAY_RE.search(source_name)
    if not day_match:
        raise ValueError("The filename must identify the opportunity day.")
    day = day_match.group(1).title()
    day_date = start + timedelta(days=DAY_OFFSETS[day])
    return {
        "day": day,
        "day_date": day_date.isoformat(),
        "period_start": start.isoformat(),
        "week_end": end.isoformat(),
        "headers": headers,
        "rows": [{"values": row, "raw_values": row} for row in rows],
    }


def display_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    displayed = []
    for row in report["rows"]:
        values = row.get("values", [])
        time_value = values[0] if values else ""
        match = re.match(r"^(\d{1,2}):\d{2}\s+(AM|PM)$", str(time_value), re.I)
        if not match:
            continue
        hour = int(match.group(1)) % 12
        if match.group(2).upper() == "PM":
            hour += 12
        if not (8 <= hour <= 22):
            continue
        indexes = [index for _, index in DISPLAY_FIELDS] if len(values) > max(index for _, index in DISPLAY_FIELDS) else list(range(min(len(values), len(DISPLAY_FIELDS))))
        projected = [values[index] if index < len(values) else "" for index in indexes]
        projected.extend([""] * (len(DISPLAY_FIELDS) - len(projected)))
        displayed.append({"values": projected, "highlight": False})

    ranking_indexes = {"traffic": 3, "conversion": 4, "dpt": 5, "star": 6}
    active = []
    for position, row in enumerate(displayed):
        values = row["values"]
        try:
            metrics = {
                "sales": float(re.sub(r"[$,%]", "", values[1]).replace(",", "")),
                **{
                    name: float(re.sub(r"[$,%]", "", values[index]).replace(",", ""))
                    for name, index in ranking_indexes.items()
                },
            }
        except (TypeError, ValueError):
            continue
        if any(metrics.values()) and metrics["sales"] != 0:
            active.append((position, metrics))

    if active:
        ranks: dict[int, dict[str, int]] = {position: {} for position, _ in active}
        for metric in ranking_indexes:
            descending_is_worse = metric == "star"
            ordered = sorted(active, key=lambda item: item[1][metric], reverse=descending_is_worse)
            for rank, (position, _metrics) in enumerate(ordered, start=1):
                ranks[position][metric] = rank
        worst_positions = sorted(
            (sum(metric_ranks.values()), position) for position, metric_ranks in ranks.items()
        )[:3]
        for _score, position in worst_positions:
            displayed[position]["highlight"] = True
    return displayed
