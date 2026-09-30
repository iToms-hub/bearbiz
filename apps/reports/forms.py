from __future__ import annotations

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from .models import ReportGoalSettings, ReportUpload


class ReportGoalForm(forms.Form):
    goal = forms.DecimalField(
        label="Goal %",
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        max_digits=5,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"min": "0", "max": "100", "step": "0.01"}),
    )

    def __init__(self, *args, report_type: str, instance: ReportGoalSettings | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.report_type = report_type
        self.instance = instance or ReportGoalSettings.current()
        field_name = self._field_name()
        self.initial["goal"] = getattr(self.instance, field_name)

    def _field_name(self) -> str:
        return "gift_card_goal" if self.report_type == "gift_cards" else "bonus_club_goal"

    def save(self) -> ReportGoalSettings:
        setattr(self.instance, self._field_name(), self.cleaned_data["goal"])
        self.instance.save()
        return self.instance


class MissedOpportunityUploadForm(forms.Form):
    source_file = forms.FileField(
        label="Missed opportunity PDF",
        widget=forms.ClearableFileInput(attrs={"accept": "application/pdf"}),
    )

    def clean_source_file(self):
        source_file = self.cleaned_data["source_file"]
        content_type = getattr(source_file, "content_type", "") or ""
        filename = getattr(source_file, "name", "") or ""
        if not filename.lower().endswith(".pdf") and content_type.lower() != "application/pdf":
            raise ValidationError("Upload a PDF file.")
        return source_file


class SegmentUploadInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class SegmentUploadField(forms.FileField):
    def clean(self, data, initial=None):
        if not isinstance(data, (list, tuple)):
            data = [data]
        cleaned = []
        for item in data:
            cleaned.append(super().clean(item, initial))
        return cleaned


class SegmentUploadForm(forms.Form):
    fiscal_week = forms.IntegerField(min_value=1, max_value=53, widget=forms.HiddenInput)
    source_files = SegmentUploadField(
        label="Segment report PDFs",
        widget=SegmentUploadInput(attrs={"accept": "application/pdf", "multiple": True}),
    )

    def clean_source_files(self):
        files = self.files.getlist("source_files")
        if not files:
            raise ValidationError("Select at least one segment report PDF.")
        return files


class GanttUploadForm(forms.Form):
    source_files = SegmentUploadField(
        label="Gantt report PDFs",
        widget=SegmentUploadInput(attrs={"accept": "application/pdf", "multiple": True}),
    )

    def clean_source_files(self):
        files = self.files.getlist("source_files")
        if not files:
            raise ValidationError("Select at least one Gantt report PDF.")
        return files


class ReportUploadForm(forms.ModelForm):
    class Meta:
        model = ReportUpload
        fields = ("source_file",)
        widgets = {
            "source_file": forms.ClearableFileInput(attrs={"accept": "application/pdf"}),
        }

    def clean_source_file(self):
        source_file = self.cleaned_data["source_file"]
        content_type = getattr(source_file, "content_type", "") or ""
        filename = getattr(source_file, "name", "") or ""
        if not filename.lower().endswith(".pdf") and content_type.lower() != "application/pdf":
            raise ValidationError("Upload a PDF file.")
        return source_file

    def save(self, commit: bool = True, *, report_type: str = "weekly_sales") -> ReportUpload:
        instance: ReportUpload = super().save(commit=False)
        source_file = self.cleaned_data["source_file"]
        setattr(instance, "report_type", report_type)
        instance.source_name = str(getattr(source_file, "name", "weekly_sales.pdf"))
        if commit:
            instance.save()
        return instance
