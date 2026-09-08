from __future__ import annotations

from typing import Any

from django.db import models


class ParseStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PARSED = "parsed", "Parsed"
    FAILED = "failed", "Failed"


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
