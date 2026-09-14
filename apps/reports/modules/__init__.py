from __future__ import annotations

from ..registry import is_registered, register
from .bonus_club import BonusClubReport
from .gift_cards import GiftCardsReport
from .parties import PartiesReport
from .ranking import RankingReport
from .segments import SegmentsReport
from .weekly_sales import WeeklySalesReport

BUILTIN_REPORTS: tuple[WeeklySalesReport | RankingReport | SegmentsReport | GiftCardsReport | BonusClubReport, ...] = (
    WeeklySalesReport(),
    RankingReport(),
    SegmentsReport(),
    GiftCardsReport(),
    BonusClubReport(),
)
PARTIES_REPORT = PartiesReport()


def load_builtin_reports() -> tuple[str, ...]:
    loaded: list[str] = []
    for report in BUILTIN_REPORTS:
        if not is_registered(report.slug):
            register(report)
            loaded.append(report.slug)
    return tuple(loaded)


def load_parties_report() -> bool:
    if is_registered(PARTIES_REPORT.slug):
        return False
    register(PARTIES_REPORT)
    return True


load_builtin_reports()
