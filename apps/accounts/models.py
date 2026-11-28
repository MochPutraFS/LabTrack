from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom User model supporting LabTrack RBAC roles."""

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        LABORAN = "LABORAN", "Laboran / Teknisi"
        BORROWER = "BORROWER", "Peminjam"

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.BORROWER,
        db_index=True,
    )
    identifier_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
        help_text="NIM / NIP / ID Staf",
    )
    phone_number = models.CharField(max_length=30, blank=True, default="")
    department = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    REQUIRED_FIELDS = ["email", "full_name"]

    class Meta:
        verbose_name = "Pengguna"
        verbose_name_plural = "Pengguna"
        ordering = ["full_name", "username"]

    def __str__(self) -> str:
        display = self.full_name or self.username
        return f"{display} ({self.get_role_display()})"

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN

    @property
    def is_laboran(self) -> bool:
        return self.role == self.Role.LABORAN

    @property
    def is_staff_lab(self) -> bool:
        return self.role in (self.Role.ADMIN, self.Role.LABORAN)

    @property
    def is_borrower(self) -> bool:
        return self.role == self.Role.BORROWER
