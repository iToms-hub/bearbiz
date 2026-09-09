from __future__ import annotations

from django.urls import path

from .views import ai_connection_test, ai_model_suggestions, backup_action, settings_page

app_name = "settings"

urlpatterns = [
    path("", settings_page, name="index"),
    path("fiscal/", settings_page, kwargs={"slug": "fiscal"}, name="fiscal"),
    path("ai/", settings_page, kwargs={"slug": "ai"}, name="ai"),
    path("ai/test/", ai_connection_test, name="ai-test"),
    path("ai/models/", ai_model_suggestions, name="ai-models"),
    path("backup/", settings_page, kwargs={"slug": "backup"}, name="backup"),
    path("backup/action/", backup_action, name="backup-action"),
    path("section/<slug:slug>/", settings_page, name="section"),
]
