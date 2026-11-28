"""URL routing for Damage Reports, Maintenance Schedules, and Maintenance Logs."""

from django.urls import path

from apps.maintenance import views

app_name = "maintenance"

urlpatterns = [
    # Damage Reports (FR-07)
    path("damages/", views.damage_list_view, name="damage_list"),
    path("damages/create/", views.damage_create_view, name="damage_create"),
    path("damages/<int:pk>/", views.damage_detail_view, name="damage_detail"),
    path("damages/<int:pk>/status/", views.damage_update_status_view, name="damage_update_status"),
    # Maintenance Schedules (FR-08)
    path("schedules/", views.schedule_list_view, name="schedule_list"),
    path("schedules/create/", views.schedule_create_view, name="schedule_create"),
    path("schedules/<int:pk>/edit/", views.schedule_edit_view, name="schedule_edit"),
    path("schedules/<int:pk>/execute/", views.schedule_execute_view, name="schedule_execute"),
    # Maintenance Logs (FR-08)
    path("logs/", views.log_list_view, name="log_list"),
]
