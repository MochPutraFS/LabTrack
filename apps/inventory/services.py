"""Business logic service layer for LabTrack inventory management."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.services import log_audit
from apps.inventory.models import Asset, AssetLocationHistory, Category, Location


def generate_asset_code(category: Category, year: int | None = None) -> str:
    """Generate the next sequential asset code: LAB-<KAT>-<YYYY>-<NNNN>."""
    target_year = year or timezone.localdate().year
    prefix = f"LAB-{category.code.upper()}-{target_year}-"
    existing_codes = Asset.objects.filter(asset_code__startswith=prefix).values_list(
        "asset_code", flat=True
    )
    max_seq = 0
    for code in existing_codes:
        suffix = code[len(prefix) :]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    return f"{prefix}{max_seq + 1:04d}"


def ensure_asset_qr(asset: Asset, base_url: str | None = None) -> str:
    """Ensure the asset's QR PNG exists on disk, regenerating safely if missing."""
    return asset.generate_qr_code(base_url=base_url, save=True, force=False)


def calculate_asset_book_value(asset: Asset, as_of: date | None = None) -> dict[str, Decimal]:
    """Compute Straight-Line depreciation summary for a single asset using Decimal."""
    ref_date = as_of or timezone.localdate()
    cost = asset.acquisition_cost
    salvage = asset.salvage_value
    life = Decimal(asset.useful_life_years)

    annual = ((cost - salvage) / life).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    days_elapsed = max(0, (ref_date - asset.acquisition_date).days)
    age_years = Decimal(days_elapsed) / Decimal("365.25")
    capped_years = min(age_years, life)
    accumulated = (annual * capped_years).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    max_depreciable = cost - salvage
    if accumulated > max_depreciable:
        accumulated = max_depreciable
    book_value = max(salvage, cost - accumulated).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "annual_depreciation": annual,
        "accumulated_depreciation": accumulated,
        "book_value": book_value,
        "age_years": age_years.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
    }


@transaction.atomic
def create_asset(asset: Asset, actor, base_url: str | None = None) -> Asset:
    """Persist a new Asset, generate its QR PNG, record initial location, and log audit."""
    if not asset.asset_code:
        year = asset.acquisition_date.year if asset.acquisition_date else timezone.localdate().year
        asset.asset_code = generate_asset_code(asset.category, year=year)
    else:
        asset.asset_code = asset.asset_code.strip().upper()

    asset.full_clean()
    asset.save()
    ensure_asset_qr(asset, base_url=base_url)

    AssetLocationHistory.objects.create(
        asset=asset,
        from_location=None,
        to_location=asset.location,
        moved_by=actor,
        reason="Penempatan awal saat registrasi aset",
    )
    log_audit(
        actor=actor,
        action="ASSET_CREATED",
        entity_type="Asset",
        entity_id=asset.pk,
        metadata={
            "asset_code": asset.asset_code,
            "name": asset.name,
            "category": asset.category.code,
            "location": asset.location.code,
        },
    )
    return asset


@transaction.atomic
def update_asset(asset: Asset, actor, previous_location: Location | None = None) -> Asset:
    """Update an existing Asset; if location changed, also record location history."""
    asset.full_clean()
    asset.save()

    if previous_location and previous_location.pk != asset.location_id:
        AssetLocationHistory.objects.create(
            asset=asset,
            from_location=previous_location,
            to_location=asset.location,
            moved_by=actor,
            reason="Perubahan lokasi melalui edit data aset",
        )

    log_audit(
        actor=actor,
        action="ASSET_UPDATED",
        entity_type="Asset",
        entity_id=asset.pk,
        metadata={
            "asset_code": asset.asset_code,
            "status": asset.status,
            "condition": asset.condition,
            "location": asset.location.code,
        },
    )
    return asset


@transaction.atomic
def move_asset_location(
    asset: Asset,
    to_location: Location,
    actor,
    reason: str = "",
) -> AssetLocationHistory:
    """Relocate an asset to another room and record both AssetLocationHistory and AuditLog."""
    if asset.status == Asset.Status.RETIRED or not asset.is_active:
        raise ValidationError("Aset yang sudah dihapusbukukan tidak dapat dimutasi.")
    if asset.location_id == to_location.pk:
        raise ValidationError("Lokasi tujuan harus berbeda dengan lokasi saat ini.")

    from_location = asset.location
    asset.location = to_location
    asset.save(update_fields=["location", "updated_at"])

    history = AssetLocationHistory.objects.create(
        asset=asset,
        from_location=from_location,
        to_location=to_location,
        moved_by=actor,
        reason=reason.strip() or "Mutasi lokasi aset",
    )
    log_audit(
        actor=actor,
        action="ASSET_LOCATION_MOVED",
        entity_type="Asset",
        entity_id=asset.pk,
        metadata={
            "asset_code": asset.asset_code,
            "from_location": from_location.code,
            "to_location": to_location.code,
            "reason": history.reason,
        },
    )
    return history


@transaction.atomic
def retire_asset(asset: Asset, actor, reason: str) -> Asset:
    """Soft-retire an asset (RETIRED + is_active=False) instead of hard deletion."""
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise ValidationError("Alasan penghapusbukuan wajib diisi.")
    if asset.status == Asset.Status.RETIRED:
        raise ValidationError("Aset ini sudah berstatus dihapusbukukan.")
    if asset.status == Asset.Status.BORROWED:
        raise ValidationError("Aset yang sedang dipinjam tidak dapat dihapusbukukan sebelum dikembalikan.")

    asset.status = Asset.Status.RETIRED
    asset.is_active = False
    asset.retirement_reason = clean_reason
    asset.retired_at = timezone.now()
    asset.save(update_fields=["status", "is_active", "retirement_reason", "retired_at", "updated_at"])

    log_audit(
        actor=actor,
        action="ASSET_RETIRED",
        entity_type="Asset",
        entity_id=asset.pk,
        metadata={"asset_code": asset.asset_code, "reason": clean_reason},
    )
    return asset


@transaction.atomic
def delete_category(category: Category, actor) -> None:
    """Delete a category only when no assets reference it (FR-03.2)."""
    if category.assets.exists():
        raise ValidationError(
            f"Kategori '{category.name}' tidak dapat dihapus karena masih digunakan oleh {category.assets.count()} aset."
        )
    cat_id, cat_code, cat_name = category.pk, category.code, category.name
    category.delete()
    log_audit(
        actor=actor,
        action="CATEGORY_DELETED",
        entity_type="Category",
        entity_id=cat_id,
        metadata={"code": cat_code, "name": cat_name},
    )


@transaction.atomic
def delete_location(location: Location, actor) -> None:
    """Delete a location only when no assets or location histories reference it."""
    if location.assets.exists():
        raise ValidationError(
            f"Lokasi '{location.name}' tidak dapat dihapus karena masih menampung {location.assets.count()} aset."
        )
    if location.incoming_histories.exists() or location.outgoing_histories.exists():
        raise ValidationError(
            f"Lokasi '{location.name}' tidak dapat dihapus karena tercatat dalam riwayat mutasi aset."
        )
    loc_id, loc_code, loc_name = location.pk, location.code, location.name
    location.delete()
    log_audit(
        actor=actor,
        action="LOCATION_DELETED",
        entity_type="Location",
        entity_id=loc_id,
        metadata={"code": loc_code, "name": loc_name},
    )
