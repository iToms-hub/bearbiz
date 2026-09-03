from __future__ import annotations

from django import forms

from .models import FiscalYearSettings


class FiscalYearSettingsForm(forms.ModelForm):
    class Meta:
        model = FiscalYearSettings
        fields = (
            "calendar_pattern",
            "boundary_rule",
            "boundary_month",
            "boundary_weekday",
        )
        help_texts = {
            "calendar_pattern": "Use the 4-5-4 pattern unless your business explicitly runs a different retail calendar.",
        }
