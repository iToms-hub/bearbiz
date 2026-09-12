from __future__ import annotations

from django.contrib import admin

from .forms import AIIntegrationSettingsForm, FiscalYearSettingsForm
from .models import AIIntegrationSettings, FiscalYearSettings


@admin.register(FiscalYearSettings)
class FiscalYearSettingsAdmin(admin.ModelAdmin):
    form = FiscalYearSettingsForm
    list_display = ("fiscal_year_start_date",)
    fields = ("fiscal_year_start_date",)

    def has_add_permission(self, request) -> bool:
        return not FiscalYearSettings.objects.exists()

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(AIIntegrationSettings)
class AIIntegrationSettingsAdmin(admin.ModelAdmin):
    form = AIIntegrationSettingsForm
    list_display = (
        "enabled",
        "provider_name",
        "api_base_url",
        "model_name",
        "api_key",
        "updated_at",
    )
    fields = (
        "enabled",
        "provider_name",
        "api_base_url",
        "api_key",
        "model_name",
        "temperature",
        "max_output_tokens",
    )

    def has_add_permission(self, request) -> bool:
        return not AIIntegrationSettings.objects.exists()

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
