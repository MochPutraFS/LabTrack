"""Core views: audit log listing (ADMIN only) and custom HTTP error handlers."""

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from apps.core.models import AuditLog
from apps.core.permissions import role_required


@role_required("ADMIN")
def audit_log_list_view(request):
    """Paginated immutable audit trail view restricted strictly to ADMIN."""
    q = (request.GET.get("q") or "").strip()
    action = (request.GET.get("action") or "").strip()
    entity_type = (request.GET.get("entity_type") or "").strip()

    qs = AuditLog.objects.select_related("actor")
    if q:
        qs = qs.filter(
            Q(action__icontains=q)
            | Q(entity_type__icontains=q)
            | Q(entity_id__icontains=q)
            | Q(actor__username__icontains=q)
            | Q(actor__full_name__icontains=q)
        )
    if action:
        qs = qs.filter(action=action)
    if entity_type:
        qs = qs.filter(entity_type=entity_type)

    page_obj = Paginator(qs, 25).get_page(request.GET.get("page"))

    actions = AuditLog.objects.values_list("action", flat=True).distinct().order_by("action")
    entity_types = (
        AuditLog.objects.values_list("entity_type", flat=True).distinct().order_by("entity_type")
    )

    return render(
        request,
        "core/audit_log_list.html",
        {
            "page_obj": page_obj,
            "actions": actions,
            "entity_types": entity_types,
            "filters": {
                "q": q,
                "action": action,
                "entity_type": entity_type,
            },
        },
    )


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
