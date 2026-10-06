import pytest

from apps.core.models import FiscalYearSettings
from apps.reports.modules.ranking import RankingReport


@pytest.mark.django_db
def test_ranking_parser_extracts_fiscal_period_from_split_pdf_footer() -> None:
    report = RankingReport().parse(
        "\n".join(
            [
                "214 Temecula 100 90 80 70 60 50 40 30 20 10 9 8 7 6 5 4 3 2 1 0 0 0",
                "FW: Week ending '26 FW",
                "35 · other footer text",
                "week ending 09/26/2026",
            ]
        )
    )

    assert report.payload["fiscal"] == {
        "fiscal_year": 2026,
        "fiscal_week_number": 35,
        "week_ending_date": "2026-09-26",
    }
    assert report.period_start == "2026-09-20"
    assert report.period_end == "2026-09-26"


@pytest.mark.django_db
def test_ranking_parser_propagates_fiscal_settings_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from django.db import OperationalError

    monkeypatch.setattr(
        FiscalYearSettings,
        "current",
        classmethod(lambda cls: (_ for _ in ()).throw(OperationalError("settings unavailable"))),
    )

    with pytest.raises(OperationalError, match="settings unavailable"):
        RankingReport().parse("FW: Week ending '26 FW01 week ending 02/07/2026")