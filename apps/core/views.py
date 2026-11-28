"""Core views: home redirect and custom HTTP error handlers."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


@login_required
def home_redirect(request):
    """Temporary home landing redirecting to asset catalog until Session 5 dashboard."""
    return redirect("inventory:asset_list")


def custom_403(request, exception=None):
    """Render custom 403 Forbidden page."""
    return render(
        request,
        "errors/403.html",
        {"error_message": str(exception) if exception else ""},
        status=403,
    )


def custom_404(request, exception=None):
    """Render custom 404 Not Found page."""
    return render(request, "errors/404.html", status=404)
