from __future__ import annotations

from django import forms

from .models import AIIntegrationSettings, FiscalYearSettings


class FiscalYearSettingsForm(forms.ModelForm):
    class Meta:
        model = FiscalYearSettings
        fields = (
            "fiscal_year_start_date",
        )
        help_texts = {
            "fiscal_year_start_date": "Set the first day of the fiscal year; the 4-5-4 calendar stays fixed internally.",
        }
        widgets = {
            "fiscal_year_start_date": forms.DateInput(attrs={"type": "date"}),
        }


class AIIntegrationSettingsForm(forms.ModelForm):
    model_name = forms.ChoiceField(choices=(), widget=forms.Select())

    class Meta:
        model = AIIntegrationSettings
        fields = (
            "enabled",
            "provider_name",
            "api_base_url",
            "api_key_env_var",
            "model_name",
            "temperature",
            "max_output_tokens",
        )
        help_texts = {
            "enabled": "Turn AI enrichment on only after the endpoint is ready.",
            "api_base_url": "Use the API root that includes /v1, for example https://api.openai.com/v1.",
            "api_key_env_var": "Leave blank for local endpoints that do not require an API key; otherwise enter the environment variable name that stores it.",
            "temperature": "Lower values stay more deterministic; higher values get looser.",
        }
        widgets = {
            "api_base_url": forms.URLInput(attrs={"placeholder": "https://api.openai.com/v1"}),
            "model_name": forms.Select(),
        }

    def __init__(self, *args, available_models: tuple[str, ...] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.available_models = tuple(available_models or ())
        self.fields["api_key_env_var"].required = False
        self.fields["api_key_env_var"].widget.attrs.setdefault("placeholder", "BEARBIZ_AI_API_KEY (or leave blank)")
        self.fields["model_name"].choices = self._build_model_choices()
        self.fields["model_name"].widget.attrs.setdefault("data-ai-model-select", "true")
        current_base_url = str(self.initial.get("api_base_url") or self.fields["api_base_url"].initial or "")
        if current_base_url:
            cleaned = current_base_url.strip().rstrip("/")
            if not cleaned.endswith("/v1"):
                cleaned = f"{cleaned}/v1"
            self.initial["api_base_url"] = cleaned

    def _build_model_choices(self) -> list[tuple[str, str]]:
        choices = [(value, value) for value in self.available_models]
        current_value = self.initial.get("model_name") or self.data.get("model_name") if hasattr(self, "data") else None
        current_value = str(current_value or "").strip()
        if current_value and current_value not in {value for value, _ in choices}:
            choices.insert(0, (current_value, current_value))
        return choices or [("", "No models returned by the endpoint")]
