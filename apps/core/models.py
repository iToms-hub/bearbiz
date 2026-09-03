from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
from django.db import models

from .fiscal import boundary_date, fiscal_week_for_day, fiscal_year_for_day


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
    calendar_pattern = models.CharField(
        max_length=3,
        choices=CalendarPattern.choices,
        default=CalendarPattern.FOUR_FIVE_FOUR,
        help_text="Retail quarter pattern used for week grouping.",
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
        return boundary_date(year, self.boundary_month, self.boundary_weekday, self.boundary_rule)

    def fiscal_year_for_date(self, day: date) -> int:
        return fiscal_year_for_day(
            day,
            month=self.boundary_month,
            weekday=self.boundary_weekday,
            rule=self.boundary_rule,
        )

    def fiscal_week_for_date(self, day: date) -> int:
        return fiscal_week_for_day(
            day,
            month=self.boundary_month,
            weekday=self.boundary_weekday,
            rule=self.boundary_rule,
        )
