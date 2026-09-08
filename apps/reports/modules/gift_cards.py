from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from ..base import ParsedReport
from ..fiscal import as_dict, calculate_fiscal_week
from ..registry import register


class GiftCardsReport:
    slug = "gift_cards"
    display_name = "Gift Cards"
    parse_version = 1

    _ASSOCIATE_RE = re.compile(r"^\d{7}$")
    _ASSOCIATE_FLAT_RE = re.compile(
        r"^(?P<associate>\d{7})\s+(?P<name>.+?)\s+(?P<total>\d[\d,]*)\s+(?P<qualifying>\d[\d,]*)\s+(?P<bonus>\d[\d,]*)\s+(?P<pct>[\d.,]+%)$"
    )
    _TOTALS_FLAT_RE = re.compile(
        r"^Totals\s+(?P<total>\d[\d,]*)\s+(?P<qualifying>\d[\d,]*)\s+(?P<bonus>\d[\d,]*)\s+(?P<pct>[\d.,]+%)$"
    )
    _HEADER_LABELS = {
        "Gift Card Bonus Report",
        "Associate #",
        "Name",
        "Total Transactions",
        "Total Qualifying Transactions",
        "Total Transactions With GC Bonus",
        "Total Transactions with GC Bonus",
        "%Transactions W/ GC Bonus",
        "% Transactions W/ GC Bonus",
    }
    _FOOTER_DATE_RE = re.compile(r"^(?P<weekday>Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday),\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})$")
    _VISIBLE_HEADERS = [
        "Associate #",
        "Name",
        "Total Transactions",
        "Total Transactions with GC Bonus",
        "% Transactions w/ GC Bonus",
        "Missed Opportunities",
    ]
    _GOAL_RATE = Decimal("0.18")

    def parse(self, raw_text: str) -> ParsedReport:
        lines = [line.strip() for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").splitlines() if line.strip()]
        period_start, period_end = self._extract_period(lines)
        store_number = self._extract_store_number(lines)
        rows = self._extract_rows(lines)
        associate_rows = [row for row in rows if row.get("row_kind") == "associate"]
        store_total = next((row for row in rows if row.get("row_kind") == "store_total"), None)
        fiscal = self._build_fiscal_payload(period_start, period_end)
        payload = {
            "parse_version": self.parse_version,
            "raw_text": raw_text,
            "report_title": "Gift Card Bonus Report",
            "location": f"Store {store_number}" if store_number else "",
            "store_number": store_number,
            "fiscal": fiscal,
            "goal_rate": float(self._GOAL_RATE),
            "summary_rows": rows,
            "associate_rows": associate_rows,
            "store_total": store_total,
            "weekly_sales_dpt": None,
            "weekly_sales_missing": True,
            "viewer": {
                "headers": list(self._VISIBLE_HEADERS),
                "rows": [self._viewer_row(row) for row in associate_rows],
            },
        }
        return ParsedReport(
            report_type=self.slug,
            source_name="gift_cards.pdf",
            period_start=period_start.isoformat() if period_start else None,
            period_end=period_end.isoformat() if period_end else None,
            payload=payload,
            raw_rows=rows,
        )

    @classmethod
    def _extract_period(cls, lines: list[str]) -> tuple[date | None, date | None]:
        start: date | None = None
        end: date | None = None
        for line in lines:
            lowered = line.lower().strip()
            if lowered.startswith("from date:"):
                parsed = cls._parse_date(line.split(":", 1)[1].strip())
                if parsed is not None:
                    start = parsed
                continue
            if lowered.startswith("to date:"):
                parsed = cls._parse_date(line.split(":", 1)[1].strip())
                if parsed is not None:
                    end = parsed
                continue
            if cls._FOOTER_DATE_RE.match(line):
                parsed = cls._parse_date(line)
                if parsed is None:
                    continue
                if start is None:
                    start = parsed
                else:
                    end = parsed
        return start, end

    @classmethod
    def _extract_store_number(cls, lines: list[str]) -> str:
        for line in reversed(lines):
            lowered = line.lower().strip()
            if lowered.startswith("store number:"):
                value = line.split(":", 1)[1].strip()
                if value.isdigit():
                    return value
            if line.isdigit():
                return line
        return ""

    @classmethod
    def _extract_rows(cls, lines: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if cls._is_footer_line(line) or line in cls._HEADER_LABELS:
                index += 1
                continue
            if line.startswith("Totals "):
                row = cls._parse_flat_store_total(line)
                if row is not None:
                    rows.append(row)
                index += 1
                continue
            if line == "Totals":
                row, index = cls._parse_store_total(lines, index + 1)
                if row is not None:
                    rows.append(row)
                continue
            flat_row = cls._parse_flat_associate_row(line)
            if flat_row is not None:
                rows.append(flat_row)
                index += 1
                continue
            if cls._ASSOCIATE_RE.match(line):
                row, index = cls._parse_associate_row(lines, index)
                if row is not None:
                    rows.append(row)
                continue
            index += 1
        return rows

    @classmethod
    def _parse_flat_associate_row(cls, line: str) -> dict[str, Any] | None:
        match = cls._ASSOCIATE_FLAT_RE.match(line)
        if match is None:
            return None
        associate_number = match.group("associate")
        name = match.group("name").strip()
        values = [match.group("total"), match.group("qualifying"), match.group("bonus"), match.group("pct")]
        return cls._build_row(
            row_kind="associate",
            source_label="associate",
            associate_number=associate_number,
            name=name,
            values=values,
        )

    @classmethod
    def _parse_flat_store_total(cls, line: str) -> dict[str, Any] | None:
        match = cls._TOTALS_FLAT_RE.match(line)
        if match is None:
            return None
        values = [match.group("total"), match.group("qualifying"), match.group("bonus"), match.group("pct")]
        return cls._build_row(
            row_kind="store_total",
            source_label="Totals",
            associate_number="",
            name="Store Sales",
            values=values,
        )

    @classmethod
    def _parse_associate_row(cls, lines: list[str], index: int) -> tuple[dict[str, Any] | None, int]:
        associate_number = lines[index].strip()
        index += 1
        name_parts: list[str] = []
        while index < len(lines):
            line = lines[index]
            if cls._is_footer_line(line) or line == "Totals" or cls._ASSOCIATE_RE.match(line):
                break
            if cls._is_numeric_line(line):
                break
            if line not in cls._HEADER_LABELS:
                name_parts.append(line)
            index += 1
        values: list[str] = []
        while index < len(lines) and len(values) < 4:
            line = lines[index]
            if cls._is_footer_line(line) or line == "Totals" or cls._ASSOCIATE_RE.match(line):
                break
            if cls._is_numeric_line(line):
                values.append(line)
            index += 1
        if len(values) < 4:
            return None, index
        return cls._build_row(
            row_kind="associate",
            source_label="associate",
            associate_number=associate_number,
            name=" ".join(name_parts).strip(),
            values=values,
        ), index

    @classmethod
    def _parse_store_total(cls, lines: list[str], index: int) -> tuple[dict[str, Any] | None, int]:
        values: list[str] = []
        while index < len(lines) and len(values) < 4:
            line = lines[index]
            if cls._is_footer_line(line):
                break
            if cls._is_numeric_line(line):
                values.append(line)
            index += 1
        if len(values) < 4:
            return None, index
        return cls._build_row(
            row_kind="store_total",
            source_label="Totals",
            associate_number="",
            name="Store Sales",
            values=values,
        ), index

    @classmethod
    def _build_row(
        cls,
        *,
        row_kind: str,
        source_label: str,
        associate_number: str,
        name: str,
        values: list[str],
    ) -> dict[str, Any]:
        total_transactions = cls._to_int(values[0])
        total_qualifying_transactions = cls._to_int(values[1])
        bonus_transactions = cls._to_int(values[2])
        bonus_pct = cls._to_percent(values[3])
        goal_transactions = cls._goal_transactions(total_transactions)
        transaction_gap = cls._transaction_gap(total_transactions, bonus_transactions)
        metrics = {
            "associate_number": associate_number,
            "name": name,
            "source_label": source_label,
            "total_transactions": total_transactions,
            "total_qualifying_transactions": total_qualifying_transactions,
            "gc_bonus_transactions": bonus_transactions,
            "bonus_percent": bonus_pct,
            "goal_transactions": goal_transactions,
            "transaction_gap": transaction_gap,
            "weekly_sales_dpt": None,
            "missed_opportunities": None,
        }
        return {
            "row_kind": row_kind,
            "associate_number": associate_number,
            "name": name,
            "source_label": source_label,
            "metrics": metrics,
            "visible_values": [
                associate_number,
                name,
                cls._format_number(total_transactions),
                cls._format_number(bonus_transactions),
                cls._format_percent(bonus_pct),
                "",
            ],
            "viewer": {
                "values": [
                    associate_number,
                    name,
                    cls._format_number(total_transactions),
                    cls._format_number(bonus_transactions),
                    cls._format_percent(bonus_pct),
                    "",
                ]
            },
        }

    @classmethod
    def _viewer_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        viewer = row.get("viewer") if isinstance(row, dict) else None
        if isinstance(viewer, dict):
            return viewer
        metrics = row.get("metrics") if isinstance(row, dict) else {}
        metrics_dict = metrics if isinstance(metrics, dict) else {}
        return {
            "values": [
                row.get("associate_number", ""),
                row.get("name", ""),
                cls._format_number(metrics_dict.get("total_transactions")),
                cls._format_number(metrics_dict.get("gc_bonus_transactions")),
                cls._format_percent(metrics_dict.get("bonus_percent")),
                cls._format_currency(metrics_dict.get("missed_opportunities")),
            ]
        }

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
    def _goal_transactions(total_transactions: int | None) -> float | None:
        if total_transactions is None:
            return None
        return float((Decimal(total_transactions) * GiftCardsReport._GOAL_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    @staticmethod
    def _transaction_gap(total_transactions: int | None, bonus_transactions: int | None) -> float | None:
        if total_transactions is None or bonus_transactions is None:
            return None
        goal_transactions = GiftCardsReport._goal_transactions(total_transactions)
        if goal_transactions is None:
            return None
        return float(Decimal(str(goal_transactions)) - Decimal(bonus_transactions))

    @staticmethod
    def _to_int(value: str) -> int | None:
        try:
            return int(str(value).replace(",", "").strip())
        except ValueError:
            return None

    @staticmethod
    def _to_percent(value: str) -> float | None:
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        if text.endswith("%"):
            text = text[:-1]
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _format_number(value: object) -> str:
        if value is None:
            return ""
        try:
            number = int(Decimal(str(value)))
        except (InvalidOperation, ValueError):
            return str(value)
        return f"{number:,}"

    @staticmethod
    def _format_percent(value: object) -> str:
        if value is None:
            return ""
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return str(value)
        if number == number.to_integral():
            return f"{int(number)}%"
        quantized = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{quantized:f}".rstrip("0").rstrip(".") + "%"

    @staticmethod
    def _format_currency(value: object) -> str:
        if value is None:
            return ""
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return str(value)
        if number == number.to_integral():
            return f"${int(number):,}"
        quantized = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"${quantized:,.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _parse_date(value: str) -> date | None:
        for fmt in ("%A, %B %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    @classmethod
    def _is_numeric_line(cls, line: str) -> bool:
        stripped = line.strip().replace(",", "")
        if not stripped:
            return False
        if stripped.endswith("%"):
            return True
        if stripped.startswith(("$", "(", "-")):
            return True
        return stripped[0:1].isdigit()

    @classmethod
    def _is_footer_line(cls, line: str) -> bool:
        lowered = line.lower().strip()
        return lowered.startswith(("store number", "from date", "to date", "page ", "gift card bonus report")) or bool(cls._FOOTER_DATE_RE.match(line))


def load_gift_cards_report() -> GiftCardsReport:
    report = GiftCardsReport()
    register(report)
    return report


load_gift_cards_report()
