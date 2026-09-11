from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from apps.core.views import coming_soon
from apps.reports.views import dashboard, performance, performance_pdf


def health(request):
    return JsonResponse({"status": "ok", "version": settings.VERSION})


urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("performance/", performance, name="performance"),
    path("performance/pdf/", performance_pdf, name="performance-pdf"),
    path("missed-ops/", coming_soon, {"feature": "Missed Ops"}, name="missed-ops"),
    path("payroll/", coming_soon, {"feature": "Payroll"}, name="payroll"),
    path("product/", coming_soon, {"feature": "Product"}, name="product"),
    path("parties/", coming_soon, {"feature": "Parties"}, name="parties"),
    path("reports/", include(("apps.reports.urls", "reports"), namespace="reports")),
    path("agent/", include(("apps.agent.urls", "agent"), namespace="agent")),
    path("settings/", include(("apps.core.urls", "settings"), namespace="settings")),
    path("admin/", admin.site.urls),
    path("health/", health),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
