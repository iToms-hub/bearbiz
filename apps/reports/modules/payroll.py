from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any

from ..base import ParsedReport
from ..registry import register


class PayrollReport:
    slug = "payroll"
    display_name = "Payroll"
    parse_version = 2
    columns = (
        "Week", "HOO", "Sales Plan", "Trend % from Bearnet", "Actual Sales",
        "SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT",
        "Total Hours Actual + Scheduled", "Labor Calculator Target Hours",
        "Current +/-", "NOTES",
    )
    display_columns = (
        "Week", "Week Ending", "Sales Plan", "Trend", "Actual Sales",
        "SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT",
        "Total Hours", "Target Hours", "Current +/-",
    )
    display_source_columns = (
        "Week", "NOTES", "Sales Plan", "Trend % from Bearnet", "Actual Sales",
        "SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT",
        "Total Hours Actual + Scheduled", "Labor Calculator Target Hours", "Current +/-",
    )

    def parse(self, raw_text: str) -> ParsedReport:
        lines = [line.strip() for line in raw_text.replace("\r", "").split("\n") if line.strip()]
        header_index = next((i for i, line in enumerate(lines) if self._header(line)), -1)
        rows: list[dict[str, Any]] = []
        footer: dict[str, Any] = {}
        source_date: str | None = None
        if header_index >= 0:
            for line in lines[header_index + 1:]:
                cells = self._cells(line)
                if not cells:
                    continue
                if self._is_footer(cells):
                    footer.update(self._footer(cells))
                    continue
                # pdfplumber collapses this PDF's table into whitespace-only
                # lines. Normalize before checking the week number so those
                # rows are not silently discarded.
                cells = self._normalize_row(cells)
                if len(cells) >= 3 and self._is_week(cells[0]):
                    row = {column: self._value(cells[i]) if i < len(cells) else None for i, column in enumerate(self.columns)}
                    row["raw_cells"] = cells
                    rows.append(row)
                    candidate = self._date(row.get("NOTES"))
                    source_date = source_date or candidate
        if source_date is None:
            source_date = self._date(raw_text)
        if not footer:
            footer = self._fallback_footer(raw_text)
        week_value = next((row.get("Week") for row in rows if row.get("Week") not in (None, "")), None)
        payload = {
            "parse_version": self.parse_version,
            "raw_text": raw_text,
            "columns": list(self.columns),
            "rows": rows,
            "monthly_summary": footer,
            "source_date": source_date,
            "source_week": week_value,
        }
        return ParsedReport("payroll", "payroll.pdf", source_date, source_date, payload, rows)

    @staticmethod
    def _header(line: str) -> bool:
        normalized = re.sub(r"[^a-z]", "", line.lower())
        return ("laborcalculator" in normalized and "actualsales" in normalized) or (
            "actualsales" in normalized and "notes" in normalized
        ) or line.lower().startswith("w kee ")

    @staticmethod
    def _cells(line: str) -> list[str]:
        if "|" in line:
            return [cell.strip() for cell in line.split("|")]
        if "\t" in line:
            return [cell.strip() for cell in line.split("\t")]
        return [cell.strip() for cell in re.split(r"\s{2,}", line) if cell.strip()]

    @classmethod
    def _normalize_row(cls, cells: list[str]) -> list[str]:
        """Handle pdfplumber's flattened whitespace-only table extraction."""
        if len(cells) != 1:
            return cells
        tokens = re.findall(
            r"(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|-?\d+(?:\.\d+)?%?|\$?-?[\d,]+(?:\.\d+)?|\S+)",
            cells[0],
        )
        if len(tokens) < 3:
            return tokens
        # A date terminates every historical row. The optional trend column is
        # the only percent token; absent cells are represented as nulls.
        date_index = next((i for i, token in enumerate(tokens) if cls._date(token)), len(tokens) - 1)
        body, notes = tokens[:date_index], tokens[date_index]
        result: list[str] = body[:3]
        if len(body) > 3 and body[3].endswith("%"):
            result.append(body[3]); body = body[:3] + body[4:]
        else:
            result.append("")
        result.append(body[3] if len(body) > 3 else "")
        tail = body[4:]
        # Daily hours plus the three calculated columns are the final ten
        # cells. Missing cells in the source PDF are blank, not shifted left.
        result.extend([""] * max(0, 10 - len(tail)))
        result.extend(tail[-10:])
        return result[:15] + [notes]

    @staticmethod
    def _fallback_footer(raw_text: str) -> dict[str, Any]:
        footer_line = next(
            (line.strip() for line in raw_text.splitlines() if line.strip().startswith("$")),
            "",
        )
        match = re.match(r"\$(\d[\d,]*)\s+\$(\d[\d,]*)", footer_line)
        result: dict[str, Any] = {}
        if match:
            result["Sales Plan"] = int(match.group(1).replace(",", ""))
            result["Actual Sales"] = int(match.group(2).replace(",", ""))
        target = re.search(r"Hours\s+@\s+101%:\s+([\d.]+)", raw_text)
        if target:
            result["Labor Calculator Target Hours"] = float(target.group(1))
        return result

    @staticmethod
    def _is_week(value: object) -> bool:
        return bool(re.fullmatch(r"(?:week\s*)?\d+", str(value or "").strip(), re.I))

    @staticmethod
    def _is_footer(cells: list[str]) -> bool:
        text = " ".join(cells).lower()
        return any(label in text for label in ("actual sales", "sales plan", "hours at", "currently")) and not PayrollReport._is_week(cells[0])

    @staticmethod
    def _footer(cells: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if len(cells) >= 2:
            result[str(cells[0])] = PayrollReport._value(" ".join(cells[1:]))
        return result

    @staticmethod
    def _value(value: object) -> Any:
        text = str(value or "").strip()
        if not text or text in {"-", "—", "–"}:
            return None
        numeric = text.replace(",", "").replace("$", "").replace("%", "")
        if re.fullmatch(r"-?\d+", numeric):
            return int(numeric)
        if re.fullmatch(r"-?\d+\.\d+", numeric):
            return float(numeric)
        return text

    @staticmethod
    def _date(value: object) -> str | None:
        match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\b", str(value or ""))
        if not match:
            return None
        text = match.group(1)
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                pass
        return None


def load_payroll_report() -> PayrollReport:
    report = PayrollReport()
    register(report)
    return report


load_payroll_report()
