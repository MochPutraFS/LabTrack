"""Views for Damage Reports, Maintenance Schedules, and Maintenance Logs."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.permissions import STAFF_ROLES, role_required
from apps.inventory.models import Asset
from apps.maintenance import services
from apps.maintenance.forms import (
    DamageReportCreateForm,
    DamageReportStatusForm,
    MaintenanceExecuteForm,
    MaintenanceScheduleForm,
)
from apps.maintenance.models import DamageReport, MaintenanceLog, MaintenanceSchedule


def _parse_iso_date(raw: str) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


# --- Damage Reports (FR-07) ---


@login_required
def damage_list_view(request):
    """List damage reports with search, status, and severity filters."""
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    severity = (request.GET.get("severity") or "").strip()

    qs = DamageReport.objects.select_related(
        "asset",
        "asset__category",
        "asset__location",
        "reported_by",
        "handled_by",
    ).order_by("-created_at")

    if q:
        qs = qs.filter(
            Q(report_number__icontains=q)
            | Q(asset__asset_code__icontains=q)
            | Q(asset__name__icontains=q)
            | Q(description__icontains=q)
        )
    if status in DamageReport.Status.values:
        qs = qs.filter(status=status)
    if severity in DamageReport.Severity.values:
        qs = qs.filter(severity=severity)

    page_obj = Paginator(qs, 12).get_page(request.GET.get("page"))

    return render(
        request,
        "maintenance/damage_list.html",
        {
            "page_obj": page_obj,
            "statuses": DamageReport.Status.choices,
            "severities": DamageReport.Severity.choices,
            "filters": {"q": q, "status": status, "severity": severity},
        },
    )


@login_required
def damage_create_view(request):
    """Allow any authenticated user to submit a DamageReport (supports ?asset=<id>)."""
    initial = {}
    preselected_asset = None
    if request.method == "GET":
        raw_asset = (request.GET.get("asset") or "").strip()
        if raw_asset.isdigit():
            candidate = (
                Asset.objects.select_related("category", "location")
                .filter(pk=int(raw_asset), is_active=True)
                .exclude(status=Asset.Status.RETIRED)
                .first()
            )
            if candidate:
                initial["asset"] = candidate.pk
                preselected_asset = candidate

    form = DamageReportCreateForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            report = services.create_damage_report(
                asset=form.cleaned_data["asset"],
                reported_by=request.user,
                severity=form.cleaned_data["severity"],
                description=form.cleaned_data["description"],
                photo=form.cleaned_data.get("photo"),
            )
            messages.success(
                request,
                f"Laporan kerusakan {report.report_number} untuk aset {report.asset.asset_code} berhasil dibuat.",
            )
            return redirect("maintenance:damage_detail", pk=report.pk)
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))

    return render(
        request,
        "maintenance/damage_form.html",
        {
            "form": form,
            "preselected_asset": preselected_asset,
        },
    )


@login_required
def damage_detail_view(request, pk: int):
    """Display full DamageReport details, evidence photo, logs, and staff follow-up panel."""
    report = get_object_or_404(
        DamageReport.objects.select_related(
            "asset",
            "asset__category",
            "asset__location",
            "reported_by",
            "handled_by",
        ),
        pk=pk,
    )
    allowed_next = services.get_allowed_damage_next_statuses(report.status)
    can_update_status = bool(request.user.is_staff_lab and allowed_next)
    status_form = DamageReportStatusForm(report=report) if can_update_status else None
    related_logs = report.maintenance_logs.select_related("performed_by").order_by("-performed_date", "-id")

    return render(
        request,
        "maintenance/damage_detail.html",
        {
            "report": report,
            "can_update_status": can_update_status,
            "status_form": status_form,
            "has_resolved_option": any(val == DamageReport.Status.RESOLVED for val, _ in allowed_next),
            "related_logs": related_logs,
        },
    )


@role_required(*STAFF_ROLES)
@require_POST
def damage_update_status_view(request, pk: int):
    """Advance DamageReport status along the state machine (ADMIN/LABORAN only)."""
    report = get_object_or_404(DamageReport.objects.select_related("asset"), pk=pk)
    form = DamageReportStatusForm(request.POST, report=report)
    if form.is_valid():
        try:
            result = services.update_damage_report_status(
                report=report,
                staff_user=request.user,
                new_status=form.cleaned_data["new_status"],
                resolution_notes=form.cleaned_data.get("resolution_notes", ""),
                create_maintenance_log=bool(form.cleaned_data.get("create_maintenance_log")),
                repair_cost=form.cleaned_data.get("repair_cost"),
                repair_summary=form.cleaned_data.get("repair_summary", ""),
                performed_date=form.cleaned_data.get("performed_date"),
            )
            updated = result["report"]
            msg = (
                f"Status laporan {updated.report_number} diperbarui menjadi "
                f"'{updated.get_status_display()}'."
            )
            if result["maintenance_log"] is not None:
                msg += " Log pemeliharaan & biaya perbaikan telah dicatat."
            messages.success(request, msg)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    else:
        errors = []
        for field_errors in form.errors.values():
            errors.extend(field_errors)
        messages.error(request, "Gagal memperbarui status: " + "; ".join(errors))
    return redirect("maintenance:damage_detail", pk=report.pk)


# --- Maintenance Schedules (FR-08) ---


@role_required(*STAFF_ROLES)
def schedule_list_view(request):
    """List maintenance schedules with H-7 due-soon & OVERDUE visual highlights."""
    today = timezone.localdate()
    due_soon_limit = today + timedelta(days=7)
    services.sync_overdue_schedules(today=today)

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    frequency = (request.GET.get("frequency") or "").strip()
    due_filter = (request.GET.get("due") or "").strip()

    base_qs = MaintenanceSchedule.objects.select_related(
        "asset",
        "asset__category",
        "asset__location",
        "assigned_to",
    )

    overdue_count = base_qs.filter(status=MaintenanceSchedule.Status.OVERDUE).count()
    due_soon_count = base_qs.filter(
        status__in=(MaintenanceSchedule.Status.SCHEDULED, MaintenanceSchedule.Status.IN_PROGRESS),
        next_due_date__gte=today,
        next_due_date__lte=due_soon_limit,
    ).count()

    qs = base_qs.order_by("next_due_date", "id")
    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(asset__asset_code__icontains=q)
            | Q(asset__name__icontains=q)
            | Q(assigned_to__full_name__icontains=q)
        )
    if status in MaintenanceSchedule.Status.values:
        qs = qs.filter(status=status)
    if frequency in MaintenanceSchedule.Frequency.values:
        qs = qs.filter(frequency=frequency)
    if due_filter == "overdue":
        qs = qs.filter(status=MaintenanceSchedule.Status.OVERDUE)
    elif due_filter == "due_soon":
        qs = qs.filter(
            status__in=(MaintenanceSchedule.Status.SCHEDULED, MaintenanceSchedule.Status.IN_PROGRESS),
            next_due_date__gte=today,
            next_due_date__lte=due_soon_limit,
        )

    page_obj = Paginator(qs, 12).get_page(request.GET.get("page"))

    return render(
        request,
        "maintenance/schedule_list.html",
        {
            "page_obj": page_obj,
            "statuses": MaintenanceSchedule.Status.choices,
            "frequencies": MaintenanceSchedule.Frequency.choices,
            "overdue_count": overdue_count,
            "due_soon_count": due_soon_count,
            "filters": {
                "q": q,
                "status": status,
                "frequency": frequency,
                "due": due_filter,
            },
        },
    )


@role_required(*STAFF_ROLES)
def schedule_create_view(request):
    """Create a new MaintenanceSchedule (supports ?asset=<id>)."""
    initial = {}
    if request.method == "GET":
        raw_asset = (request.GET.get("asset") or "").strip()
        if raw_asset.isdigit():
            candidate = (
                Asset.objects.filter(pk=int(raw_asset), is_active=True)
                .exclude(status=Asset.Status.RETIRED)
                .first()
            )
            if candidate:
                initial["asset"] = candidate.pk

    form = MaintenanceScheduleForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            schedule = services.create_or_update_schedule(
                staff_user=request.user,
                asset=form.cleaned_data["asset"],
                title=form.cleaned_data["title"],
                description=form.cleaned_data.get("description", ""),
                frequency=form.cleaned_data["frequency"],
                next_due_date=form.cleaned_data["next_due_date"],
                assigned_to=form.cleaned_data.get("assigned_to"),
            )
            messages.success(
                request,
                f"Jadwal pemeliharaan '{schedule.title}' untuk {schedule.asset.asset_code} berhasil dibuat.",
            )
            return redirect("maintenance:schedule_list")
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))

    return render(
        request,
        "maintenance/schedule_form.html",
        {"form": form, "is_edit": False},
    )


@role_required(*STAFF_ROLES)
def schedule_edit_view(request, pk: int):
    """Edit an existing MaintenanceSchedule."""
    schedule = get_object_or_404(MaintenanceSchedule.objects.select_related("asset"), pk=pk)
    form = MaintenanceScheduleForm(request.POST or None, instance=schedule)
    if request.method == "POST" and form.is_valid():
        try:
            updated = services.create_or_update_schedule(
                staff_user=request.user,
                asset=form.cleaned_data["asset"],
                title=form.cleaned_data["title"],
                description=form.cleaned_data.get("description", ""),
                frequency=form.cleaned_data["frequency"],
                next_due_date=form.cleaned_data["next_due_date"],
                assigned_to=form.cleaned_data.get("assigned_to"),
                status=form.cleaned_data.get("status"),
                schedule=schedule,
            )
            messages.success(request, f"Jadwal pemeliharaan '{updated.title}' berhasil diperbarui.")
            return redirect("maintenance:schedule_list")
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))

    return render(
        request,
        "maintenance/schedule_form.html",
        {"form": form, "is_edit": True, "schedule": schedule},
    )


@role_required(*STAFF_ROLES)
def schedule_execute_view(request, pk: int):
    """Record execution of a MaintenanceSchedule and generate MaintenanceLog."""
    schedule = get_object_or_404(
        MaintenanceSchedule.objects.select_related("asset", "asset__category", "asset__location", "assigned_to"),
        pk=pk,
    )
    if schedule.status in (MaintenanceSchedule.Status.COMPLETED, MaintenanceSchedule.Status.CANCELLED):
        messages.error(
            request,
            f"Jadwal '{schedule.title}' berstatus '{schedule.get_status_display()}' sehingga tidak dapat dieksekusi.",
        )
        return redirect("maintenance:schedule_list")

    form = MaintenanceExecuteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            result = services.execute_maintenance_schedule(
                schedule=schedule,
                staff_user=request.user,
                performed_date=form.cleaned_data["performed_date"],
                summary=form.cleaned_data["summary"],
                cost=form.cleaned_data["cost"],
                result_condition=form.cleaned_data["result_condition"],
            )
            updated_schedule = result["schedule"]
            if updated_schedule.frequency == MaintenanceSchedule.Frequency.ONCE:
                messages.success(
                    request,
                    f"Pemeliharaan '{updated_schedule.title}' selesai dicatat dan status jadwal diubah menjadi Selesai.",
                )
            else:
                messages.success(
                    request,
                    f"Pemeliharaan '{updated_schedule.title}' selesai dicatat. "
                    f"Jadwal berikutnya otomatis diatur ke {updated_schedule.next_due_date.strftime('%d %b %Y')}.",
                )
            return redirect("maintenance:schedule_list")
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))

    return render(
        request,
        "maintenance/schedule_execute.html",
        {"schedule": schedule, "form": form},
    )


# --- Maintenance Logs (FR-08) ---


@role_required(*STAFF_ROLES)
def log_list_view(request):
    """List MaintenanceLog history with asset, date range, search filters, and total cost."""
    q = (request.GET.get("q") or "").strip()
    asset_id = (request.GET.get("asset") or "").strip()
    date_from_raw = (request.GET.get("date_from") or "").strip()
    date_to_raw = (request.GET.get("date_to") or "").strip()

    date_from = _parse_iso_date(date_from_raw)
    date_to = _parse_iso_date(date_to_raw)

    qs = MaintenanceLog.objects.select_related(
        "asset",
        "asset__category",
        "schedule",
        "damage_report",
        "performed_by",
    ).order_by("-performed_date", "-id")

    if q:
        qs = qs.filter(
            Q(summary__icontains=q)
            | Q(asset__asset_code__icontains=q)
            | Q(asset__name__icontains=q)
            | Q(performed_by__full_name__icontains=q)
        )
    if asset_id.isdigit():
        qs = qs.filter(asset_id=int(asset_id))
    if date_from:
        qs = qs.filter(performed_date__gte=date_from)
    if date_to:
        qs = qs.filter(performed_date__lte=date_to)

    summary_agg = qs.aggregate(
        total_cost=Coalesce(Sum("cost"), Decimal("0.00")),
    )
    total_count = qs.count()
    page_obj = Paginator(qs, 15).get_page(request.GET.get("page"))

    return render(
        request,
        "maintenance/log_list.html",
        {
            "page_obj": page_obj,
            "assets": Asset.objects.order_by("asset_code").only("id", "asset_code", "name"),
            "total_cost": summary_agg["total_cost"],
            "total_count": total_count,
            "filters": {
                "q": q,
                "asset": asset_id,
                "date_from": date_from_raw,
                "date_to": date_to_raw,
            },
        },
    )
