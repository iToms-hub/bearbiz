from __future__ import annotations

from django.urls import path

from .views import settings_page

app_name = "settings"

urlpatterns = [
    path("", settings_page, name="index"),
    path("section/<slug:slug>/", settings_page, name="section"),
]
