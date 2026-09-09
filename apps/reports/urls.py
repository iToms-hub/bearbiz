from __future__ import annotations

from django.urls import path

from .views import report_delete, report_detail, report_download, report_history, report_pdf, report_section, report_upload

app_name = "reports"

urlpatterns = [
    path("", report_section, kwargs={"number": 1}, name="index"),
    path("report-<int:number>/", report_section, name="report-number"),
    path("report-<int:number>/pdf/", report_pdf, name="report-pdf"),
    path("uploads/", report_history, name="history"),
    path("uploads/report-<int:number>/", report_history, name="history-number"),
    path("uploads/new/", report_upload, name="upload"),
    path("uploads/<int:pk>/", report_detail, name="detail"),
    path("uploads/<int:pk>/download/", report_download, name="download"),
    path("uploads/<int:pk>/delete/", report_delete, name="delete"),
]
