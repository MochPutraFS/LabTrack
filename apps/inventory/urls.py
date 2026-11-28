"""URL routing for inventory module (docs/05-Architecture-dan-API.md §3.2)."""

from django.urls import path

from apps.inventory import views

app_name = "inventory"

urlpatterns = [
    # Assets
    path("assets/", views.asset_list_view, name="asset_list"),
    path("assets/create/", views.asset_create_view, name="asset_create"),
    path("assets/qr/print/", views.asset_qr_print_view, name="asset_qr_print"),
    path("assets/<int:pk>/", views.asset_detail_view, name="asset_detail"),
    path("assets/<int:pk>/edit/", views.asset_edit_view, name="asset_edit"),
    path("assets/<int:pk>/move/", views.asset_move_view, name="asset_move"),
    path("assets/<int:pk>/retire/", views.asset_retire_view, name="asset_retire"),
    path("assets/<int:pk>/qr/download/", views.asset_qr_download_view, name="asset_qr_download"),
    # Categories
    path("categories/", views.category_list_view, name="category_list"),
    path("categories/<int:pk>/edit/", views.category_edit_view, name="category_edit"),
    path("categories/<int:pk>/delete/", views.category_delete_view, name="category_delete"),
    # Locations
    path("locations/", views.location_list_view, name="location_list"),
    path("locations/<int:pk>/edit/", views.location_edit_view, name="location_edit"),
    path("locations/<int:pk>/delete/", views.location_delete_view, name="location_delete"),
]
