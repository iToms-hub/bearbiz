from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from apps.core.views import coming_soon
from apps.reports.payroll_views import delete as payroll_delete
from apps.reports.payroll_views import download as payroll_download
from apps.reports.payroll_views import index as payroll_index
from apps.reports.payroll_views import upload_page as payroll_uploads
from apps.reports.parties_views import delete as parties_delete
from apps.reports.parties_views import download as parties_download
from apps.reports.parties_views import index as parties_index
from apps.reports.parties_views import upload_page as parties_uploads
from apps.reports.views import dashboard, performance, performance_pdf


def health(request):
    return JsonResponse({"status": "ok", "version": settings.VERSION})


urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("performance/", performance, name="performance"),
    path("performance/pdf/", performance_pdf, name="performance-pdf"),
    path("missed-ops/", coming_soon, {"feature": "Missed Ops"}, name="missed-ops"),
    path("payroll/uploads/", payroll_uploads, name="payroll-uploads"),
    path("payroll/uploads/<int:pk>/download/", payroll_download, name="payroll-download"),
    path("payroll/uploads/<int:pk>/delete/", payroll_delete, name="payroll-delete"),
    path("payroll/", payroll_index, name="payroll"),
    path("product/", coming_soon, {"feature": "Product"}, name="product"),
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
