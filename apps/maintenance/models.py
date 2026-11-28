from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.inventory.models import Asset


class DamageReport(TimeStampedModel):
    """Incident ticket for reporting and tracking laboratory asset damage."""

    class Severity(models.TextChoices):
        LOW = "LOW", "Rendah"
        MEDIUM = "MEDIUM", "Sedang"
        HIGH = "HIGH", "Tinggi"
        CRITICAL = "CRITICAL", "Kritis"

    class Status(models.TextChoices):
        REPORTED = "REPORTED", "Dilaporkan"
        VERIFIED = "VERIFIED", "Terverifikasi"
        IN_REPAIR = "IN_REPAIR", "Dalam Perbaikan"
        RESOLVED = "RESOLVED", "Selesai Diperbaiki"
        UNREPAIRABLE = "UNREPAIRABLE", "Tidak Dapat Diperbaiki"

    report_number = models.CharField(
        max_length=30,
        unique=True,
        help_text="Format DMG-YYYYMMDD-NNNN",
    )
    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name="damage_reports",
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reported_damages",
    )
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handled_damages",
    )
    severity = models.CharField(
        max_length=15,
        choices=Severity.choices,
    )
    description = models.TextField()
    photo = models.ImageField(
        upload_to="damage_reports/",
        max_length=255,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REPORTED,
        db_index=True,
    )
    resolution_notes = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Laporan Kerusakan"
        verbose_name_plural = "Laporan Kerusakan"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.report_number} — {self.asset.asset_code} ({self.get_status_display()})"


class MaintenanceSchedule(TimeStampedModel):
    """Preventive or periodic maintenance schedule for a laboratory asset."""

    class Frequency(models.TextChoices):
        ONCE = "ONCE", "Sekali"
        MONTHLY = "MONTHLY", "Bulanan"
        QUARTERLY = "QUARTERLY", "Triwulanan"
        SEMI_ANNUAL = "SEMI_ANNUAL", "Semesteran"
        ANNUAL = "ANNUAL", "Tahunan"

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Terjadwal"
        IN_PROGRESS = "IN_PROGRESS", "Sedang Dikerjakan"
        COMPLETED = "COMPLETED", "Selesai"
        OVERDUE = "OVERDUE", "Terlambat"
        CANCELLED = "CANCELLED", "Dibatalkan"

    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name="maintenance_schedules",
    )
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    frequency = models.CharField(
        max_length=20,
        choices=Frequency.choices,
    )
    next_due_date = models.DateField(db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_maintenance_schedules",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
        db_index=True,
    )
    last_completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Jadwal Pemeliharaan"
        verbose_name_plural = "Jadwal Pemeliharaan"
        ordering = ["next_due_date", "id"]

    def __str__(self) -> str:
        return f"{self.asset.asset_code} — {self.title} ({self.next_due_date})"

    @property
    def is_overdue(self) -> bool:
        if self.status == self.Status.OVERDUE:
            return True
        if self.status in (self.Status.SCHEDULED, self.Status.IN_PROGRESS):
            return self.next_due_date < timezone.localdate()
        return False

    @property
    def is_due_soon(self) -> bool:
        if self.status not in (self.Status.SCHEDULED, self.Status.IN_PROGRESS):
            return False
        days_until = (self.next_due_date - timezone.localdate()).days
        return 0 <= days_until <= 7


class MaintenanceLog(TimeStampedModel):
    """Historical record of executed preventive maintenance or corrective repairs."""

    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name="maintenance_logs",
    )
    schedule = models.ForeignKey(
        MaintenanceSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs",
    )
    damage_report = models.ForeignKey(
        DamageReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenance_logs",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="performed_maintenances",
    )
    performed_date = models.DateField()
    summary = models.TextField()
    cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    result_condition = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices,
    )

    class Meta:
        verbose_name = "Log Pemeliharaan"
        verbose_name_plural = "Log Pemeliharaan"
        ordering = ["-performed_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cost__gte=Decimal("0.00")),
                name="maintenance_log_cost_gte_0",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.asset.asset_code} ({self.performed_date}) — Rp {self.cost:,.2f}"
