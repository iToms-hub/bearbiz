from django.contrib import admin

from .models import BonusClubSummary, GiftCardsSummary, PartiesSummary, PartiesWeek, PayrollWeek, ProductItem, ProductReport, RankingSummary, ReportUpload, SegmentsSummary, WeeklySalesSummary


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


@admin.register(ProductReport)
class ProductReportAdmin(admin.ModelAdmin):
    list_display = ("fiscal_year", "fiscal_week", "store_number", "row_count", "parse_status", "period_end")
    list_filter = ("fiscal_year", "parse_status")


@admin.register(ProductItem)
class ProductItemAdmin(admin.ModelAdmin):
    list_display = ("report", "department", "department_rank", "item_number", "item_description", "units_sold", "net_sales")
    list_filter = ("department",)
    search_fields = ("item_number", "item_description")


@admin.register(PartiesWeek)
class PartiesWeekAdmin(admin.ModelAdmin):
    list_display = ("fiscal_year", "fiscal_month", "fiscal_week", "held_current", "held_previous", "booked_current", "booked_previous")
    list_filter = ("fiscal_year", "fiscal_month")
