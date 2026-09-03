from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from .models import ReportUpload


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

    def save(self, commit: bool = True) -> ReportUpload:
        instance: ReportUpload = super().save(commit=False)
        source_file = self.cleaned_data["source_file"]
        instance.source_name = str(getattr(source_file, "name", "weekly_sales.pdf"))
        if commit:
            instance.save()
        return instance
