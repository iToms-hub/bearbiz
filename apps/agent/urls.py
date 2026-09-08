from __future__ import annotations

from django.urls import path

from .views import agent_chat

app_name = "agent"

urlpatterns = [
    path("", agent_chat, name="index"),
]
