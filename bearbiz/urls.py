from django.contrib import admin
from django.http import JsonResponse
from django.urls import path


def health(request):
    return JsonResponse({"status": "ok", "version": "0.0.1"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health),
]
