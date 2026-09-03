from django.contrib import admin

from .models import ReportUpload, WeeklySalesSummary


@admin.register(ReportUpload)
class ReportUploadAdmin(admin.ModelAdmin):
    list_display = ("source_name", "parse_status", "uploaded_at", "parsed_at")
    list_filter = ("parse_status", "uploaded_at")
    search_fields = ("source_name",)


@admin.register(WeeklySalesSummary)
class WeeklySalesSummaryAdmin(admin.ModelAdmin):
    list_display = (
        "fiscal_year",
        "fiscal_week",
        "report_upload",
        "fiscal_period_start",
        "fiscal_period_end",
        "created_at",
    )
    search_fields = ("report_upload__source_name",)
