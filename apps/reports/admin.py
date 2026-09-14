from django.contrib import admin

from .models import BonusClubSummary, GiftCardsSummary, PartiesSummary, PayrollSummary, RankingSummary, ReportUpload, SegmentsSummary, WeeklySalesSummary


@admin.register(ReportUpload)
class ReportUploadAdmin(admin.ModelAdmin):
    list_display = ("source_name", "report_type", "parse_status", "uploaded_at", "parsed_at")
    list_filter = ("report_type", "parse_status", "uploaded_at")
    search_fields = ("source_name",)


@admin.register(WeeklySalesSummary)
class WeeklySalesSummaryAdmin(admin.ModelAdmin):
    list_display = ("fiscal_year", "fiscal_week", "report_upload", "fiscal_period_start", "fiscal_period_end", "created_at")
    search_fields = ("report_upload__source_name",)


@admin.register(RankingSummary)
class RankingSummaryAdmin(admin.ModelAdmin):
    list_display = ("fiscal_year", "fiscal_week", "report_upload", "fiscal_period_start", "fiscal_period_end", "created_at")
    search_fields = ("report_upload__source_name",)


@admin.register(GiftCardsSummary)
class GiftCardsSummaryAdmin(admin.ModelAdmin):
    list_display = ("fiscal_year", "fiscal_week", "report_upload", "fiscal_period_start", "fiscal_period_end", "created_at")
    search_fields = ("report_upload__source_name",)


@admin.register(BonusClubSummary)
class BonusClubSummaryAdmin(admin.ModelAdmin):
    list_display = ("fiscal_year", "fiscal_week", "report_upload", "fiscal_period_start", "fiscal_period_end", "created_at")
    search_fields = ("report_upload__source_name",)


@admin.register(SegmentsSummary)
class SegmentsSummaryAdmin(admin.ModelAdmin):
    list_display = ("fiscal_year", "fiscal_week", "report_upload", "fiscal_period_start", "fiscal_period_end", "created_at")
    search_fields = ("report_upload__source_name",)


@admin.register(PayrollSummary)
class PayrollSummaryAdmin(admin.ModelAdmin):
    list_display = ("source_date", "source_week", "current_week", "report_upload", "created_at")
    list_filter = ("current_week", "source_month")
    search_fields = ("report_upload__source_name",)


@admin.register(PartiesSummary)
class PartiesSummaryAdmin(admin.ModelAdmin):
    list_display = ("fiscal_year", "fiscal_week", "report_upload", "created_at")
    search_fields = ("report_upload__source_name",)
