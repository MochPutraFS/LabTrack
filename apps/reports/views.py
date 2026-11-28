"""Views for Dashboard, Chart.js JSON API, Condition Report, and Depreciation Report."""

from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from apps.core.permissions import STAFF_ROLES, role_required
from apps.inventory.models import Asset, Category, Location
from apps.reports import services


def _parse_int(raw: str | None) -> int | None:
    cleaned = (raw or "").strip()
    return int(cleaned) if cleaned.isdigit() else None


def _parse_as_of_date(request) -> date:
    raw = (request.GET.get("as_of") or "").strip()
    if not raw:
        return timezone.localdate()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        messages.warning(request, "Format tanggal acuan tidak valid, menggunakan tanggal hari ini.")
        return timezone.localdate()


def _build_filter_summary(category_id: int | None, location_id: int | None) -> str:
    parts: list[str] = []
    if category_id:
        cat = Category.objects.filter(pk=category_id).first()
        if cat:
            parts.append(f"Kategori: {cat.name}")
    if location_id:
        loc = Location.objects.filter(pk=location_id).first()
        if loc:
            parts.append(f"Lokasi: {loc.code} - {loc.name}")
    return ", ".join(parts) if parts else "Semua Kategori & Lokasi"


@login_required
def dashboard_view(request):
    """Main role-aware dashboard (full analytics for staff, personal loan summary for borrower)."""
    if request.user.is_staff_lab:
        context = services.get_staff_dashboard_context()
        return render(request, "reports/dashboard_staff.html", context)

    context = services.get_borrower_dashboard_context(request.user)
    return render(request, "reports/dashboard_borrower.html", context)


@role_required(*STAFF_ROLES)
def api_dashboard_charts_view(request):
    """Return JSON payload for the 3 Chart.js visualizations on the staff dashboard."""
    return JsonResponse(services.get_dashboard_charts_payload())


@role_required(*STAFF_ROLES)
def condition_report_view(request):
    """Asset Condition Report grouped by location or category, with CSV & PDF export."""
    category_id = _parse_int(request.GET.get("category"))
    location_id = _parse_int(request.GET.get("location"))
    group_by = (request.GET.get("group_by") or "location").strip().lower()
    if group_by not in ("location", "category"):
        group_by = "location"

    report = services.get_condition_report(
        category_id=category_id,
        location_id=location_id,
        group_by=group_by,
    )

    export_fmt = (request.GET.get("export") or "").strip().lower()
    if export_fmt == "csv":
        payload = services.build_condition_csv(report)
        response = HttpResponse(payload, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="labtrack-laporan-kondisi-{timezone.localdate().isoformat()}.csv"'
        )
        return response

    if export_fmt == "pdf":
        filter_summary = _build_filter_summary(category_id, location_id)
        payload = services.build_condition_pdf(report, filter_summary=filter_summary)
        response = HttpResponse(payload, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="labtrack-laporan-kondisi-{timezone.localdate().isoformat()}.pdf"'
        )
        return response

    return render(
        request,
        "reports/condition_report.html",
        {
            "report": report,
            "categories": Category.objects.all(),
            "locations": Location.objects.filter(is_active=True),
            "filters": {
                "category": str(category_id or ""),
                "location": str(location_id or ""),
                "group_by": group_by,
            },
        },
    )


@role_required(*STAFF_ROLES)
def depreciation_report_view(request):
    """Straight-Line Asset Depreciation Report as of a reference date, with CSV & PDF export."""
    category_id = _parse_int(request.GET.get("category"))
    location_id = _parse_int(request.GET.get("location"))
    as_of_date = _parse_as_of_date(request)

    qs = Asset.objects.filter(is_active=True).exclude(status=Asset.Status.RETIRED)
    if category_id:
        qs = qs.filter(category_id=category_id)
    if location_id:
        qs = qs.filter(location_id=location_id)

    report = services.calculate_portfolio_depreciation(qs, as_of_date=as_of_date)

    export_fmt = (request.GET.get("export") or "").strip().lower()
    if export_fmt == "csv":
        payload = services.build_depreciation_csv(report)
        response = HttpResponse(payload, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="labtrack-laporan-penyusutan-{as_of_date.isoformat()}.csv"'
        )
        return response

    if export_fmt == "pdf":
        filter_summary = _build_filter_summary(category_id, location_id)
        payload = services.build_depreciation_pdf(report, filter_summary=filter_summary)
        response = HttpResponse(payload, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="labtrack-laporan-penyusutan-{as_of_date.isoformat()}.pdf"'
        )
        return response

    return render(
        request,
        "reports/depreciation_report.html",
        {
            "report": report,
            "categories": Category.objects.all(),
            "locations": Location.objects.filter(is_active=True),
            "filters": {
                "as_of": as_of_date.isoformat(),
                "category": str(category_id or ""),
                "location": str(location_id or ""),
            },
        },
    )
