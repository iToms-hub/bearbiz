from __future__ import annotations

from django.urls import path

from .views import report_detail, report_download, report_history, report_section, report_upload

app_name = "reports"

urlpatterns = [
    path("", report_section, kwargs={"number": 1}, name="index"),
    path("report-<int:number>/", report_section, name="report-number"),
    path("uploads/", report_history, name="history"),
    path("uploads/new/", report_upload, name="upload"),
    path("uploads/<int:pk>/", report_detail, name="detail"),
    path("uploads/<int:pk>/download/", report_download, name="download"),
]
