from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from apps.reports.views import dashboard


def health(request):
    return JsonResponse({"status": "ok", "version": settings.VERSION})


urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("reports/", include(("apps.reports.urls", "reports"), namespace="reports")),
    path("settings/", include(("apps.core.urls", "settings"), namespace="settings")),
    path("admin/", admin.site.urls),
    path("health/", health),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
