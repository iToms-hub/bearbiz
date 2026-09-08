from __future__ import annotations

from datetime import date, datetime, timedelta
import math
import re
from typing import Any

from ..base import ParsedReport
from ..registry import register


class RankingReport:
    slug = "ranking"
    display_name = "Ranking"
    parse_version = 2

    _TARGET_STORE = "214"
    _STORE_ROW_RE = re.compile(r"^(?P<store_number>\d{3})\s+(?P<rest>.+)$")
    _FOOTER_RE = re.compile(
        r"FW:\s*Week ending\s*'(?P<fy>\d{2})\s*FW(?P<week>\d{2}).*?week ending\s*(?P<date>\d{1,2}/\d{1,2}/\d{4})",
        re.IGNORECASE,
    )

    _COLUMN_SPECS = (
        ("sales", "Sales"),
        ("sales_v_plan", "Sales v plan"),
        ("sales_v_ly", "Sales v ly"),
        ("trans", "Trans"),
        ("trans_v_ly", "Trans v ly"),
        ("dpt", "DPT"),
        ("dpt_bw_ly", "B/W v ly"),
        ("upt", "UPT"),
        ("upt_bw_ly", "B/W v ly"),
        ("parties", "Parties"),
        ("parties_bw_ly", "B/W v ly"),
        ("party_sales_pct", "% Party Sales"),
        ("reg_gc_count", "# Reg GC"),
        ("amt_reg_gc", "Amt Reg GC"),
        ("reg_gc_amt", "Reg GC Amt"),
        ("reg_gc_bw_ly", "B/W v ly"),
        ("skin_units", "Skin Units"),
        ("traffic_ty", "Traffic TY"),
        ("traffic_bw", "Traffic b/w"),
        ("conv_ty", "Conv ty"),
        ("conv_ly", "Conv ly"),
        ("conv_bw", "Conv b/w"),
        ("stuffers", "Stuffers"),
    )
    _DISPLAY_METRICS = (
        ("sales", "Sales"),
        ("sales_v_plan", "Sales v plan"),
        ("sales_v_ly", "Sales v ly"),
        ("dpt", "DPT"),
        ("upt", "UPT"),
        ("parties", "Parties"),
        ("traffic_bw", "Traffic b/w"),
        ("conv_ty", "Conv ty"),
        ("conv_bw", "Conv b/w"),
        ("stuffers", "Stuffers"),
    )

    def parse(self, raw_text: str) -> ParsedReport:
        lines = [line.strip() for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").splitlines() if line.strip()]
        fiscal_year, fiscal_week, period_end = self._extract_period(lines)
        store_rows = self._extract_store_rows(lines)
        target_store = self._build_target_store(store_rows)
        fiscal = None
        if fiscal_year is not None and fiscal_week is not None and period_end is not None:
            fiscal = {
                "fiscal_year": fiscal_year,
                "fiscal_week_number": fiscal_week,
                "week_ending_date": period_end.isoformat(),
            }

        period_start = period_end - timedelta(days=6) if period_end else None
        payload = {
            "parse_version": self.parse_version,
            "raw_text": raw_text,
            "fiscal": fiscal,
            "store_count": len(store_rows),
            "store_rows": store_rows,
            "target_store": target_store,
            "viewer": self._build_viewer(target_store, fiscal_week, period_end),
        }
        return ParsedReport(
            report_type=self.slug,
            source_name="ranking.pdf",
            period_start=period_start.isoformat() if period_start else None,
            period_end=period_end.isoformat() if period_end else None,
            payload=payload,
            raw_rows=store_rows,
        )

    def _extract_period(self, lines: list[str]) -> tuple[int | None, int | None, date | None]:
        for line in lines:
            match = self._FOOTER_RE.search(line)
            if not match:
                continue
            fiscal_year = 2000 + int(match.group("fy"))
            fiscal_week = int(match.group("week"))
            period_end = self._parse_date(match.group("date"))
            return fiscal_year, fiscal_week, period_end
        return None, None, None

    def _extract_store_rows(self, lines: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            match = self._STORE_ROW_RE.match(line)
            if not match:
                index += 1
                continue
            store_number = match.group("store_number")
            rest = match.group("rest").strip()
            name_tokens: list[str] = []
            value_tokens = rest.split()
            value_index = len(value_tokens)
            for idx, token in enumerate(value_tokens):
                if self._looks_like_value_token(token):
                    value_index = idx
                    break
                name_tokens.append(token)
            store_name = " ".join(name_tokens).strip()
            values = self._tokenize_value_text(" ".join(value_tokens[value_index:]))
            index += 1
            if not values:
                while len(values) < len(self._COLUMN_SPECS) and index < len(lines):
                    current = lines[index]
                    if self._STORE_ROW_RE.match(current) or self._is_footer_line(current):
                        break
                    values.extend(self._tokenize_value_text(current))
                    index += 1
            if not values:
                continue
            while len(values) < len(self._COLUMN_SPECS) and index < len(lines):
                current = lines[index]
                if self._STORE_ROW_RE.match(current) or self._is_footer_line(current):
                    break
                values.extend(self._tokenize_value_text(current))
                index += 1
            if store_number == self._TARGET_STORE or store_number.isdigit():
                rows.append(self._build_store_row(store_number, store_name, values))
            if self._is_footer_line(lines[index] if index < len(lines) else ""):
                break
        return rows

    def _build_store_row(self, store_number: str, store_name: str, values: list[str]) -> dict[str, Any]:
        normalized_values = values[: len(self._COLUMN_SPECS)]
        if len(normalized_values) < len(self._COLUMN_SPECS):
            normalized_values.extend([""] * (len(self._COLUMN_SPECS) - len(normalized_values)))
        metrics = {
            key: normalized_values[index]
            for index, (key, _) in enumerate(self._COLUMN_SPECS)
        }
        return {
            "store_number": store_number,
            "store_name": store_name,
            "values": normalized_values,
            "metrics": metrics,
        }

    @staticmethod
    def _tokenize_value_text(text: str) -> list[str]:
        tokens: list[str] = []
        for token in text.split():
            if token == "%":
                if tokens:
                    tokens[-1] = f"{tokens[-1]} %"
                continue
            if token == "-" and tokens:
                tokens[-1] = f"{tokens[-1]} -"
                continue
            tokens.append(token)
        return tokens

    @staticmethod
    def _looks_like_value_token(token: str) -> bool:
        stripped = token.strip()
        return stripped.startswith(("$", "-", "(", "N/A", "NaN", "Infinity")) or stripped[0:1].isdigit()

    def _build_target_store(self, store_rows: list[dict[str, Any]]) -> dict[str, Any]:
        target = next((row for row in store_rows if row.get("store_number") == self._TARGET_STORE), None)
        if target is None:
            return {"store_number": self._TARGET_STORE, "store_name": "Temecula", "metrics": {}, "ranks": {}, "store_count": len(store_rows)}

        ranks: dict[str, dict[str, Any]] = {}
        for key, _label in self._DISPLAY_METRICS:
            target_value = self._numeric_value(target["metrics"].get(key))
            if target_value is None:
                continue
            candidates: list[tuple[float, str, str]] = []
            for row in store_rows:
                numeric_value = self._numeric_value(row["metrics"].get(key))
                if numeric_value is None:
                    continue
                candidates.append((numeric_value, row["store_number"], row["store_name"]))
            ranked = sorted(candidates, key=lambda item: item[0], reverse=True)
            rank = 1 + sum(1 for numeric_value, _, _ in ranked if numeric_value > target_value)
            ranks[key] = {"rank": rank, "total": len(ranked), "value": target["metrics"].get(key)}

        return {
            "store_number": target["store_number"],
            "store_name": target["store_name"],
            "metrics": target["metrics"],
            "ranks": ranks,
            "store_count": len(store_rows),
        }

    def _build_viewer(self, target_store: dict[str, Any], fiscal_week: int | None, period_end: date | None) -> dict[str, Any]:
        ranks = target_store.get("ranks", {}) if isinstance(target_store, dict) else {}
        values = [fiscal_week if fiscal_week is not None else "", self._format_display_date(period_end)]
        for key, _label in self._DISPLAY_METRICS:
            rank = ranks.get(key, {})
            if rank:
                values.append(f"{rank['rank']}/{rank['total']}")
            else:
                values.append("")
        return {
            "headers": ["Week", "Date", *[label for _, label in self._DISPLAY_METRICS]],
            "values": values,
            "store_number": target_store.get("store_number"),
            "store_name": target_store.get("store_name"),
        }

    @staticmethod
    def _is_footer_line(line: str) -> bool:
        lowered = line.lower()
        return lowered.startswith(("socal/vegas", "north america", "company total", "confidential", "run on", "page ", "fw: week ending", "build-a-bear"))

    @staticmethod
    def _numeric_value(value: Any) -> float | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"-", "n/a", "nan", "infinity", "inf"}:
            return None
        text = text.replace(",", "").replace("$", "")
        if text.endswith("%"):
            text = text[:-1]
        if text.startswith("(") and text.endswith(")"):
            text = f"-{text[1:-1]}"
        try:
            numeric = float(text)
            return numeric if math.isfinite(numeric) else None
        except ValueError:
            return None

    @staticmethod
    def _parse_date(value: str) -> date | None:
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _format_display_date(value: date | None) -> str:
        if value is None:
            return ""
        return value.strftime("%m/%d/%y")


def load_ranking_report() -> RankingReport:
    report = RankingReport()
    register(report)
    return report


load_ranking_report()
