from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from numbers import Real
from typing import Any, Iterable, Mapping, Sequence
import re

from .base import ParsedReport

_WEEK_KEY_RE = re.compile(r"^(?P<year>\d{4})-?W(?P<week>\d{2})$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RESERVED_PAYLOAD_KEYS = {
    "metrics",
    "raw_rows",
    "raw_text",
    "report_type",
    "source_name",
    "week",
    "week_key",
    "period",
    "period_start",
    "period_end",
    "fiscal_week",
}


@dataclass(frozen=True, slots=True)
class DashboardWeek:
    key: str
    start: date
    end: date
    label: str
    is_current: bool = False


@dataclass(frozen=True, slots=True)
class DashboardReport:
    report_type: str
    source_name: str
    week_key: str
    metrics: dict[str, float]


@dataclass(frozen=True, slots=True)
class DashboardTrendPoint:
    week_key: str
    label: str
    value: float


@dataclass(frozen=True, slots=True)
class DashboardTrend:
    name: str
    label: str
    total: float
    points: tuple[DashboardTrendPoint, ...]


@dataclass(frozen=True, slots=True)
class DashboardContext:
    window_size: int
    weeks: tuple[DashboardWeek, ...]
    selected_week_keys: tuple[str, ...]
    reports: tuple[DashboardReport, ...]
    metric_totals: dict[str, float]
    trends: dict[str, DashboardTrend]

    @property
    def current_week(self) -> DashboardWeek:
        return self.weeks[-1]

    @property
    def metrics(self) -> dict[str, float]:
        return self.metric_totals

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_size": self.window_size,
            "weeks": [
                {
                    "key": week.key,
                    "start": week.start.isoformat(),
                    "end": week.end.isoformat(),
                    "label": week.label,
                    "is_current": week.is_current,
                }
                for week in self.weeks
            ],
            "selected_week_keys": list(self.selected_week_keys),
            "reports": [asdict(report) for report in self.reports],
            "metric_totals": dict(self.metric_totals),
            "trends": {
                name: {
                    "name": trend.name,
                    "label": trend.label,
                    "total": trend.total,
                    "points": [asdict(point) for point in trend.points],
                }
                for name, trend in self.trends.items()
            },
        }


@dataclass(frozen=True, slots=True)
class WeekFilter:
    mode: str
    week_keys: tuple[str, ...]

    def includes(self, week_key: str) -> bool:
        if self.mode == "all-weeks":
            return True
        return week_key in self.week_keys


def iso_week_key(value: date | datetime) -> str:
    if isinstance(value, datetime):
        value = value.date()
    calendar_week = value.isocalendar()
    return f"{calendar_week.year}-W{calendar_week.week:02d}"


def week_bounds(value: date | datetime) -> tuple[date, date]:
    if isinstance(value, datetime):
        value = value.date()
    start = value - timedelta(days=value.weekday())
    return start, start + timedelta(days=6)


def week_windows(reference_date: date | datetime | None = None, size: int = 6) -> tuple[DashboardWeek, ...]:
    if size < 1:
        raise ValueError("size must be at least 1")

    reference = _as_date(reference_date or date.today())
    current_start, _ = week_bounds(reference)
    windows: list[DashboardWeek] = []
    for offset in range(size - 1, -1, -1):
        start = current_start - timedelta(weeks=offset)
        end = start + timedelta(days=6)
        key = iso_week_key(start)
        windows.append(
            DashboardWeek(
                key=key,
                start=start,
                end=end,
                label=key,
                is_current=offset == 0,
            )
        )
    return tuple(windows)


def normalize_week_key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return iso_week_key(value)
    if isinstance(value, date):
        return iso_week_key(value)

    text = str(value).strip()
    if not text:
        return None
    if _DATE_RE.match(text):
        return iso_week_key(date.fromisoformat(text))

    match = _WEEK_KEY_RE.match(text)
    if match:
        return f"{int(match.group('year')):04d}-W{int(match.group('week')):02d}"
    return None


def week_key_from_report(report: ParsedReport | Mapping[str, Any] | Any) -> str:
    candidates: list[Any] = []
    if isinstance(report, Mapping):
        payload = report.get("payload", {})
        candidates.extend(
            [
                report.get("week"),
                report.get("week_key"),
                report.get("fiscal_week"),
                report.get("period_end"),
                report.get("period_start"),
                payload.get("week") if isinstance(payload, Mapping) else None,
                payload.get("week_key") if isinstance(payload, Mapping) else None,
                payload.get("fiscal_week") if isinstance(payload, Mapping) else None,
            ]
        )
        source_name = report.get("source_name")
    else:
        candidates.extend(
            [
                getattr(report, "week", None),
                getattr(report, "week_key", None),
                getattr(report, "fiscal_week", None),
                getattr(report, "period_end", None),
                getattr(report, "period_start", None),
            ]
        )
        payload = getattr(report, "payload", {})
        if isinstance(payload, Mapping):
            candidates.extend(
                [
                    payload.get("week"),
                    payload.get("week_key"),
                    payload.get("fiscal_week"),
                ]
            )
        source_name = getattr(report, "source_name", "")

    for candidate in candidates:
        week_key = normalize_week_key(candidate)
        if week_key:
            return week_key

    if isinstance(source_name, str):
        for candidate in _WEEK_KEY_RE.finditer(source_name):
            week_key = normalize_week_key(candidate.group(0))
            if week_key:
                return week_key
        date_match = _DATE_RE.search(source_name)
        if date_match:
            return iso_week_key(date.fromisoformat(date_match.group(0)))

    return iso_week_key(date.today())


def summarize_report(report: ParsedReport | Mapping[str, Any] | Any) -> DashboardReport:
    if isinstance(report, Mapping):
        report_type = str(report.get("report_type", "unknown"))
        source_name = str(report.get("source_name", "unknown"))
        payload = report.get("payload", {})
        raw_rows = report.get("raw_rows", [])
    else:
        report_type = str(getattr(report, "report_type", "unknown"))
        source_name = str(getattr(report, "source_name", "unknown"))
        payload = getattr(report, "payload", {})
        raw_rows = getattr(report, "raw_rows", [])

    metrics = _collect_metrics(payload, raw_rows)
    return DashboardReport(
        report_type=report_type,
        source_name=source_name,
        week_key=week_key_from_report(report),
        metrics=metrics,
    )


def build_week_filter(
    weeks: Sequence[DashboardWeek],
    selection: str | Sequence[str] | None = None,
) -> WeekFilter:
    if selection is None:
        return WeekFilter(mode="all-weeks", week_keys=tuple(week.key for week in weeks))

    if isinstance(selection, str):
        normalized = selection.strip().lower()
        if normalized in {"", "all", "all-weeks", "all_weeks"}:
            return WeekFilter(mode="all-weeks", week_keys=tuple(week.key for week in weeks))
        if normalized in {"selected", "selected-weeks", "selected_weeks"}:
            return WeekFilter(mode="selected-weeks", week_keys=())
        week_keys = tuple(
            key
            for key in (normalize_week_key(part) for part in re.split(r"[\s,]+", selection))
            if key
        )
        return WeekFilter(mode="selected-weeks", week_keys=week_keys)

    week_keys = tuple(key for key in (normalize_week_key(value) for value in selection) if key)
    return WeekFilter(mode="selected-weeks", week_keys=week_keys)


def filter_weeks(
    weeks: Sequence[DashboardWeek],
    selection: str | Sequence[str] | None = None,
) -> tuple[DashboardWeek, ...]:
    week_filter = build_week_filter(weeks, selection)
    if week_filter.mode == "all-weeks":
        return tuple(weeks)
    selected = [week for week in weeks if week_filter.includes(week.key)]
    return tuple(selected)


def build_six_week_dashboard(
    reports: Iterable[ParsedReport | Mapping[str, Any] | Any],
    selection: str | Sequence[str] | None = None,
    reference_date: date | datetime | None = None,
    window_size: int = 6,
) -> DashboardContext:
    weeks = week_windows(reference_date=reference_date, size=window_size)
    week_filter = build_week_filter(weeks, selection)
    if week_filter.mode == "selected-weeks" and not week_filter.week_keys:
        week_filter = WeekFilter(mode="all-weeks", week_keys=tuple(week.key for week in weeks))

    summaries = [summarize_report(report) for report in reports]
    summary_by_week: dict[str, list[DashboardReport]] = defaultdict(list)
    for summary in summaries:
        summary_by_week[summary.week_key].append(summary)

    selected_week_keys = tuple(week.key for week in filter_weeks(weeks, week_filter.week_keys if week_filter.mode == "selected-weeks" else None))
    if week_filter.mode == "all-weeks":
        selected_week_keys = tuple(week.key for week in weeks)

    selected_week_set = set(selected_week_keys)
    filtered_reports = tuple(
        summary
        for week in weeks
        if week.key in selected_week_set
        for summary in summary_by_week.get(week.key, [])
    )

    metric_totals: dict[str, float] = defaultdict(float)
    metric_week_values: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for summary in filtered_reports:
        for metric_name, metric_value in summary.metrics.items():
            metric_totals[metric_name] += metric_value
            metric_week_values[metric_name][summary.week_key] += metric_value

    trends: dict[str, DashboardTrend] = {}
    for metric_name in sorted(metric_week_values):
        points = tuple(
            DashboardTrendPoint(
                week_key=week.key,
                label=week.label,
                value=metric_week_values[metric_name].get(week.key, 0.0) if week.key in selected_week_set else 0.0,
            )
            for week in weeks
        )
        trends[metric_name] = DashboardTrend(
            name=metric_name,
            label=_humanize_metric_name(metric_name),
            total=metric_totals[metric_name],
            points=points,
        )

    return DashboardContext(
        window_size=window_size,
        weeks=weeks,
        selected_week_keys=selected_week_keys,
        reports=filtered_reports,
        metric_totals=dict(metric_totals),
        trends=trends,
    )


def build_dashboard_data(
    reports: Iterable[ParsedReport | Mapping[str, Any] | Any],
    selection: str | Sequence[str] | None = None,
    reference_date: date | datetime | None = None,
    window_size: int = 6,
) -> dict[str, Any]:
    return build_six_week_dashboard(
        reports=reports,
        selection=selection,
        reference_date=reference_date,
        window_size=window_size,
    ).to_dict()


def _collect_metrics(payload: Any, raw_rows: Any) -> dict[str, float]:
    metrics: dict[str, float] = {}
    if isinstance(payload, Mapping):
        metrics.update(_collect_numeric_mapping(payload))
        nested_metrics = payload.get("metrics")
        if isinstance(nested_metrics, Mapping):
            metrics.update(_collect_numeric_mapping(nested_metrics))

    if isinstance(raw_rows, Sequence) and not isinstance(raw_rows, (str, bytes)):
        for row in raw_rows:
            if not isinstance(row, Mapping):
                continue
            for key, value in row.items():
                if key in metrics:
                    continue
                number = _coerce_number(value)
                if number is not None:
                    metrics[key] = metrics.get(key, 0.0) + number
    return metrics


def _collect_numeric_mapping(mapping: Mapping[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for key, value in mapping.items():
        if key in _RESERVED_PAYLOAD_KEYS:
            continue
        number = _coerce_number(value)
        if number is not None:
            metrics[key] = metrics.get(key, 0.0) + number
    return metrics


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Real):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _humanize_metric_name(name: str) -> str:
    return name.replace("_", " ").strip().title() or name


def _as_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value
