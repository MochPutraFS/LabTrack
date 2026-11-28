"""URL routes for core administrative endpoints."""

from django.urls import path

from apps.core import views

app_name = "core"

urlpatterns = [
    path("audit-logs/", views.audit_log_list_view, name="audit_log_list"),
]
