"""Business logic service layer for Damage Reports, Maintenance Schedules, and Logs."""

import calendar
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.services import log_audit
from apps.inventory.models import Asset
from apps.maintenance.models import DamageReport, MaintenanceLog, MaintenanceSchedule

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2 MB (NFR-02)

# Allowed DamageReport state transitions (docs/02-Business-Flowchart.md 2.3)
ALLOWED_DAMAGE_TRANSITIONS: dict[str, set[str]] = {
    DamageReport.Status.REPORTED: {
        DamageReport.Status.VERIFIED,
    },
    DamageReport.Status.VERIFIED: {
        DamageReport.Status.IN_REPAIR,
        DamageReport.Status.UNREPAIRABLE,
    },
    DamageReport.Status.IN_REPAIR: {
        DamageReport.Status.RESOLVED,
        DamageReport.Status.UNREPAIRABLE,
    },
    DamageReport.Status.RESOLVED: set(),
    DamageReport.Status.UNREPAIRABLE: set(),
}

FREQUENCY_MONTHS: dict[str, int] = {
    MaintenanceSchedule.Frequency.MONTHLY: 1,
    MaintenanceSchedule.Frequency.QUARTERLY: 3,
    MaintenanceSchedule.Frequency.SEMI_ANNUAL: 6,
    MaintenanceSchedule.Frequency.ANNUAL: 12,
}


def add_months(source_date: date, months: int) -> date:
    """Add calendar months to a date, clamping day to the target month's last day."""
    total_months = (source_date.year * 12 + (source_date.month - 1)) + months
    year, zero_based_month = divmod(total_months, 12)
    month = zero_based_month + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(source_date.day, last_day))


def generate_damage_report_number(ref_date: date | None = None) -> str:
    """Generate sequential damage report number: DMG-YYYYMMDD-NNNN."""
    target = ref_date or timezone.localdate()
    prefix = f"DMG-{target.strftime('%Y%m%d')}-"
    existing = DamageReport.objects.filter(report_number__startswith=prefix).values_list(
        "report_number", flat=True
    )
    max_seq = 0
    for number in existing:
        suffix = number[len(prefix) :]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    return f"{prefix}{max_seq + 1:04d}"


def validate_damage_photo(photo) -> None:
    """Validate uploaded damage evidence image format (JPG/PNG/WebP) and size (<= 2 MB)."""
    if not photo:
        return
    filename = getattr(photo, "name", "") or ""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError("Format foto bukti harus JPG, PNG, atau WebP.")
    size = getattr(photo, "size", None)
    if size is not None and size > MAX_IMAGE_BYTES:
        raise ValidationError("Ukuran foto bukti maksimal 2 MB.")


def get_allowed_damage_next_statuses(current_status: str) -> list[tuple[str, str]]:
    """Return ordered (value, label) choices allowed from the given DamageReport status."""
    allowed = ALLOWED_DAMAGE_TRANSITIONS.get(current_status, set())
    return [(val, label) for val, label in DamageReport.Status.choices if val in allowed]


def _assert_damage_transition(report: DamageReport, target_status: str) -> None:
    if target_status not in DamageReport.Status.values:
        raise ValidationError("Status laporan kerusakan tujuan tidak valid.")
    allowed = ALLOWED_DAMAGE_TRANSITIONS.get(report.status, set())
    if target_status not in allowed:
        raise ValidationError(
            f"Transisi status laporan dari '{report.get_status_display()}' ke "
            f"'{DamageReport.Status(target_status).label}' tidak diizinkan."
        )


def _parse_non_negative_decimal(value, field_label: str = "Biaya") -> Decimal:
    """Safely coerce a numeric/Decimal/string input into a non-negative 2-decimal Decimal."""
    if value is None or value == "":
        return Decimal("0.00")
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError(f"{field_label} harus berupa angka yang valid.") from exc
    if amount < Decimal("0.00"):
        raise ValidationError(f"{field_label} tidak boleh bernilai negatif.")
    return amount


def sync_overdue_schedules(today: date | None = None) -> int:
    """Mark SCHEDULED maintenance schedules past next_due_date as OVERDUE."""
    ref_date = today or timezone.localdate()
    return MaintenanceSchedule.objects.filter(
        status=MaintenanceSchedule.Status.SCHEDULED,
        next_due_date__lt=ref_date,
    ).update(status=MaintenanceSchedule.Status.OVERDUE, updated_at=timezone.now())


@transaction.atomic
def create_damage_report(
    asset: Asset,
    reported_by,
    severity: str,
    description: str,
    photo=None,
) -> DamageReport:
    """Create a new REPORTED DamageReport with DMG-YYYYMMDD-NNNN number and photo validation."""
    if reported_by is None or not getattr(reported_by, "is_authenticated", False):
        raise ValidationError("Pengguna harus login untuk membuat laporan kerusakan.")
    if asset is None:
        raise ValidationError("Aset yang dilaporkan wajib dipilih.")
    if asset.status == Asset.Status.RETIRED or not asset.is_active:
        raise ValidationError("Aset yang sudah dihapusbukukan (RETIRED) tidak dapat dilaporkan kerusakannya.")
    if severity not in DamageReport.Severity.values:
        raise ValidationError("Tingkat keparahan kerusakan tidak valid.")

    clean_description = (description or "").strip()
    if not clean_description:
        raise ValidationError("Deskripsi gejala kerusakan wajib diisi.")

    validate_damage_photo(photo)

    report = DamageReport(
        report_number=generate_damage_report_number(),
        asset=asset,
        reported_by=reported_by,
        severity=severity,
        description=clean_description,
        status=DamageReport.Status.REPORTED,
    )
    if photo:
        report.photo = photo
    report.save()

    log_audit(
        actor=reported_by,
        action="DAMAGE_REPORT_CREATED",
        entity_type="DamageReport",
        entity_id=report.pk,
        metadata={
            "report_number": report.report_number,
            "asset_code": asset.asset_code,
            "severity": severity,
            "has_photo": bool(report.photo),
        },
    )
    return report


@transaction.atomic
def update_damage_report_status(
    report: DamageReport,
    staff_user,
    new_status: str,
    resolution_notes: str = "",
    create_maintenance_log: bool = False,
    repair_cost: Decimal | str | int | None = None,
    repair_summary: str = "",
    performed_date: date | None = None,
) -> dict:
    """Advance a DamageReport along the state machine and sync Asset status/condition."""
    if not getattr(staff_user, "is_staff_lab", False):
        raise ValidationError("Hanya Admin atau Laboran yang dapat memperbarui status laporan kerusakan.")

    locked_report = (
        DamageReport.objects.select_for_update()
        .select_related("asset")
        .get(pk=report.pk)
    )
    locked_asset = Asset.objects.select_for_update().get(pk=locked_report.asset_id)

    _assert_damage_transition(locked_report, new_status)

    if locked_asset.status == Asset.Status.RETIRED:
        raise ValidationError("Status aset tidak dapat diubah karena aset sudah dihapusbukukan (RETIRED).")

    previous_status = locked_report.status
    clean_notes = (resolution_notes or "").strip()
    created_log: MaintenanceLog | None = None

    if new_status == DamageReport.Status.IN_REPAIR:
        if locked_asset.status == Asset.Status.BORROWED:
            raise ValidationError(
                "Aset sedang dalam peminjaman aktif. Proses pengembalian aset terlebih dahulu sebelum memulai perbaikan."
            )
        locked_asset.status = Asset.Status.MAINTENANCE
        locked_asset.save(update_fields=["status", "updated_at"])

    elif new_status == DamageReport.Status.RESOLVED:
        locked_asset.status = Asset.Status.AVAILABLE
        locked_asset.condition = Asset.Condition.GOOD
        locked_asset.save(update_fields=["status", "condition", "updated_at"])
        locked_report.resolved_at = timezone.now()

        if create_maintenance_log:
            cost_decimal = _parse_non_negative_decimal(repair_cost, field_label="Biaya perbaikan")
            clean_summary = (
                (repair_summary or "").strip()
                or clean_notes
                or f"Perbaikan aset berdasarkan laporan {locked_report.report_number}."
            )
            created_log = MaintenanceLog.objects.create(
                asset=locked_asset,
                damage_report=locked_report,
                performed_by=staff_user,
                performed_date=performed_date or timezone.localdate(),
                summary=clean_summary,
                cost=cost_decimal,
                result_condition=Asset.Condition.GOOD,
            )

    elif new_status == DamageReport.Status.UNREPAIRABLE:
        if locked_asset.status == Asset.Status.BORROWED:
            raise ValidationError(
                "Aset sedang dalam peminjaman aktif. Proses pengembalian aset terlebih dahulu."
            )
        locked_asset.status = Asset.Status.DAMAGED
        locked_asset.condition = Asset.Condition.MAJOR_DAMAGE
        locked_asset.save(update_fields=["status", "condition", "updated_at"])
        locked_report.resolved_at = timezone.now()

    locked_report.status = new_status
    locked_report.handled_by = staff_user
    if clean_notes:
        locked_report.resolution_notes = clean_notes

    update_fields = ["status", "handled_by", "resolution_notes", "updated_at"]
    if locked_report.resolved_at is not None:
        update_fields.append("resolved_at")
    locked_report.save(update_fields=update_fields)

    log_audit(
        actor=staff_user,
        action=f"DAMAGE_REPORT_{new_status}",
        entity_type="DamageReport",
        entity_id=locked_report.pk,
        metadata={
            "report_number": locked_report.report_number,
            "asset_code": locked_asset.asset_code,
            "previous_status": previous_status,
            "new_status": new_status,
            "asset_status": locked_asset.status,
            "asset_condition": locked_asset.condition,
            "maintenance_log_id": created_log.pk if created_log else None,
        },
    )

    return {
        "report": locked_report,
        "asset": locked_asset,
        "maintenance_log": created_log,
    }


@transaction.atomic
def create_or_update_schedule(
    staff_user,
    asset: Asset,
    title: str,
    frequency: str,
    next_due_date: date,
    description: str = "",
    assigned_to=None,
    status: str | None = None,
    schedule: MaintenanceSchedule | None = None,
) -> MaintenanceSchedule:
    """Create or update a MaintenanceSchedule with validation and AuditLog."""
    if not getattr(staff_user, "is_staff_lab", False):
        raise ValidationError("Hanya Admin atau Laboran yang dapat mengelola jadwal pemeliharaan.")
    if asset is None:
        raise ValidationError("Aset target pemeliharaan wajib dipilih.")
    if asset.status == Asset.Status.RETIRED or not asset.is_active:
        raise ValidationError("Aset yang sudah dihapusbukukan (RETIRED) tidak dapat dijadwalkan pemeliharaan.")

    clean_title = (title or "").strip()
    if not clean_title:
        raise ValidationError("Judul kegiatan pemeliharaan wajib diisi.")
    if frequency not in MaintenanceSchedule.Frequency.values:
        raise ValidationError("Frekuensi jadwal pemeliharaan tidak valid.")
    if not next_due_date:
        raise ValidationError("Tanggal jatuh tempo pemeliharaan wajib diisi.")

    today = timezone.localdate()

    if schedule is None:
        initial_status = (
            status
            if status in MaintenanceSchedule.Status.values
            else (
                MaintenanceSchedule.Status.OVERDUE
                if next_due_date < today
                else MaintenanceSchedule.Status.SCHEDULED
            )
        )
        instance = MaintenanceSchedule.objects.create(
            asset=asset,
            title=clean_title,
            description=(description or "").strip(),
            frequency=frequency,
            next_due_date=next_due_date,
            assigned_to=assigned_to,
            status=initial_status,
        )
        log_audit(
            actor=staff_user,
            action="MAINTENANCE_SCHEDULE_CREATED",
            entity_type="MaintenanceSchedule",
            entity_id=instance.pk,
            metadata={
                "asset_code": asset.asset_code,
                "title": instance.title,
                "frequency": instance.frequency,
                "next_due_date": str(instance.next_due_date),
                "status": instance.status,
            },
        )
        return instance

    locked_schedule = MaintenanceSchedule.objects.select_for_update().get(pk=schedule.pk)
    locked_schedule.asset = asset
    locked_schedule.title = clean_title
    locked_schedule.description = (description or "").strip()
    locked_schedule.frequency = frequency
    locked_schedule.next_due_date = next_due_date
    locked_schedule.assigned_to = assigned_to

    if status in MaintenanceSchedule.Status.values:
        locked_schedule.status = status
    elif locked_schedule.status == MaintenanceSchedule.Status.OVERDUE and next_due_date >= today:
        locked_schedule.status = MaintenanceSchedule.Status.SCHEDULED

    locked_schedule.save()

    log_audit(
        actor=staff_user,
        action="MAINTENANCE_SCHEDULE_UPDATED",
        entity_type="MaintenanceSchedule",
        entity_id=locked_schedule.pk,
        metadata={
            "asset_code": asset.asset_code,
            "title": locked_schedule.title,
            "frequency": locked_schedule.frequency,
            "next_due_date": str(locked_schedule.next_due_date),
            "status": locked_schedule.status,
        },
    )
    return locked_schedule


@transaction.atomic
def execute_maintenance_schedule(
    schedule: MaintenanceSchedule,
    staff_user,
    performed_date: date,
    summary: str,
    cost: Decimal | str | int = Decimal("0.00"),
    result_condition: str = Asset.Condition.GOOD,
) -> dict:
    """Execute a MaintenanceSchedule: create MaintenanceLog, sync Asset, and roll recurring next_due_date."""
    if not getattr(staff_user, "is_staff_lab", False):
        raise ValidationError("Hanya Admin atau Laboran yang dapat mencatat eksekusi pemeliharaan.")

    locked_schedule = (
        MaintenanceSchedule.objects.select_for_update()
        .select_related("asset")
        .get(pk=schedule.pk)
    )
    locked_asset = Asset.objects.select_for_update().get(pk=locked_schedule.asset_id)

    if locked_schedule.status in (
        MaintenanceSchedule.Status.COMPLETED,
        MaintenanceSchedule.Status.CANCELLED,
    ):
        raise ValidationError(
            f"Jadwal dengan status '{locked_schedule.get_status_display()}' tidak dapat dieksekusi lagi."
        )
    if locked_asset.status == Asset.Status.RETIRED or not locked_asset.is_active:
        raise ValidationError("Aset yang sudah dihapusbukukan (RETIRED) tidak dapat dipelihara.")
    if not performed_date:
        raise ValidationError("Tanggal pelaksanaan pemeliharaan wajib diisi.")

    clean_summary = (summary or "").strip()
    if not clean_summary:
        raise ValidationError("Ringkasan tindakan pemeliharaan wajib diisi.")
    if result_condition not in Asset.Condition.values:
        raise ValidationError("Kondisi akhir aset tidak valid.")

    cost_decimal = _parse_non_negative_decimal(cost, field_label="Biaya pemeliharaan")

    maintenance_log = MaintenanceLog.objects.create(
        asset=locked_asset,
        schedule=locked_schedule,
        performed_by=staff_user,
        performed_date=performed_date,
        summary=clean_summary,
        cost=cost_decimal,
        result_condition=result_condition,
    )

    locked_asset.condition = result_condition
    if result_condition == Asset.Condition.MAJOR_DAMAGE:
        if locked_asset.status != Asset.Status.BORROWED:
            locked_asset.status = Asset.Status.DAMAGED
    elif locked_asset.status in (Asset.Status.MAINTENANCE, Asset.Status.DAMAGED):
        locked_asset.status = Asset.Status.AVAILABLE
    locked_asset.save(update_fields=["status", "condition", "updated_at"])

    previous_due = locked_schedule.next_due_date
    locked_schedule.last_completed_at = timezone.now()

    if locked_schedule.frequency == MaintenanceSchedule.Frequency.ONCE:
        locked_schedule.status = MaintenanceSchedule.Status.COMPLETED
    else:
        months = FREQUENCY_MONTHS[locked_schedule.frequency]
        base_date = max(performed_date, locked_schedule.next_due_date)
        locked_schedule.next_due_date = add_months(base_date, months)
        locked_schedule.status = MaintenanceSchedule.Status.SCHEDULED

    locked_schedule.save(update_fields=["next_due_date", "status", "last_completed_at", "updated_at"])

    log_audit(
        actor=staff_user,
        action="MAINTENANCE_SCHEDULE_EXECUTED",
        entity_type="MaintenanceSchedule",
        entity_id=locked_schedule.pk,
        metadata={
            "schedule_title": locked_schedule.title,
            "frequency": locked_schedule.frequency,
            "asset_code": locked_asset.asset_code,
            "maintenance_log_id": maintenance_log.pk,
            "performed_date": str(performed_date),
            "cost": str(cost_decimal),
            "result_condition": result_condition,
            "asset_status": locked_asset.status,
            "previous_due_date": str(previous_due),
            "next_due_date": str(locked_schedule.next_due_date),
            "schedule_status": locked_schedule.status,
        },
    )

    return {
        "schedule": locked_schedule,
        "log": maintenance_log,
        "asset": locked_asset,
    }
