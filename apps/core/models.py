from __future__ import annotations

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import models

from .fiscal import boundary_date, fiscal_week_for_day, fiscal_year_for_day


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


class CalendarPattern(models.TextChoices):
    FOUR_FIVE_FOUR = "454", "4-5-4"
    FOUR_FOUR_FIVE = "445", "4-4-5"
    FIVE_FOUR_FOUR = "544", "5-4-4"


class BoundaryRule(models.TextChoices):
    FIRST = "first", "First weekday in month"
    LAST = "last", "Last weekday in month"
    NEAREST = "nearest", "Nearest weekday to month end"


class Weekday(models.IntegerChoices):
    MONDAY = 0, "Monday"
    TUESDAY = 1, "Tuesday"
    WEDNESDAY = 2, "Wednesday"
    THURSDAY = 3, "Thursday"
    FRIDAY = 4, "Friday"
    SATURDAY = 5, "Saturday"
    SUNDAY = 6, "Sunday"


class FiscalYearSettings(models.Model):
    """Singleton configuration for a retail fiscal calendar."""

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    fiscal_year_start_date = models.DateField(
        null=True,
        blank=True,
        help_text="First day of the current fiscal year. The 4-5-4 calendar stays fixed behind the scenes.",
    )
    calendar_pattern = models.CharField(
        max_length=3,
        choices=CalendarPattern.choices,
        default=CalendarPattern.FOUR_FIVE_FOUR,
        help_text="Fixed to 4-5-4 internally.",
    )
    boundary_rule = models.CharField(
        max_length=16,
        choices=BoundaryRule.choices,
        default=BoundaryRule.NEAREST,
        help_text="How the fiscal year boundary is picked near month end.",
    )
    boundary_month = models.PositiveSmallIntegerField(
        default=1,
        choices=[(month, date(2000, month, 1).strftime("%B")) for month in range(1, 13)],
        help_text="Calendar month that anchors the fiscal year boundary.",
    )
    boundary_weekday = models.PositiveSmallIntegerField(
        default=Weekday.SATURDAY,
        choices=Weekday.choices,
        help_text="Weekday used for the boundary rule.",
    )

    class Meta:
        verbose_name = "fiscal year settings"
        verbose_name_plural = "fiscal year settings"

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if not 1 <= int(self.boundary_month or 0) <= 12:
            errors["boundary_month"] = "Boundary month must be between 1 and 12."
        if not 0 <= int(self.boundary_weekday or -1) <= 6:
            errors["boundary_weekday"] = "Boundary weekday must be between 0 and 6."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.singleton_key = 1
        return super().save(*args, **kwargs)

    @classmethod
    def current(cls) -> "FiscalYearSettings":
        instance = cls.objects.order_by("pk").first()
        if instance is not None:
            return instance
        return cls()

    def fiscal_year_end(self, year: int) -> date:
        if self.fiscal_year_start_date:
            return self.fiscal_year_start_date - timedelta(days=1)
        return boundary_date(year, self.boundary_month, self.boundary_weekday, self.boundary_rule)

    def fiscal_year_for_date(self, day: date) -> int:
        if self.fiscal_year_start_date:
            fiscal_year, _ = self._start_and_week_for_date(day)
            return fiscal_year
        return fiscal_year_for_day(
            day,
            month=self.boundary_month,
            weekday=self.boundary_weekday,
            rule=self.boundary_rule,
        )

    def fiscal_week_for_date(self, day: date) -> int:
        if self.fiscal_year_start_date:
            _, week = self._start_and_week_for_date(day)
            return week
        return fiscal_week_for_day(
            day,
            month=self.boundary_month,
            weekday=self.boundary_weekday,
            rule=self.boundary_rule,
        )

    def fiscal_year_start_for_year(self, fiscal_year: int) -> date:
        """Return the configured anniversary start for a fiscal-year label."""
        start = getattr(self, "fiscal_year_start_date", None)
        if start is None:
            return self.fiscal_year_end(fiscal_year - 1) + timedelta(days=1)
        if start.month == 2 and start.day == 29:
            return date(fiscal_year, 2, 29 if _is_leap_year(fiscal_year) else 28)
        return date(fiscal_year, start.month, start.day)

    def _start_and_week_for_date(self, day: date) -> tuple[int, int]:
        start = getattr(self, "fiscal_year_start_date", None)
        if start is None:
            raise ValueError("fiscal_year_start_date is not set")

        configured_start = date(start.year, start.month, start.day)
        # Re-derive the anniversary in the requested date's calendar year. A
        # single 52-week subtraction is wrong across 53-week fiscal years.
        if configured_start.month == 2 and configured_start.day == 29:
            anniversary = date(day.year, 2, 29 if _is_leap_year(day.year) else 28)
        else:
            anniversary = configured_start.replace(year=day.year)
        if day >= anniversary:
            fiscal_year = day.year
            fiscal_start = anniversary
        else:
            fiscal_year = day.year - 1
            if configured_start.month == 2 and configured_start.day == 29:
                fiscal_start = date(day.year - 1, 2, 29 if _is_leap_year(day.year - 1) else 28)
            else:
                fiscal_start = configured_start.replace(year=day.year - 1)

        week_number = ((day - fiscal_start).days // 7) + 1
        if week_number < 1:
            week_number = 1
        return fiscal_year, week_number


class ReviewTemplate(models.Model):
    """Saved, ordered module layout for a dashboard review report."""

    name = models.CharField(max_length=120, unique=True)
    subtitle = models.CharField(max_length=240, blank=True, default="")
    layout = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return str(self.name)


class BackupConfirmationToken(models.Model):
    """Hashes of backup confirmation tokens already consumed."""

    token_hash = models.CharField(max_length=64, unique=True)
    purpose = models.CharField(max_length=32)
    consumed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=("purpose", "consumed_at"))]


class AIIntegrationSettings(models.Model):
    """Singleton configuration for report AI enrichment."""

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    enabled = models.BooleanField(default=False)
    provider_name = models.CharField(max_length=64, default="openai-compatible")
    api_base_url = models.URLField(default="https://api.openai.com/v1")
    api_key = models.TextField(blank=True, default="")
    model_name = models.CharField(max_length=128, default="gpt-4o-mini")
    temperature = models.DecimalField(max_digits=3, decimal_places=2, default=0.20)
    max_output_tokens = models.PositiveSmallIntegerField(default=500)
    report_summary_prompt = models.TextField(
        default=(
            "Summarize the weekly sales report for a store manager. "
            "Call out notable trends, weak spots, and a practical next action."
        )
    )
    system_prompt = models.TextField(
        default=(
            "You are Bearbiz's AI report assistant. Write concise, helpful report summaries "
            "based only on the supplied report data."
        )
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI integration settings"
        verbose_name_plural = "AI integration settings"

    def __str__(self) -> str:
        return "AI integration settings"

    def save(self, *args, **kwargs):
        self.singleton_key = 1
        return super().save(*args, **kwargs)

    @classmethod
    def current(cls) -> "AIIntegrationSettings":
        instance = cls.objects.order_by("pk").first()
        if instance is not None:
            return instance
        return cls()
