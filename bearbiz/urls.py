from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path


def health(request):
    return JsonResponse({"status": "ok", "version": settings.VERSION})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health),
]
