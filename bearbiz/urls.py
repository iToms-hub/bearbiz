from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import RedirectView

from apps.core.views import coming_soon
from apps.reports.payroll_views import index as payroll_index
from apps.reports.product_views import index as product_index
from apps.reports.gantt_views import index as gantts_index
from apps.reports.missed_opportunities_views import index as missed_opportunities_index
from apps.reports.missed_ops_review_views import index as missed_ops_review_index
from apps.reports.missed_ops_review_views import pdf as missed_ops_review_pdf
from apps.reports.segment_views import index as segments_index
from apps.reports.parties_views import delete as parties_delete
from apps.reports.parties_views import download as parties_download
from apps.reports.parties_views import index as parties_index
from apps.reports.parties_views import upload_page as parties_uploads
from apps.reports.views import (
    dashboard,
    dashboard_review,
    dashboard_review_pdf,
    performance,
    performance_pdf,
)


def health(request):
    return JsonResponse({"status": "ok", "version": settings.VERSION})


urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("dashboard/last-week/", dashboard, name="dashboard-last-week"),
    path("dashboard/review/pdf/", dashboard_review_pdf, name="dashboard-review-pdf"),
    path("dashboard/review/", dashboard_review, name="dashboard-review"),
    path("performance/", performance, name="performance"),
    path("performance/pdf/", performance_pdf, name="performance-pdf"),
    path("missed-ops/", RedirectView.as_view(pattern_name="missed-ops-mo-reports", permanent=False), name="missed-ops"),
    path("missed-ops/mo-reports/", missed_opportunities_index, name="missed-ops-mo-reports"),
    path("missed-ops/segments/", segments_index, name="missed-ops-segments"),
    path("missed-ops/gantts/", gantts_index, name="missed-ops-gantts"),
    path("missed-ops/review/", missed_ops_review_index, name="missed-ops-review"),
    path("missed-ops/review/pdf/", missed_ops_review_pdf, name="missed-ops-review-pdf"),
    path("payroll/", payroll_index, name="payroll"),
    path("product/", product_index, name="product"),
    path("parties/uploads/", parties_uploads, name="parties-uploads"),
    path("parties/uploads/<int:pk>/download/", parties_download, name="parties-download"),
    path("parties/uploads/<int:pk>/delete/", parties_delete, name="parties-delete"),
    path("parties/", parties_index, name="parties"),
    path("reports/", include(("apps.reports.urls", "reports"), namespace="reports")),
    path("agent/", include(("apps.agent.urls", "agent"), namespace="agent")),
    path("settings/", include(("apps.core.urls", "settings"), namespace="settings")),
    path("admin/", admin.site.urls),
    path("health/", health),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
