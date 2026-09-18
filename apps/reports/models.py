from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import models


class ParseStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PARSED = "parsed", "Parsed"
    FAILED = "failed", "Failed"
    CONFLICT = "conflict", "Conflict"


def report_upload_path(instance: "ReportUpload", filename: str) -> str:
    return f"reports/{instance.report_type}/{filename}"


class ReportUpload(models.Model):
    """Stored report PDF and its ingestion state."""

    report_type = models.CharField(max_length=32, default="weekly_sales", db_index=True)
    source_file = models.FileField(upload_to=report_upload_path)
    source_name = models.CharField(max_length=255)
    parse_status = models.CharField(
        max_length=16,
        choices=ParseStatus.choices,
        default=ParseStatus.PENDING,
        db_index=True,
    )
    parse_error = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    parsed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]
        verbose_name = "report upload"
        verbose_name_plural = "report uploads"

    def __str__(self) -> str:
        return f"{self.source_name} ({self.report_type}:{self.parse_status})"


class WeeklySalesSummary(models.Model):
    """Normalized weekly sales data extracted from a report upload."""

    report_upload = models.OneToOneField(
        ReportUpload,
        on_delete=models.CASCADE,
        related_name="weekly_sales_summary",
    )
    fiscal_year = models.PositiveSmallIntegerField()
    fiscal_week = models.PositiveSmallIntegerField()
    fiscal_period_start = models.DateField(null=True, blank=True)
    fiscal_period_end = models.DateField(null=True, blank=True)
    raw_json = models.JSONField(default=dict, blank=True)
    ai_summary = models.TextField(blank=True, default="")
    ai_provider = models.CharField(max_length=64, blank=True, default="")
    ai_model = models.CharField(max_length=128, blank=True, default="")
    ai_payload = models.JSONField(default=dict, blank=True)
    ai_error = models.TextField(blank=True, default="")
    ai_generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fiscal_year", "-fiscal_week", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["fiscal_year", "fiscal_week"],
                name="unique_weekly_sales_summary_fiscal_period",
            )
        ]
        verbose_name = "weekly sales summary"
        verbose_name_plural = "weekly sales summaries"

    def __str__(self) -> str:
        return f"Weekly sales FY{self.fiscal_year} W{self.fiscal_week:02d}"

    @property
    def raw_data(self) -> Any:
        return self.raw_json


class RankingSummary(models.Model):
    """Normalized store ranking data extracted from a report upload."""

    report_upload = models.OneToOneField(
        ReportUpload,
        on_delete=models.CASCADE,
        related_name="ranking_summary",
    )
    fiscal_year = models.PositiveSmallIntegerField()
    fiscal_week = models.PositiveSmallIntegerField()
    fiscal_period_start = models.DateField(null=True, blank=True)
    fiscal_period_end = models.DateField(null=True, blank=True)
    raw_json = models.JSONField(default=dict, blank=True)
    ai_summary = models.TextField(blank=True, default="")
    ai_provider = models.CharField(max_length=64, blank=True, default="")
    ai_model = models.CharField(max_length=128, blank=True, default="")
    ai_payload = models.JSONField(default=dict, blank=True)
    ai_error = models.TextField(blank=True, default="")
    ai_generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fiscal_year", "-fiscal_week", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["fiscal_year", "fiscal_week"],
                name="unique_ranking_summary_fiscal_period",
            )
        ]
        verbose_name = "ranking summary"
        verbose_name_plural = "ranking summaries"

    def __str__(self) -> str:
        return f"Ranking FY{self.fiscal_year} W{self.fiscal_week:02d}"

    @property
    def raw_data(self) -> Any:
        return self.raw_json


class GiftCardsSummary(models.Model):
    """Normalized gift card bonus data extracted from a report upload."""

    report_upload = models.OneToOneField(
        ReportUpload,
        on_delete=models.CASCADE,
        related_name="gift_cards_summary",
    )
    fiscal_year = models.PositiveSmallIntegerField()
    fiscal_week = models.PositiveSmallIntegerField()
    fiscal_period_start = models.DateField(null=True, blank=True)
    fiscal_period_end = models.DateField(null=True, blank=True)
    raw_json = models.JSONField(default=dict, blank=True)
    ai_summary = models.TextField(blank=True, default="")
    ai_provider = models.CharField(max_length=64, blank=True, default="")
    ai_model = models.CharField(max_length=128, blank=True, default="")
    ai_payload = models.JSONField(default=dict, blank=True)
    ai_error = models.TextField(blank=True, default="")
    ai_generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fiscal_year", "-fiscal_week", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["fiscal_year", "fiscal_week"],
                name="unique_gift_cards_summary_fiscal_period",
            )
        ]
        verbose_name = "gift cards summary"
        verbose_name_plural = "gift cards summaries"

    def __str__(self) -> str:
        return f"Gift Cards FY{self.fiscal_year} W{self.fiscal_week:02d}"

    @property
    def raw_data(self) -> Any:
        return self.raw_json


class BonusClubSummary(models.Model):
    """Normalized bonus club capture data extracted from a report upload."""

    report_upload = models.OneToOneField(
        ReportUpload,
        on_delete=models.CASCADE,
        related_name="bonus_club_summary",
    )
    fiscal_year = models.PositiveSmallIntegerField()
    fiscal_week = models.PositiveSmallIntegerField()
    fiscal_period_start = models.DateField(null=True, blank=True)
    fiscal_period_end = models.DateField(null=True, blank=True)
    raw_json = models.JSONField(default=dict, blank=True)
    ai_summary = models.TextField(blank=True, default="")
    ai_provider = models.CharField(max_length=64, blank=True, default="")
    ai_model = models.CharField(max_length=128, blank=True, default="")
    ai_payload = models.JSONField(default=dict, blank=True)
    ai_error = models.TextField(blank=True, default="")
    ai_generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fiscal_year", "-fiscal_week", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["fiscal_year", "fiscal_week"],
                name="unique_bonus_club_summary_fiscal_period",
            )
        ]
        verbose_name = "bonus club summary"
        verbose_name_plural = "bonus club summaries"

    def __str__(self) -> str:
        return f"Bonus Club FY{self.fiscal_year} W{self.fiscal_week:02d}"

    @property
    def raw_data(self) -> Any:
        return self.raw_json


class SegmentsSummary(models.Model):
    """Normalized manager accountability data extracted from a report upload."""

    report_upload = models.OneToOneField(
        ReportUpload,
        on_delete=models.CASCADE,
        related_name="segments_summary",
    )
    fiscal_year = models.PositiveSmallIntegerField()
    fiscal_week = models.PositiveSmallIntegerField()
    fiscal_period_start = models.DateField(null=True, blank=True)
    fiscal_period_end = models.DateField(null=True, blank=True)
    raw_json = models.JSONField(default=dict, blank=True)
    ai_summary = models.TextField(blank=True, default="")
    ai_provider = models.CharField(max_length=64, blank=True, default="")
    ai_model = models.CharField(max_length=128, blank=True, default="")
    ai_payload = models.JSONField(default=dict, blank=True)
    ai_error = models.TextField(blank=True, default="")
    ai_generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fiscal_year", "-fiscal_week", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["fiscal_year", "fiscal_week"],
                name="unique_segments_summary_fiscal_period",
            )
        ]
        verbose_name = "segments summary"
        verbose_name_plural = "segments summaries"

    def __str__(self) -> str:
        return f"Segments FY{self.fiscal_year} W{self.fiscal_week:02d}"

    @property
    def raw_data(self) -> Any:
        return self.raw_json


class ProductReport(models.Model):
    """Structured weekly Top Items report metadata; source PDFs are not retained."""

    fiscal_year = models.PositiveSmallIntegerField()
    fiscal_week = models.PositiveSmallIntegerField()
    store_number = models.CharField(max_length=32, blank=True)
    period_start = models.DateField()
    period_end = models.DateField()
    source_name = models.CharField(max_length=255)
    parse_status = models.CharField(max_length=16, choices=ParseStatus.choices, default=ParseStatus.PENDING)
    parse_error = models.TextField(blank=True)
    row_count = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    parsed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-fiscal_year", "-fiscal_week"]
        constraints = [models.UniqueConstraint(fields=["fiscal_year", "fiscal_week"], name="unique_product_report_fiscal_period")]


class ProductItem(models.Model):
    report = models.ForeignKey(ProductReport, on_delete=models.CASCADE, related_name="items")
    department = models.CharField(max_length=120)
    department_rank = models.PositiveSmallIntegerField()
    item_number = models.CharField(max_length=32)
    item_description = models.CharField(max_length=255)
    units_sold = models.DecimalField(max_digits=12, decimal_places=2)
    net_sales = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["department", "department_rank", "item_number"]


class PartiesSummary(models.Model):
    """Source-faithful weekly parties report, including raw metric cells."""

    report_upload = models.OneToOneField(ReportUpload, on_delete=models.CASCADE, related_name="parties_summary")
    fiscal_year = models.PositiveSmallIntegerField()
    fiscal_week = models.PositiveSmallIntegerField()
    rows = models.JSONField(default=list, blank=True)
    raw_json = models.JSONField(default=dict, blank=True)
    parse_version = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fiscal_year", "fiscal_week", "id"]

    def __str__(self) -> str:
        return f"Parties FY{self.fiscal_year} W{self.fiscal_week:02d}"


class PartiesWeek(models.Model):
    """Directly entered weekly Parties values for the configured fiscal year."""

    fiscal_year = models.PositiveSmallIntegerField()
    fiscal_month = models.PositiveSmallIntegerField()
    fiscal_week = models.PositiveSmallIntegerField()
    held_current = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    held_previous = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    booked_current = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    booked_previous = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fiscal_year", "fiscal_week"]
        constraints = [
            models.UniqueConstraint(fields=["fiscal_year", "fiscal_week"], name="unique_parties_week")
        ]
        verbose_name = "parties week"
        verbose_name_plural = "parties weeks"

    @property
    def held_variance(self) -> Decimal | None:
        if self.held_current is None or self.held_previous is None:
            return None
        return (self.held_current - self.held_previous).quantize(Decimal("0.01"))

    @property
    def booked_variance(self) -> Decimal | None:
        if self.booked_current is None or self.booked_previous is None:
            return None
        return (self.booked_current - self.booked_previous).quantize(Decimal("0.01"))


class PayrollWeek(models.Model):
    """Directly entered weekly Payroll values for the configured fiscal year."""

    fiscal_year = models.PositiveSmallIntegerField()
    fiscal_month = models.PositiveSmallIntegerField()
    fiscal_week = models.PositiveSmallIntegerField()
    sales_plan = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    trend_percent = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    sun = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    mon = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    tue = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    wed = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    thu = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    fri = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    sat = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    labor_calculator_target_hours = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fiscal_year", "fiscal_week"]
        constraints = [
            models.UniqueConstraint(fields=["fiscal_year", "fiscal_week"], name="unique_payroll_week")
        ]
        verbose_name = "payroll week"
        verbose_name_plural = "payroll weeks"

    @property
    def actual_sales(self) -> Decimal | None:
        if self.sales_plan is None:
            return None
        trend = self.trend_percent or Decimal("0")
        return (self.sales_plan * (Decimal("1") + trend / Decimal("100"))).quantize(Decimal("0.01"))

    @property
    def total_hours_actual_scheduled(self) -> Decimal:
        fields = (self.sun, self.mon, self.tue, self.wed, self.thu, self.fri, self.sat)
        return sum((value or Decimal("0") for value in fields), Decimal("0")).quantize(Decimal("0.01"))

    @property
    def current_variance(self) -> Decimal | None:
        if self.labor_calculator_target_hours is None:
            return None
        return (self.total_hours_actual_scheduled - self.labor_calculator_target_hours).quantize(Decimal("0.01"))
