"""Report contracts, registry, fiscal calendar, and dashboard helpers."""

from .base import ParsedReport, ReportModule
from .dashboard import (
    DashboardContext,
    DashboardReport,
    DashboardTrend,
    DashboardTrendPoint,
    DashboardWeek,
    build_dashboard_data,
    build_six_week_dashboard,
    build_week_filter,
    filter_weeks,
    iso_week_key,
    normalize_week_key,
    summarize_report,
    week_bounds,
    week_key_from_report,
    week_windows,
)
from .fiscal import FiscalCalendarConfig, FiscalWeek, as_dict, calculate_fiscal_week
from .registry import all_reports, clear, get, register

__all__ = [
    "ParsedReport",
    "ReportModule",
    "DashboardContext",
    "DashboardReport",
    "DashboardTrend",
    "DashboardTrendPoint",
    "DashboardWeek",
    "build_dashboard_data",
    "build_six_week_dashboard",
    "build_week_filter",
    "filter_weeks",
    "iso_week_key",
    "normalize_week_key",
    "summarize_report",
    "week_bounds",
    "week_key_from_report",
    "week_windows",
    "FiscalCalendarConfig",
    "FiscalWeek",
    "as_dict",
    "calculate_fiscal_week",
    "all_reports",
    "clear",
    "get",
    "register",
]
