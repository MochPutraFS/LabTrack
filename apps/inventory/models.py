from decimal import Decimal
from io import BytesIO

import qrcode
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import TimeStampedModel


class Category(TimeStampedModel):
    """Master category for laboratory assets."""

    code = models.CharField(max_length=10, unique=True, help_text="Kode kategori uppercase, misal: KOM, JAR, PRJ")
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    default_useful_life_years = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1)],
        help_text="Rekomendasi umur ekonomis standar (tahun)",
    )

    class Meta:
        verbose_name = "Kategori Aset"
        verbose_name_plural = "Kategori Aset"
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(default_useful_life_years__gte=1),
                name="category_default_useful_life_gte_1",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Location(TimeStampedModel):
    """Laboratory room or storage location."""

    code = models.CharField(max_length=20, unique=True, help_text="Kode ruangan, misal: LAB-RPL")
    name = models.CharField(max_length=120)
    building = models.CharField(max_length=100, blank=True, default="")
    floor = models.CharField(max_length=20, blank=True, default="")
    pic_name = models.CharField(max_length=120, blank=True, default="")
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Lokasi Laboratorium"
        verbose_name_plural = "Lokasi Laboratorium"
        ordering = ["code"]

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Asset(TimeStampedModel):
    """Master record for an individual laboratory asset."""

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Tersedia"
        BORROWED = "BORROWED", "Dipinjam"
        MAINTENANCE = "MAINTENANCE", "Pemeliharaan"
        DAMAGED = "DAMAGED", "Rusak"
        RETIRED = "RETIRED", "Dihapusbukukan"

    class Condition(models.TextChoices):
        GOOD = "GOOD", "Baik"
        MINOR_DAMAGE = "MINOR_DAMAGE", "Rusak Ringan"
        MAJOR_DAMAGE = "MAJOR_DAMAGE", "Rusak Berat"

    asset_code = models.CharField(
        max_length=40,
        unique=True,
        db_index=True,
        help_text="Format LAB-<KAT>-<YYYY>-<NNNN>",
    )
    name = models.CharField(max_length=150, db_index=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="assets",
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="assets",
    )
    brand = models.CharField(max_length=100, blank=True, default="")
    model_name = models.CharField(max_length=100, blank=True, default="")
    serial_number = models.CharField(max_length=100, blank=True, default="", db_index=True)
    acquisition_date = models.DateField()
    acquisition_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    useful_life_years = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1)],
    )
    salvage_value = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
        db_index=True,
    )
    condition = models.CharField(
        max_length=20,
        choices=Condition.choices,
        default=Condition.GOOD,
        db_index=True,
    )
    qr_code_image = models.ImageField(
        upload_to="qrcodes/",
        max_length=255,
        blank=True,
    )
    photo = models.ImageField(
        upload_to="assets/",
        max_length=255,
        blank=True,
    )
    specifications = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    retirement_reason = models.TextField(blank=True, default="")
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Aset Laboratorium"
        verbose_name_plural = "Aset Laboratorium"
        ordering = ["asset_code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(acquisition_cost__gte=Decimal("0.00")),
                name="asset_acquisition_cost_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(useful_life_years__gte=1),
                name="asset_useful_life_years_gte_1",
            ),
            models.CheckConstraint(
                condition=Q(salvage_value__gte=Decimal("0.00")),
                name="asset_salvage_value_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(salvage_value__lte=F("acquisition_cost")),
                name="asset_salvage_lte_acquisition_cost",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.salvage_value is not None
            and self.acquisition_cost is not None
            and self.salvage_value > self.acquisition_cost
        ):
            raise ValidationError(
                {"salvage_value": "Nilai residu tidak boleh lebih besar dari harga perolehan."}
            )

    def __str__(self) -> str:
        return f"{self.asset_code} — {self.name}"

    @property
    def is_borrowable(self) -> bool:
        """Return True if asset is active, available, and not majorly damaged."""
        return (
            self.is_active
            and self.status == self.Status.AVAILABLE
            and self.condition != self.Condition.MAJOR_DAMAGE
        )

    def get_qr_payload(self, base_url: str | None = None) -> str:
        """Build the public scan URL encoded inside the asset's QR code."""
        resolved_base = (
            base_url or getattr(settings, "SITE_BASE_URL", "http://localhost:8000")
        ).rstrip("/")
        return f"{resolved_base}/scan/{self.asset_code}/"

    def generate_qr_code(
        self,
        base_url: str | None = None,
        save: bool = True,
        force: bool = False,
    ) -> str:
        """Generate and store the QR code PNG at media/qrcodes/<asset_code>.png."""
        if not force and self.qr_code_image and self.qr_code_image.storage.exists(self.qr_code_image.name):
            return self.qr_code_image.name

        payload = self.get_qr_payload(base_url=base_url)
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        filename = f"{self.asset_code}.png"
        target_name = f"qrcodes/{filename}"

        # Replace existing file cleanly to avoid random suffixes on regeneration
        if self.qr_code_image.storage.exists(target_name):
            self.qr_code_image.storage.delete(target_name)

        self.qr_code_image.save(filename, ContentFile(buffer.getvalue()), save=save)
        return self.qr_code_image.name


class AssetLocationHistory(TimeStampedModel):
    """Audit trail for asset placement and room-to-room relocations."""

    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name="location_histories",
    )
    from_location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="outgoing_histories",
    )
    to_location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="incoming_histories",
    )
    moved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_moves",
    )
    moved_at = models.DateTimeField(default=timezone.now)
    reason = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Riwayat Lokasi Aset"
        verbose_name_plural = "Riwayat Lokasi Aset"
        ordering = ["-moved_at"]

    def __str__(self) -> str:
        origin = self.from_location.code if self.from_location else "AWAL"
        return f"{self.asset.asset_code}: {origin} -> {self.to_location.code}"
