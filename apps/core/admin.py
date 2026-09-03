from __future__ import annotations

from django.contrib import admin

from .forms import FiscalYearSettingsForm
from .models import FiscalYearSettings


@admin.register(FiscalYearSettings)
class FiscalYearSettingsAdmin(admin.ModelAdmin):
    form = FiscalYearSettingsForm
    list_display = (
        "calendar_pattern",
        "boundary_rule",
        "boundary_month",
        "boundary_weekday",
    )
    fields = (
        "calendar_pattern",
        "boundary_rule",
        "boundary_month",
        "boundary_weekday",
    )

    def has_add_permission(self, request) -> bool:
        return not FiscalYearSettings.objects.exists()

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
