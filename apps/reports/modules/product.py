from __future__ import annotations

import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pdfplumber

from apps.core.models import FiscalYearSettings

_DATE_RE = re.compile(r"(?:From Date|To Date):\s+([A-Za-z]+,\s+[A-Za-z]+\s+\d{1,2},\s+\d{4})")
_STORE_RE = re.compile(r"Store Number:\s*([\w-]+)")


def _money(value: str) -> Decimal:
    try:
        return Decimal(value.replace("$", "").replace(",", "").strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid net sales value: {value!r}") from exc


def _units(value: str) -> Decimal:
    try:
        return Decimal(value.replace(",", "").strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid units sold value: {value!r}") from exc


def parse_product_pdf(data: bytes) -> dict[str, Any]:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        rows: list[dict[str, Any]] = []
        current_department = ""
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for raw in table:
                    if not raw or len(raw) < 6:
                        continue
                    cells = [(cell or "").strip() for cell in raw]
                    if cells[0].lower() == "department" or cells[1].lower().startswith("department"):
                        continue
                    if cells[3].lower().startswith("totals"):
                        continue
                    if cells[0]:
                        current_department = cells[0]
                    if not current_department or not cells[1].isdigit() or not cells[2]:
                        continue
                    if not cells[4] or not cells[5]:
                        continue
                    rows.append({
                        "department": current_department,
                        "department_rank": int(cells[1]),
                        "item_number": cells[2],
                        "item_description": cells[3],
                        "units_sold": _units(cells[4]),
                        "net_sales": _money(cells[5]),
                    })
    dates = [datetime.strptime(value, "%A, %B %d, %Y").date() for value in _DATE_RE.findall(text)]
    if len(dates) != 2 or not rows:
        raise ValueError("This PDF does not contain a recognizable Top 20 Items report.")
    period_start, period_end = dates
    settings = FiscalYearSettings.current()
    store_match = _STORE_RE.search(text)
    return {
        "store_number": store_match.group(1) if store_match else "",
        "period_start": period_start,
        "period_end": period_end,
        "fiscal_year": settings.fiscal_year_for_date(period_end),
        "fiscal_week": settings.fiscal_week_for_date(period_end),
        "rows": rows,
    }
