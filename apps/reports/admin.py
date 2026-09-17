from django.contrib import admin

from .models import BonusClubSummary, GiftCardsSummary, PartiesSummary, PayrollWeek, RankingSummary, ReportUpload, SegmentsSummary, WeeklySalesSummary


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


@admin.register(PayrollWeek)
class PayrollWeekAdmin(admin.ModelAdmin):
    list_display = ("fiscal_year", "fiscal_month", "fiscal_week", "sales_plan", "actual_sales", "total_hours_actual_scheduled", "current_variance")
    list_filter = ("fiscal_year", "fiscal_month")


@admin.register(PartiesSummary)
class PartiesSummaryAdmin(admin.ModelAdmin):
    list_display = ("fiscal_year", "fiscal_week", "report_upload", "created_at")
    search_fields = ("report_upload__source_name",)
