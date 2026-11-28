"""Root URL configuration for LabTrack."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.inventory.views import asset_qr_scan_view
from apps.reports.views import dashboard_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.reports.urls")),
    path("", dashboard_view, name="home"),
    path("", include("apps.core.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("loans/", include("apps.loans.urls")),
    path("maintenance/", include("apps.maintenance.urls")),
    path("scan/<str:asset_code>/", asset_qr_scan_view, name="asset_qr_scan"),
]

handler403 = "apps.core.views.custom_403"
handler404 = "apps.core.views.custom_404"

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
