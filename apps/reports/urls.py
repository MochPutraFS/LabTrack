"""URL routes for LabTrack dashboard and reports."""

from django.urls import path

from apps.reports import views

app_name = "reports"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("reports/api/dashboard-charts/", views.api_dashboard_charts_view, name="api_dashboard_charts"),
    path("reports/condition/", views.condition_report_view, name="condition_report"),
    path("reports/depreciation/", views.depreciation_report_view, name="depreciation_report"),
]
