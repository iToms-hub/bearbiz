from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from ..base import ParsedReport
from ..fiscal import as_dict, calculate_fiscal_week
from ..registry import register


class SegmentsReport:
    slug = "segments"
    display_name = "Segments"
    parse_version = 2

    _JOB_TITLE_LABELS = {"SL", "AWM", "CWM"}
    _TRAILING_LABELS = {"Act", "Var", "% Target"}
    _HEADER_LABELS = {
        "Segment Accountability Report",
        "Name / Job Title",
        "# Seg",
        "% Total",
        "Success Segments",
        "% Success",
        "Store Sales",
        "Sales Trans",
        "Conversion",
        "DPT",
        "UPT",
        "Visit Value",
    }
    _FOOTER_RE = re.compile(
        r"(?P<start>\d{1,2}/\d{1,2}/\d{4})\s*-\s*(?P<end>\d{1,2}/\d{1,2}/\d{4})"
    )
    _VISIBLE_HEADERS = [
        "Name",
        "#seg",
        "% Total",
        "Success Segments",
        "% Success",
        "Store Sales",
        "Sales Trans",
        "Conversion",
        "DPT",
        "UPT",
    ]

    def parse(self, raw_text: str) -> ParsedReport:
        lines = [line.strip() for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").splitlines() if line.strip()]
        period_start, period_end = self._extract_period(lines)
        rows = self._extract_rows(lines)
        manager_rows = [row for row in rows if row.get("row_kind") == "manager"]
        store_total = next((row for row in rows if row.get("row_kind") == "store_total"), None)
        fiscal = self._build_fiscal_payload(period_start, period_end)
        payload = {
            "parse_version": self.parse_version,
            "raw_text": raw_text,
            "report_title": "Segment Accountability Report",
            "location": self._extract_location(lines),
            "fiscal": fiscal,
            "summary_rows": rows,
            "manager_rows": manager_rows,
            "store_total": store_total,
            "viewer": {
                "headers": list(self._VISIBLE_HEADERS),
                "rows": [self._viewer_row(row) for row in manager_rows],
            },
        }
        return ParsedReport(
            report_type=self.slug,
            source_name="segments.pdf",
            period_start=period_start.isoformat() if period_start else None,
            period_end=period_end.isoformat() if period_end else None,
            payload=payload,
            raw_rows=rows,
        )

    @classmethod
    def _extract_period(cls, lines: list[str]) -> tuple[date | None, date | None]:
        for line in lines:
            match = cls._FOOTER_RE.search(line)
            if not match:
                continue
            start = cls._parse_date(match.group("start"))
            end = cls._parse_date(match.group("end"))
            if start and end:
                return start, end
        return None, None

    @classmethod
    def _extract_location(cls, lines: list[str]) -> str:
        for line in lines[1:4]:
            if not cls._FOOTER_RE.search(line) and line not in cls._HEADER_LABELS:
                return line
        return ""

    @classmethod
    def _extract_rows(cls, lines: list[str]) -> list[dict[str, Any]]:
        table_start = next(
            (
                index
                for index, line in enumerate(lines)
                if "Name / Job Title" in line and "Visit Value" in line
            ),
            None,
        )
        if table_start is None:
            table_start = next((index for index, line in enumerate(lines) if line == "Visit Value"), None)
        if table_start is None:
            return []
        rows: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for line in lines[table_start + 1 :]:
            if cls._is_footer_line(line):
                break
            if cls._is_header_line(line):
                continue

            inline_row = cls._parse_inline_row(line)
            if inline_row is not None:
                if current is not None:
                    rows.append(cls._finalize_row(current))
                    current = None
                rows.append(cls._finalize_row(inline_row))
                continue

            if current is None:
                if cls._is_row_start(line):
                    current = {
                        "name": line,
                        "values": [],
                        "job_title": "",
                    }
                continue

            if line in cls._JOB_TITLE_LABELS and not current["job_title"]:
                current["job_title"] = line
                continue

            values = cls._parse_value_tokens(line)
            if not values:
                continue
            current["values"].extend(values)
            if len(current["values"]) >= 10:
                rows.append(cls._finalize_row(current))
                current = None
                continue
        if current is not None:
            rows.append(cls._finalize_row(current))
        return rows

    @classmethod
    def _parse_inline_row(cls, line: str) -> dict[str, Any] | None:
        tokens = cls._split_tokens(line)
        if not tokens:
            return None
        if tokens[0] in cls._JOB_TITLE_LABELS or tokens[0] in cls._TRAILING_LABELS:
            return None
        if cls._is_header_line(line):
            return None
        if not any(cls._looks_like_value_token(token) for token in tokens):
            return None
        name_tokens: list[str] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token in cls._JOB_TITLE_LABELS or token in cls._TRAILING_LABELS or cls._looks_like_value_token(token):
                break
            name_tokens.append(token)
            index += 1
        if not name_tokens:
            return None
        values = cls._parse_value_tokens(" ".join(tokens[index:]))
        if not values:
            return None
        return {
            "name": " ".join(name_tokens).strip(),
            "values": values,
            "job_title": "",
        }

    @classmethod
    def _finalize_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        values = list(row.get("values", []))
        if len(values) < 10:
            values.extend([""] * (10 - len(values)))
        visible_values = values[:9]
        row_kind = "store_total" if str(row.get("name", "")).strip().lower() == "store total" else "manager"
        metrics = {
            "segment_count": cls._to_int(values[0]),
            "segment_total_pct": cls._to_float(values[1]),
            "success_segments": cls._to_int(values[2]),
            "success_pct": cls._to_float(values[3]),
            "store_sales": values[4],
            "sales_trans": cls._to_int(values[5]),
            "conversion": cls._to_float(values[6]),
            "dpt": cls._to_float(values[7]),
            "upt": cls._to_float(values[8]),
            "visit_value": values[9],
        }
        return {
            "name": row.get("name", ""),
            "job_title": row.get("job_title", ""),
            "row_kind": row_kind,
            "values": values,
            "visible_values": visible_values,
            "metrics": metrics,
            "viewer": {
                "values": [row.get("name", ""), *visible_values],
            },
        }

    @classmethod
    def _viewer_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        viewer = row.get("viewer") if isinstance(row, dict) else None
        if isinstance(viewer, dict):
            return viewer
        return {"values": [row.get("name", ""), *list(row.get("visible_values", []))]}

    @classmethod
    def _build_fiscal_payload(cls, period_start: date | None, period_end: date | None) -> dict[str, object] | None:
        if not period_start or not period_end:
            return None

        from apps.core.models import FiscalYearSettings

        settings = FiscalYearSettings.current()
        if getattr(settings, "fiscal_year_start_date", None):
            return {
                "fiscal_year": settings.fiscal_year_for_date(period_end),
                "week_ending_date": period_end.isoformat(),
                "fiscal_week_number": settings.fiscal_week_for_date(period_end),
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            }
        try:
            return as_dict(calculate_fiscal_week(period_start, period_end))
        except Exception:
            return None

    @staticmethod
    def _is_row_start(line: str) -> bool:
        lowered = line.lower().strip()
        if not lowered or lowered in {label.lower() for label in SegmentsReport._HEADER_LABELS}:
            return False
        first_token = line.split()[0] if line.split() else ""
        if first_token in SegmentsReport._JOB_TITLE_LABELS or first_token in SegmentsReport._TRAILING_LABELS:
            return False
        if lowered in {label.lower() for label in SegmentsReport._JOB_TITLE_LABELS | SegmentsReport._TRAILING_LABELS}:
            return False
        if lowered.startswith(("page ", "socal/vegas", "north america", "company total", "confidential", "run on", "fw:", "segment accountability")):
            return False
        if SegmentsReport._looks_like_value_token(line):
            return False
        return any(ch.isalpha() for ch in line)

    @staticmethod
    def _is_header_line(line: str) -> bool:
        lowered = line.lower().strip()
        if not lowered:
            return True
        if lowered.startswith(("name / job title", "segments trans", "store sales sales", "name/job title")):
            return True
        return line in SegmentsReport._HEADER_LABELS

    @staticmethod
    def _split_tokens(text: str) -> list[str]:
        tokens: list[str] = []
        for token in text.split():
            if token == "%" and tokens:
                tokens[-1] = f"{tokens[-1]} %"
                continue
            tokens.append(token)
        return tokens

    @classmethod
    def _parse_value_tokens(cls, text: str) -> list[str]:
        tokens = []
        for token in cls._split_tokens(text):
            if token in cls._JOB_TITLE_LABELS or token in cls._TRAILING_LABELS:
                continue
            tokens.append(token)
        return tokens

    @staticmethod
    def _is_footer_line(line: str) -> bool:
        lowered = line.lower()
        return lowered.startswith(("page ", "segment accountability - lw-mtd-qtd", "build-a-bear", "socal/vegas", "north america", "company total", "confidential", "run on"))

    @staticmethod
    def _looks_like_value_token(token: str) -> bool:
        stripped = token.strip().replace(",", "")
        if not stripped:
            return False
        if stripped in {"-", "N/A", "n/a", "NaN", "nan", "Infinity", "inf"}:
            return True
        if stripped.startswith(("$", "-", "(", "+")):
            return True
        if stripped.endswith("%"):
            return True
        return stripped[0:1].isdigit()

    @staticmethod
    def _to_float(value: str) -> float | None:
        text = value.strip().replace(",", "").replace("$", "")
        if not text or text.lower() in {"-", "n/a", "nan", "infinity", "inf"}:
            return None
        if text.endswith("%"):
            text = text[:-1]
        if text.startswith("(") and text.endswith(")"):
            text = f"-{text[1:-1]}"
        try:
            numeric = float(text)
        except ValueError:
            return None
        return numeric if numeric == numeric and numeric not in {float("inf"), float("-inf")} else None

    @classmethod
    def _to_int(cls, value: str) -> int | None:
        numeric = cls._to_float(value)
        if numeric is None:
            return None
        return int(numeric)

    @staticmethod
    def _parse_date(value: str) -> date | None:
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None


def load_segments_report() -> SegmentsReport:
    report = SegmentsReport()
    register(report)
    return report


load_segments_report()
