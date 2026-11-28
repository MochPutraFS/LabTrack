"""Business logic service layer for Hybrid Loans (Online & Walk-In) and Returns."""

from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.services import log_audit
from apps.inventory.models import Asset
from apps.loans.models import Loan, LoanItem
from apps.maintenance.models import DamageReport

# Allowed Loan state transitions (docs/02-Business-Flowchart.md Tabel 3)
ALLOWED_LOAN_TRANSITIONS: dict[str, set[str]] = {
    Loan.Status.PENDING: {
        Loan.Status.APPROVED,
        Loan.Status.ACTIVE,
        Loan.Status.REJECTED,
        Loan.Status.CANCELLED,
    },
    Loan.Status.APPROVED: {
        Loan.Status.ACTIVE,
        Loan.Status.CANCELLED,
    },
    Loan.Status.ACTIVE: {
        Loan.Status.OVERDUE,
        Loan.Status.RETURNED,
    },
    Loan.Status.OVERDUE: {
        Loan.Status.RETURNED,
    },
    Loan.Status.REJECTED: set(),
    Loan.Status.CANCELLED: set(),
    Loan.Status.RETURNED: set(),
}


def generate_loan_number(ref_date: date | None = None) -> str:
    """Generate sequential loan number: LOAN-YYYYMMDD-NNNN."""
    target = ref_date or timezone.localdate()
    prefix = f"LOAN-{target.strftime('%Y%m%d')}-"
    existing = Loan.objects.filter(loan_number__startswith=prefix).values_list("loan_number", flat=True)
    max_seq = 0
    for number in existing:
        suffix = number[len(prefix) :]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    return f"{prefix}{max_seq + 1:04d}"


def _generate_damage_report_number(ref_date: date | None = None) -> str:
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


def _assert_loan_transition(loan: Loan, target_status: str) -> None:
    allowed = ALLOWED_LOAN_TRANSITIONS.get(loan.status, set())
    if target_status not in allowed:
        raise ValidationError(
            f"Transisi status pinjaman dari '{loan.get_status_display()}' ke "
            f"'{Loan.Status(target_status).label}' tidak diizinkan."
        )


def _validate_dates_and_purpose(borrow_date: date, due_date: date, purpose: str) -> str:
    if not borrow_date or not due_date:
        raise ValidationError("Tanggal pinjam dan tanggal jatuh tempo wajib diisi.")
    if due_date < borrow_date:
        raise ValidationError("Tanggal jatuh tempo tidak boleh lebih awal dari tanggal pinjam.")
    clean_purpose = (purpose or "").strip()
    if not clean_purpose:
        raise ValidationError("Tujuan peminjaman wajib diisi.")
    return clean_purpose


def _lock_and_validate_assets(asset_ids: list[int]) -> list[Asset]:
    """Row-lock selected assets in deterministic ID order and verify borrowability."""
    unique_ids = sorted({int(aid) for aid in asset_ids if str(aid).isdigit()})
    if not unique_ids:
        raise ValidationError("Pilih minimal satu aset yang akan dipinjam.")

    assets = list(Asset.objects.select_for_update().filter(pk__in=unique_ids).order_by("id"))
    if len(assets) != len(unique_ids):
        raise ValidationError("Sebagian aset yang dipilih tidak ditemukan.")

    unavailable = [
        f"{a.asset_code} ({a.get_status_display()}, {a.get_condition_display()})"
        for a in assets
        if not a.is_borrowable
    ]
    if unavailable:
        raise ValidationError(
            "Aset berikut tidak tersedia untuk dipinjam: " + ", ".join(unavailable) + "."
        )
    return assets


def sync_overdue_loans(today: date | None = None) -> int:
    """Mark ACTIVE loans past due_date as OVERDUE and return updated row count."""
    ref_date = today or timezone.localdate()
    return Loan.objects.filter(
        status=Loan.Status.ACTIVE,
        due_date__lt=ref_date,
    ).update(status=Loan.Status.OVERDUE, updated_at=timezone.now())


@transaction.atomic
def create_online_loan(
    borrower_user,
    asset_ids: list[int],
    borrow_date: date,
    due_date: date,
    purpose: str,
    notes: str = "",
) -> Loan:
    """Create a PENDING ONLINE loan request after locking and validating assets."""
    if borrower_user is None or not borrower_user.is_authenticated:
        raise ValidationError("Peminjam harus login untuk mengajukan peminjaman online.")

    clean_purpose = _validate_dates_and_purpose(borrow_date, due_date, purpose)
    assets = _lock_and_validate_assets(asset_ids)

    loan = Loan.objects.create(
        loan_number=generate_loan_number(),
        loan_channel=Loan.Channel.ONLINE,
        borrower_user=borrower_user,
        borrower_name=(borrower_user.full_name or borrower_user.username).strip(),
        borrower_identifier=(borrower_user.identifier_number or borrower_user.username).strip(),
        borrower_contact=(borrower_user.phone_number or borrower_user.email).strip(),
        purpose=clean_purpose,
        borrow_date=borrow_date,
        due_date=due_date,
        status=Loan.Status.PENDING,
        notes=(notes or "").strip(),
    )

    LoanItem.objects.bulk_create(
        [
            LoanItem(loan=loan, asset=asset, condition_on_checkout=asset.condition)
            for asset in assets
        ]
    )

    log_audit(
        actor=borrower_user,
        action="LOAN_ONLINE_REQUESTED",
        entity_type="Loan",
        entity_id=loan.pk,
        metadata={
            "loan_number": loan.loan_number,
            "channel": loan.loan_channel,
            "asset_codes": [a.asset_code for a in assets],
            "borrow_date": str(borrow_date),
            "due_date": str(due_date),
        },
    )
    return loan


@transaction.atomic
def approve_loan(loan: Loan, staff_user, handover_now: bool = False) -> Loan:
    """Approve a PENDING loan (to APPROVED, or directly to ACTIVE when handover_now=True)."""
    if not getattr(staff_user, "is_staff_lab", False):
        raise ValidationError("Hanya Admin atau Laboran yang dapat menyetujui peminjaman.")

    locked_loan = Loan.objects.select_for_update().get(pk=loan.pk)
    target_status = Loan.Status.ACTIVE if handover_now else Loan.Status.APPROVED
    _assert_loan_transition(locked_loan, target_status)

    items = list(locked_loan.items.select_related("asset").order_by("asset_id"))
    assets = _lock_and_validate_assets([item.asset_id for item in items])
    asset_map = {a.pk: a for a in assets}

    now = timezone.now()
    locked_loan.status = target_status
    locked_loan.processed_by = staff_user
    update_fields = ["status", "processed_by", "updated_at"]

    if handover_now:
        locked_loan.handed_over_at = now
        update_fields.append("handed_over_at")
        for item in items:
            asset = asset_map[item.asset_id]
            asset.status = Asset.Status.BORROWED
            asset.save(update_fields=["status", "updated_at"])
            if item.condition_on_checkout != asset.condition:
                item.condition_on_checkout = asset.condition
                item.save(update_fields=["condition_on_checkout", "updated_at"])

    locked_loan.save(update_fields=update_fields)

    log_audit(
        actor=staff_user,
        action="LOAN_APPROVED_AND_HANDED_OVER" if handover_now else "LOAN_APPROVED",
        entity_type="Loan",
        entity_id=locked_loan.pk,
        metadata={
            "loan_number": locked_loan.loan_number,
            "status": locked_loan.status,
            "asset_codes": [a.asset_code for a in assets],
        },
    )
    return locked_loan


@transaction.atomic
def reject_loan(loan: Loan, staff_user, reason: str) -> Loan:
    """Reject a PENDING loan with a mandatory rejection reason."""
    if not getattr(staff_user, "is_staff_lab", False):
        raise ValidationError("Hanya Admin atau Laboran yang dapat menolak peminjaman.")

    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise ValidationError("Alasan penolakan wajib diisi.")

    locked_loan = Loan.objects.select_for_update().get(pk=loan.pk)
    _assert_loan_transition(locked_loan, Loan.Status.REJECTED)

    locked_loan.status = Loan.Status.REJECTED
    locked_loan.rejection_reason = clean_reason
    locked_loan.processed_by = staff_user
    locked_loan.save(update_fields=["status", "rejection_reason", "processed_by", "updated_at"])

    log_audit(
        actor=staff_user,
        action="LOAN_REJECTED",
        entity_type="Loan",
        entity_id=locked_loan.pk,
        metadata={"loan_number": locked_loan.loan_number, "reason": clean_reason},
    )
    return locked_loan


@transaction.atomic
def handover_loan(loan: Loan, staff_user) -> Loan:
    """Hand over an APPROVED loan (APPROVED -> ACTIVE) and mark all assets BORROWED."""
    if not getattr(staff_user, "is_staff_lab", False):
        raise ValidationError("Hanya Admin atau Laboran yang dapat melakukan serah terima aset.")

    locked_loan = Loan.objects.select_for_update().get(pk=loan.pk)
    if locked_loan.status != Loan.Status.APPROVED:
        raise ValidationError(
            f"Serah terima hanya dapat dilakukan untuk pinjaman berstatus 'Disetujui' "
            f"(status saat ini: '{locked_loan.get_status_display()}')."
        )
    _assert_loan_transition(locked_loan, Loan.Status.ACTIVE)

    items = list(locked_loan.items.select_related("asset").order_by("asset_id"))
    assets = _lock_and_validate_assets([item.asset_id for item in items])
    asset_map = {a.pk: a for a in assets}

    for item in items:
        asset = asset_map[item.asset_id]
        asset.status = Asset.Status.BORROWED
        asset.save(update_fields=["status", "updated_at"])
        if item.condition_on_checkout != asset.condition:
            item.condition_on_checkout = asset.condition
            item.save(update_fields=["condition_on_checkout", "updated_at"])

    locked_loan.status = Loan.Status.ACTIVE
    locked_loan.handed_over_at = timezone.now()
    locked_loan.processed_by = locked_loan.processed_by or staff_user
    locked_loan.save(update_fields=["status", "handed_over_at", "processed_by", "updated_at"])

    log_audit(
        actor=staff_user,
        action="LOAN_HANDED_OVER",
        entity_type="Loan",
        entity_id=locked_loan.pk,
        metadata={
            "loan_number": locked_loan.loan_number,
            "asset_codes": [a.asset_code for a in assets],
        },
    )
    return locked_loan


@transaction.atomic
def cancel_loan(loan: Loan, actor) -> Loan:
    """Cancel a PENDING (owner/staff) or APPROVED (staff only) loan."""
    locked_loan = Loan.objects.select_for_update().get(pk=loan.pk)
    _assert_loan_transition(locked_loan, Loan.Status.CANCELLED)

    is_staff = getattr(actor, "is_staff_lab", False)
    if not is_staff:
        if locked_loan.borrower_user_id != getattr(actor, "pk", None):
            raise ValidationError("Anda tidak berhak membatalkan peminjaman milik pengguna lain.")
        if locked_loan.status != Loan.Status.PENDING:
            raise ValidationError("Peminjam hanya dapat membatalkan pengajuan saat status masih Menunggu Persetujuan.")

    previous_status = locked_loan.status
    locked_loan.status = Loan.Status.CANCELLED
    locked_loan.save(update_fields=["status", "updated_at"])

    log_audit(
        actor=actor,
        action="LOAN_CANCELLED",
        entity_type="Loan",
        entity_id=locked_loan.pk,
        metadata={"loan_number": locked_loan.loan_number, "previous_status": previous_status},
    )
    return locked_loan


@transaction.atomic
def create_walk_in_loan(
    staff_user,
    asset_ids: list[int],
    borrow_date: date,
    due_date: date,
    purpose: str,
    borrower_user=None,
    borrower_name: str = "",
    borrower_identifier: str = "",
    borrower_contact: str = "",
    notes: str = "",
) -> Loan:
    """Record a WALK_IN loan directly as ACTIVE and mark all selected assets BORROWED."""
    if not getattr(staff_user, "is_staff_lab", False):
        raise ValidationError("Hanya Admin atau Laboran yang dapat mencatat peminjaman Walk-In.")

    clean_purpose = _validate_dates_and_purpose(borrow_date, due_date, purpose)

    resolved_name = (borrower_name or "").strip()
    resolved_identifier = (borrower_identifier or "").strip()
    resolved_contact = (borrower_contact or "").strip()

    if borrower_user is not None:
        resolved_name = resolved_name or (borrower_user.full_name or borrower_user.username).strip()
        resolved_identifier = resolved_identifier or (borrower_user.identifier_number or borrower_user.username).strip()
        resolved_contact = resolved_contact or (borrower_user.phone_number or borrower_user.email).strip()

    if not resolved_name or not resolved_identifier or not resolved_contact:
        raise ValidationError(
            "Identitas peminjam (Nama Lengkap, NIM/NIP, dan No. Kontak) wajib diisi."
        )

    assets = _lock_and_validate_assets(asset_ids)

    now = timezone.now()
    loan = Loan.objects.create(
        loan_number=generate_loan_number(),
        loan_channel=Loan.Channel.WALK_IN,
        borrower_user=borrower_user,
        borrower_name=resolved_name,
        borrower_identifier=resolved_identifier,
        borrower_contact=resolved_contact,
        purpose=clean_purpose,
        borrow_date=borrow_date,
        due_date=due_date,
        handed_over_at=now,
        status=Loan.Status.ACTIVE,
        processed_by=staff_user,
        notes=(notes or "").strip(),
    )

    LoanItem.objects.bulk_create(
        [
            LoanItem(loan=loan, asset=asset, condition_on_checkout=asset.condition)
            for asset in assets
        ]
    )

    for asset in assets:
        asset.status = Asset.Status.BORROWED
        asset.save(update_fields=["status", "updated_at"])

    log_audit(
        actor=staff_user,
        action="LOAN_WALK_IN_CREATED",
        entity_type="Loan",
        entity_id=loan.pk,
        metadata={
            "loan_number": loan.loan_number,
            "channel": loan.loan_channel,
            "borrower_name": resolved_name,
            "borrower_identifier": resolved_identifier,
            "linked_user_id": borrower_user.pk if borrower_user else None,
            "asset_codes": [a.asset_code for a in assets],
        },
    )
    return loan


@transaction.atomic
def process_loan_return(
    loan: Loan,
    staff_user,
    item_inspections: dict[int, dict[str, str]],
) -> dict:
    """Inspect and return all items in an ACTIVE/OVERDUE loan, syncing asset statuses.

    item_inspections maps LoanItem.pk -> {"condition": Asset.Condition, "notes": str}.
    """
    if not getattr(staff_user, "is_staff_lab", False):
        raise ValidationError("Hanya Admin atau Laboran yang dapat memproses pengembalian aset.")

    locked_loan = Loan.objects.select_for_update().get(pk=loan.pk)
    _assert_loan_transition(locked_loan, Loan.Status.RETURNED)

    items = list(locked_loan.items.select_related("asset").order_by("asset_id"))
    if not items:
        raise ValidationError("Transaksi peminjaman tidak memiliki item aset.")

    asset_ids = [item.asset_id for item in items]
    assets = {
        a.pk: a
        for a in Asset.objects.select_for_update().filter(pk__in=asset_ids).order_by("id")
    }

    valid_conditions = set(Asset.Condition.values)
    for item in items:
        entry = item_inspections.get(item.pk)
        if not entry or entry.get("condition") not in valid_conditions:
            raise ValidationError(
                f"Kondisi pengembalian untuk aset {item.asset.asset_code} wajib diisi dengan nilai yang valid."
            )

    created_damage_reports: list[DamageReport] = []
    for item in items:
        entry = item_inspections[item.pk]
        returned_condition = entry["condition"]
        return_notes = (entry.get("notes") or "").strip()

        item.condition_on_return = returned_condition
        item.return_notes = return_notes
        item.save(update_fields=["condition_on_return", "return_notes", "updated_at"])

        asset = assets[item.asset_id]
        asset.condition = returned_condition

        if returned_condition == Asset.Condition.MAJOR_DAMAGE:
            asset.status = Asset.Status.DAMAGED
            asset.save(update_fields=["status", "condition", "updated_at"])

            desc_detail = return_notes or "Aset dikembalikan dalam kondisi Rusak Berat."
            report = DamageReport.objects.create(
                report_number=_generate_damage_report_number(),
                asset=asset,
                reported_by=staff_user,
                handled_by=staff_user,
                severity=DamageReport.Severity.HIGH,
                status=DamageReport.Status.VERIFIED,
                description=(
                    f"[Otomatis dari Pengembalian {locked_loan.loan_number} — "
                    f"Peminjam: {locked_loan.borrower_name}] {desc_detail}"
                ),
            )
            created_damage_reports.append(report)
            log_audit(
                actor=staff_user,
                action="DAMAGE_REPORT_AUTO_CREATED",
                entity_type="DamageReport",
                entity_id=report.pk,
                metadata={
                    "report_number": report.report_number,
                    "asset_code": asset.asset_code,
                    "loan_number": locked_loan.loan_number,
                },
            )
        else:
            asset.status = Asset.Status.AVAILABLE
            asset.save(update_fields=["status", "condition", "updated_at"])

    locked_loan.status = Loan.Status.RETURNED
    locked_loan.returned_at = timezone.now()
    locked_loan.received_by = staff_user
    locked_loan.save(update_fields=["status", "returned_at", "received_by", "updated_at"])

    log_audit(
        actor=staff_user,
        action="LOAN_RETURNED",
        entity_type="Loan",
        entity_id=locked_loan.pk,
        metadata={
            "loan_number": locked_loan.loan_number,
            "received_by": staff_user.username,
            "items": [
                {
                    "asset_code": assets[i.asset_id].asset_code,
                    "condition_on_return": i.condition_on_return,
                }
                for i in items
            ],
            "auto_damage_reports": [r.report_number for r in created_damage_reports],
        },
    )
    return {
        "loan": locked_loan,
        "created_damage_reports": created_damage_reports,
    }
