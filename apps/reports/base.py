from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedReport:
    report_type: str
    source_name: str
    period_start: str | None = None
    period_end: str | None = None
    payload: dict[str, Any] | None = None


class ReportModule:
    slug: str = ""
    display_name: str = ""

    def parse(self, raw_text: str) -> ParsedReport:
        raise NotImplementedError
