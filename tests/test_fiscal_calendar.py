from __future__ import annotations

from datetime import date, datetime

import pytest

from apps.reports.fiscal import FiscalCalendarConfig, as_dict, calculate_fiscal_week


def test_calculate_fiscal_week_uses_period_end_as_week_ending_date() -> None:
    fiscal_week = calculate_fiscal_week("2025-01-01", "2025-01-07")

    assert fiscal_week.week_ending_date == date(2025, 1, 7)
    assert fiscal_week.period_start == date(2025, 1, 1)
    assert fiscal_week.period_end == date(2025, 1, 7)


def test_calculate_fiscal_week_rolls_fiscal_year_forward_on_start_boundary() -> None:
    config = FiscalCalendarConfig(start_month=7, start_day=1, week_ending_weekday=6)

    prior_year = calculate_fiscal_week(date(2024, 6, 24), date(2024, 6, 30), config=config)
    new_fiscal_year = calculate_fiscal_week(date(2024, 7, 1), datetime(2024, 7, 7, 18, 0), config=config)

    assert prior_year.fiscal_year == 2024
    assert prior_year.fiscal_week_number == 53
    assert new_fiscal_year.fiscal_year == 2025
    assert new_fiscal_year.fiscal_week_number == 1


def test_calculate_fiscal_week_supports_custom_week_ending_day() -> None:
    config = FiscalCalendarConfig(start_month=2, start_day=1, week_ending_weekday=4)
    fiscal_week = calculate_fiscal_week("2025-02-01", "2025-02-07", config=config)

    assert fiscal_week.fiscal_year == 2026
    assert fiscal_week.fiscal_week_number == 1
    assert fiscal_week.week_ending_date == date(2025, 2, 7)


def test_calculate_fiscal_week_rejects_reversed_bounds() -> None:
    with pytest.raises(ValueError, match="period_start"):
        calculate_fiscal_week("2025-01-10", "2025-01-09")


def test_as_dict_serializes_iso_dates() -> None:
    fiscal_week = calculate_fiscal_week("2025-01-01", "2025-01-07")

    assert as_dict(fiscal_week) == {
        "fiscal_year": 2025,
        "week_ending_date": "2025-01-07",
        "fiscal_week_number": 1,
        "period_start": "2025-01-01",
        "period_end": "2025-01-07",
    }
