from __future__ import annotations

import re
from calendar import month_abbr
from datetime import timedelta
from typing import Any

from ..base import ParsedReport



class PartiesReport:
    slug = "parties"
    display_name = "Parties"
    parse_version = 1
    groups = ("ttl_held", "comp_held", "ttl_booked")

    def parse(self, raw_text: str) -> ParsedReport:
        fiscal_match = re.search(r"['’]?(\d{2})\s+FW\s*(\d+)", raw_text, re.I)
        fiscal = {
            "fiscal_year": 2000 + int(fiscal_match.group(1)) if fiscal_match else None,
            "fiscal_week_number": int(fiscal_match.group(2)) if fiscal_match else None,
        }
        rows: list[dict[str, Any]] = []
        source_month: str | None = None
        source_months = {month_abbr[index].lower(): month_abbr[index] for index in range(1, 13)}
        for line in raw_text.replace("\r", "").splitlines():
            cells = self._cells(line)
            week_index = next((i for i, cell in enumerate(cells) if re.fullmatch(r"wk\d+", cell, re.I)), None)
            marker = next((source_months[cell[:3].lower()] for cell in cells if cell[:3].lower() in source_months), None)
            if marker:
                source_month = marker
            if week_index is None:
                continue
            prefix = cells[:week_index]
            status = next((cell.upper() for cell in prefix if cell.upper() in {"ACT", "FCST"}), None)
            values = cells[week_index + 1:]
            if len(values) < 3:
                continue
            values = (values + [""] * 9)[:9]
            row_source_month = source_month or self._previous_month(source_months, raw_text)
            month = self._fiscal_month(row_source_month, len(rows))
            week_in_month = sum(1 for row in rows if row.get("fiscal_month") == month) + 1
            metrics = {
                group: self._metric(values[index:index + 3])
                for index, group in enumerate(self.groups)
            }
            week_number = len(rows) + 1
            week_date = ""
            try:
                from apps.core.models import FiscalYearSettings

                start_date = FiscalYearSettings.current().fiscal_year_start_date
                if start_date:
                    week_date = (start_date + timedelta(weeks=week_number - 1)).isoformat()
            except Exception:
                pass
            rows.append({
                "status": status,
                "week": cells[week_index].lower(),
                "week_number": week_number,
                "week_date": week_date,
                "fiscal_month": month,
                "source_month": row_source_month,
                "week_in_month": week_in_month,
                "metrics": metrics,
                "raw_cells": cells,
            })
        payload = {"parse_version": self.parse_version, "fiscal": fiscal, "rows": rows, "raw_text": raw_text}
        return ParsedReport("parties", "parties.pdf", None, None, payload, rows)

    @staticmethod
    def _cells(line: str) -> list[str]:
        if "|" in line:
            cells = [cell.strip() for cell in line.split("|") if cell.strip()]
            if cells and " " in cells[0]:
                cells = cells[0].split() + cells[1:]
            return cells
        return line.split()

    @staticmethod
    def _fiscal_position(index: int) -> tuple[int, int]:
        month = 1
        remaining = index
        while remaining >= (5 if month in {2, 5, 8, 11} else 4) and month < 12:
            remaining -= 5 if month in {2, 5, 8, 11} else 4
            month += 1
        return month, remaining + 1

    @classmethod
    def _fiscal_month(cls, source_month: str | None, index: int) -> int:
        try:
            from apps.core.models import FiscalYearSettings
            pattern = str(FiscalYearSettings.current().calendar_pattern or "454")
        except Exception:
            pattern = "454"
        month = 1
        remaining = index
        for weeks in (int(value) for _ in range(4) for value in pattern):
            if remaining < weeks:
                return month
            remaining -= weeks
            month += 1
        return 12

    @staticmethod
    def _previous_month(source_months: dict[str, str], raw_text: str) -> str | None:
        markers = [source_months[cell[:3].lower()] for cell in raw_text.split() if cell[:3].lower() in source_months]
        if not markers:
            return None
        current = next(month for month in range(1, 13) if month_abbr[month] == markers[0])
        return month_abbr[12 if current == 1 else current - 1]

    @staticmethod
    def _metric(values: list[str]) -> dict[str, Any]:
        raw = (values + [""] * 3)[:3]
        return {"current": PartiesReport._number(raw[0]), "previous": PartiesReport._number(raw[1]), "variance": PartiesReport._number(raw[2]), "raw_current": raw[0], "raw_previous": raw[1], "raw_variance": raw[2]}

    @staticmethod
    def _number(value: str) -> int | None:
        text = value.strip()
        if not text or text.upper() in {"#N/A", "N/A", "-", "—"}:
            return None
        try:
            return int(text.replace(",", "").replace("+", ""))
        except ValueError:
            return None


report = PartiesReport()
