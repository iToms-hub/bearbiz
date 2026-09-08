from __future__ import annotations

from datetime import date, datetime
import re

from ..fiscal import as_dict, calculate_fiscal_week
from ..base import ParsedReport
from ..registry import register


class WeeklySalesReport:
    slug = "weekly_sales"
    display_name = "Weekly Sales"
    parse_version = 2

    _SECTION_KEYWORDS = (
        "summary",
        "weekly sales summary",
        "sales summary",
        "kpi",
    )

    _LABEL_ALIASES = {
        "fiscal year": "fiscal_year",
        "fiscal week": "fiscal_week",
        "week": "fiscal_week",
        "week number": "fiscal_week",
        "period start": "period_start",
        "start date": "period_start",
        "week start": "period_start",
        "period end": "period_end",
        "end date": "period_end",
        "week ending": "period_end",
        "week end": "period_end",
        "time period": "period_end",
        "gross sales": "gross_sales",
        "net sales": "net_sales",
        "sales": "sales",
        "revenue": "revenue",
        "orders": "orders",
        "order count": "orders",
        "units": "units",
        "unit count": "units",
        "average order value": "average_order_value",
        "avg order value": "average_order_value",
        "aov": "average_order_value",
        "conversion rate": "conversion_rate",
        "discount": "discounts",
        "discounts": "discounts",
        "returns": "returns",
        "traffic": "traffic",
        "sessions": "traffic",
        "visitors": "traffic",
    }

    _COMPACT_LABEL_ALIASES = {
        "totalsales": "total_sales",
        "lytotalsales": "ly_total_sales",
        "ttotalsales": "target_total_sales",
        "totarget": "pct_to_target",
        "storesales": "store_sales",
        "bosfssales": "bo_sfs_sales",
        "bopissales": "bo_pis_sales",
        "enterprisesales": "enterprise_sales",
        "trafficleverage": "traffic_leverage",
        "conversion": "conversion_rate",
        "lyconv": "ly_conversion_rate",
        "traffic": "traffic",
        "lytraffic": "ly_traffic",
        "changetolytraffic": "pct_change_to_ly_traffic",
        "salestrans": "sales_trans",
        "bosfstrans": "bo_sfs_trans",
        "bopistrans": "bo_pis_trans",
        "enterprisetrans": "enterprise_trans",
        "dpt": "dpt",
        "lydpt": "ly_dpt",
        "upt": "upt",
        "capturerate": "capture_rate",
        "partysales": "party_sales",
        "partytrans": "party_trans",
        "reccoverage": "rec_coverage",
        "sellinghours": "selling_hours",
        "nshours": "ns_hours",
        "totalhours": "total_hours",
        "star": "star",
        "giftcardunits": "gift_card_units",
        "tbosfssales": "t_bo_sfs_sales",
        "tstoresales": "t_store_sales",
        "timeperiod": "period_end",
    }

    _DATE_FORMATS = (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%b %d, %Y",
        "%B %d, %Y",
    )

    def parse(self, raw_text: str) -> ParsedReport:
        table_title, rows = self._extract_top_table(raw_text)
        normalized_kpis: dict[str, object] = {}
        raw_kpis: dict[str, object] = {}
        typed_kpis: dict[str, object] = {}
        period_start: str | None = None
        period_end: str | None = None

        for row in rows:
            normalized_key = str(row["normalized_key"])
            value = row["value"]
            typed_value = row["typed_value"]
            if normalized_key:
                normalized_kpis[normalized_key] = typed_value
                raw_kpis[normalized_key] = value
                typed_kpis[normalized_key] = typed_value
            if normalized_key == "period_start":
                period_start = typed_value if isinstance(typed_value, str) else typed_value.isoformat() if isinstance(typed_value, date) else str(typed_value)
            elif normalized_key == "period_end":
                period_end = typed_value if isinstance(typed_value, str) else typed_value.isoformat() if isinstance(typed_value, date) else str(typed_value)

        fallback_start, fallback_end = self._extract_period_bounds(raw_text)
        if not period_start:
            period_start = fallback_start
        if not period_end:
            period_end = fallback_end

        fiscal = self._build_fiscal_payload(period_start, period_end)

        return ParsedReport(
            report_type=self.slug,
            source_name="weekly_sales.pdf",
            period_start=period_start,
            period_end=period_end,
            payload={
                "parse_version": self.parse_version,
                "raw_text": raw_text,
                "table_title": table_title,
                "summary_rows": rows,
                "summary_kpis": normalized_kpis,
                "summary_kpi_text": raw_kpis,
                "summary_kpi_values": typed_kpis,
                "fiscal": fiscal,
                "metrics": normalized_kpis,
            },
            raw_rows=rows,
        )

    @classmethod
    def _extract_period_bounds(cls, raw_text: str) -> tuple[str | None, str | None]:
        range_pattern = re.compile(
            r"(?P<start>\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})\s*(?:-|–|—|to|through)\s*(?P<end>\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
            re.IGNORECASE,
        )
        normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
        for line in (part.strip() for part in normalized.splitlines()):
            if not line:
                continue
            match = range_pattern.search(line)
            if not match:
                continue
            start = cls._parse_date(match.group("start"))
            end = cls._parse_date(match.group("end"))
            if start and end:
                return start.isoformat(), end.isoformat()
        return None, None

    @classmethod
    def _build_fiscal_payload(cls, period_start: str | None, period_end: str | None) -> dict[str, object] | None:
        if not period_start or not period_end:
            return None
        start = cls._parse_date(period_start)
        end = cls._parse_date(period_end)
        if not start or not end:
            return None

        from apps.core.models import FiscalYearSettings

        settings = FiscalYearSettings.current()
        if getattr(settings, "fiscal_year_start_date", None):
            return {
                "fiscal_year": settings.fiscal_year_for_date(end),
                "week_ending_date": end.isoformat(),
                "fiscal_week_number": settings.fiscal_week_for_date(end),
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
            }

        try:
            return as_dict(calculate_fiscal_week(start, end))
        except Exception:
            return None

    @classmethod
    def _extract_top_table(cls, raw_text: str) -> tuple[str | None, list[dict[str, object]]]:
        for block in cls._split_blocks(raw_text):
            rows = cls._parse_block(block)
            if rows:
                title = cls._extract_title(block, rows)
                return title, rows
        return None, []

    @staticmethod
    def _split_blocks(raw_text: str) -> list[str]:
        normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
        return [block.strip() for block in re.split(r"\n\s*\n+", normalized) if block.strip()]

    @classmethod
    def _parse_block(cls, block: str) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        started = False
        for line in (part.strip() for part in block.splitlines()):
            if not line:
                continue
            parsed = cls._parse_row(line)
            if parsed is None:
                if started:
                    break
                continue
            started = True
            rows.append(parsed)
        return rows

    @classmethod
    def _extract_title(cls, block: str, rows: list[dict[str, object]]) -> str | None:
        row_labels = {str(row["label"]).strip().lower() for row in rows}
        for line in (part.strip() for part in block.splitlines()):
            if not line:
                continue
            lowered = line.lower()
            if lowered in row_labels:
                continue
            if any(keyword in lowered for keyword in cls._SECTION_KEYWORDS):
                return line
        return None

    @classmethod
    def _parse_row(cls, line: str) -> dict[str, object] | None:
        cells = cls._split_cells(line)
        if len(cells) < 2:
            return None
        label = cells[0].strip()
        value = " ".join(cell.strip() for cell in cells[1:] if cell.strip())
        if not label or not value:
            return None
        normalized_key = cls._normalize_label(label)
        typed_value = cls._coerce_value(value)
        return {
            "label": label,
            "value": value,
            "normalized_label": normalized_key,
            "normalized_key": normalized_key,
            "typed_value": typed_value,
            "raw_line": line,
        }

    @staticmethod
    def _split_cells(line: str) -> list[str]:
        if "|" in line:
            cells = [cell.strip() for cell in line.split("|") if cell.strip()]
            if len(cells) >= 2:
                return cells
        if "\t" in line:
            cells = [cell.strip() for cell in line.split("\t") if cell.strip()]
            if len(cells) >= 2:
                return cells
        if ":" in line:
            left, right = line.split(":", 1)
            if left.strip() and right.strip():
                return [left.strip(), right.strip()]
        cells = [cell.strip() for cell in re.split(r"\s{2,}", line) if cell.strip()]
        return cells

    @classmethod
    def _normalize_label(cls, label: str) -> str:
        collapsed = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
        if not collapsed:
            return ""
        compact = collapsed.replace(" ", "")
        return cls._LABEL_ALIASES.get(collapsed, cls._COMPACT_LABEL_ALIASES.get(compact, collapsed.replace(" ", "_")))

    @classmethod
    def _coerce_value(cls, value: str) -> object:
        text = value.strip()
        if not text:
            return text

        compact_text = re.sub(r"\s+", "", text)

        date_value = cls._parse_date(compact_text)
        if date_value is not None:
            return date_value.isoformat()

        numeric_text = compact_text.replace(",", "")
        currency_text = numeric_text.lstrip("$")
        percent_text = currency_text[:-1] if currency_text.endswith("%") else currency_text
        if re.fullmatch(r"-?\d+", percent_text):
            try:
                return int(percent_text)
            except ValueError:
                pass
        if re.fullmatch(r"-?\d+\.\d+", percent_text):
            try:
                return float(percent_text)
            except ValueError:
                pass
        return text

    @classmethod
    def _parse_date(cls, value: str) -> date | None:
        for fmt in cls._DATE_FORMATS:
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None


def load_weekly_sales_report() -> WeeklySalesReport:
    report = WeeklySalesReport()
    register(report)
    return report


load_weekly_sales_report()
