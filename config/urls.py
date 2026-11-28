"""Root URL configuration for LabTrack."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path


def health_placeholder(request):
    """Minimal root placeholder view for Session 1 foundation."""
    return HttpResponse(
        "LabTrack — Sistem Manajemen Inventaris dan Pemeliharaan Aset Laboratorium (Pondasi Sesi 1 siap)."
    )


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", health_placeholder, name="home"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
