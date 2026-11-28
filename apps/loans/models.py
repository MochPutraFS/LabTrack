from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.inventory.models import Asset


class Loan(TimeStampedModel):
    """Hybrid loan transaction supporting both ONLINE requests and WALK_IN counter loans."""

    class Channel(models.TextChoices):
        ONLINE = "ONLINE", "Online"
        WALK_IN = "WALK_IN", "Walk-In"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Menunggu Persetujuan"
        APPROVED = "APPROVED", "Disetujui"
        REJECTED = "REJECTED", "Ditolak"
        ACTIVE = "ACTIVE", "Sedang Dipinjam"
        OVERDUE = "OVERDUE", "Terlambat"
        RETURNED = "RETURNED", "Dikembalikan"
        CANCELLED = "CANCELLED", "Dibatalkan"

    loan_number = models.CharField(
        max_length=30,
        unique=True,
        db_index=True,
        help_text="Format LOAN-YYYYMMDD-NNNN",
    )
    loan_channel = models.CharField(
        max_length=15,
        choices=Channel.choices,
        db_index=True,
    )
    borrower_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="loans",
    )
    borrower_name = models.CharField(max_length=150)
    borrower_identifier = models.CharField(max_length=50, help_text="NIM / NIP peminjam")
    borrower_contact = models.CharField(max_length=60, help_text="No. HP / Email peminjam")
    purpose = models.TextField()
    borrow_date = models.DateField()
    due_date = models.DateField()
    handed_over_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processed_loans",
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_loans",
    )
    rejection_reason = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Peminjaman Aset"
        verbose_name_plural = "Peminjaman Aset"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(due_date__gte=F("borrow_date")),
                name="loan_due_date_gte_borrow_date",
            ),
        ]

    def clean(self):
        super().clean()
        if self.borrow_date and self.due_date and self.due_date < self.borrow_date:
            raise ValidationError(
                {"due_date": "Tanggal jatuh tempo tidak boleh lebih awal dari tanggal pinjam."}
            )
        if self.loan_channel == self.Channel.ONLINE and self.borrower_user is None:
            raise ValidationError(
                {"borrower_user": "Peminjaman jalur ONLINE wajib terhubung dengan akun pengguna."}
            )

    def __str__(self) -> str:
        return f"{self.loan_number} — {self.borrower_name} ({self.get_status_display()})"

    @property
    def is_overdue(self) -> bool:
        if self.status == self.Status.OVERDUE:
            return True
        if self.status == self.Status.ACTIVE and self.due_date:
            return self.due_date < timezone.localdate()
        return False


class LoanItem(TimeStampedModel):
    """Individual asset line item belonging to a Loan transaction."""

    loan = models.ForeignKey(
        Loan,
        on_delete=models.CASCADE,
        related_name="items",
    )
    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name="loan_items",
    )
    condition_on_checkout = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices,
    )
    condition_on_return = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices,
        blank=True,
        default="",
    )
    return_notes = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Item Peminjaman"
        verbose_name_plural = "Item Peminjaman"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "asset"],
                name="unique_loan_asset_item",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.loan.loan_number} -> {self.asset.asset_code}"
