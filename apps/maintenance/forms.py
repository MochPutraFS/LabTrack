"""Forms for Damage Reports, Status Transitions, Maintenance Schedules, and Execution Logs."""

from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from apps.accounts.forms import CHECKBOX_CLASS, INPUT_CLASS, SELECT_CLASS
from apps.inventory.models import Asset
from apps.maintenance import services
from apps.maintenance.models import DamageReport, MaintenanceSchedule

User = get_user_model()


def active_assets_queryset():
    """Return active, non-RETIRED assets ordered by asset_code."""
    return (
        Asset.objects.select_related("category", "location")
        .filter(is_active=True)
        .exclude(status=Asset.Status.RETIRED)
        .order_by("asset_code")
    )


class DamageReportCreateForm(forms.ModelForm):
    """Form for any authenticated user to report laboratory asset damage."""

    class Meta:
        model = DamageReport
        fields = ("asset", "severity", "description", "photo")
        labels = {
            "asset": "Aset yang Dilaporkan",
            "severity": "Tingkat Keparahan",
            "description": "Deskripsi Gejala Kerusakan",
            "photo": "Foto Bukti Kerusakan (Opsional — JPG/PNG/WebP, maks 2 MB)",
        }
        widgets = {
            "asset": forms.Select(attrs={"class": SELECT_CLASS}),
            "severity": forms.Select(attrs={"class": SELECT_CLASS}),
            "description": forms.Textarea(
                attrs={
                    "class": INPUT_CLASS,
                    "rows": 4,
                    "placeholder": "Jelaskan gejala kerusakan, waktu ditemukan, dan kondisi fisik aset...",
                }
            ),
            "photo": forms.ClearableFileInput(
                attrs={"class": INPUT_CLASS, "accept": ".jpg,.jpeg,.png,.webp"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset"].queryset = active_assets_queryset()
        self.fields["asset"].empty_label = "-- Pilih Aset Laboratorium --"

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo:
            try:
                services.validate_damage_photo(photo)
            except DjangoValidationError as exc:
                raise forms.ValidationError(exc.messages) from exc
        return photo


class DamageReportStatusForm(forms.Form):
    """Staff-only form to advance DamageReport status along the state machine."""

    new_status = forms.ChoiceField(
        label="Status Tindak Lanjut",
        choices=[],
        widget=forms.Select(attrs={"class": SELECT_CLASS, "id": "id_new_status"}),
    )
    resolution_notes = forms.CharField(
        label="Catatan Verifikasi / Penanganan",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": INPUT_CLASS,
                "rows": 3,
                "placeholder": "Catat hasil inspeksi fisik, tindakan perbaikan, atau alasan tidak dapat diperbaiki...",
            }
        ),
    )
    create_maintenance_log = forms.BooleanField(
        label="Catat juga sebagai Log Pemeliharaan (riwayat biaya perbaikan)",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": CHECKBOX_CLASS, "id": "id_create_maintenance_log"}),
    )
    performed_date = forms.DateField(
        label="Tanggal Selesai Perbaikan",
        required=False,
        widget=forms.DateInput(attrs={"class": INPUT_CLASS, "type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    repair_cost = forms.DecimalField(
        label="Biaya Perbaikan (Rp)",
        required=False,
        min_value=Decimal("0.00"),
        max_digits=14,
        decimal_places=2,
        initial=Decimal("0.00"),
        widget=forms.NumberInput(
            attrs={
                "class": INPUT_CLASS + " font-mono-num",
                "step": "0.01",
                "min": "0",
                "placeholder": "0",
            }
        ),
    )
    repair_summary = forms.CharField(
        label="Ringkasan Tindakan & Suku Cadang (Log Pemeliharaan)",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": INPUT_CLASS,
                "rows": 2,
                "placeholder": "Contoh: Penggantian PSU 500W dan pembersihan heatsink...",
            }
        ),
    )

    def __init__(self, *args, report: DamageReport | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.report = report
        if report is not None:
            self.fields["new_status"].choices = services.get_allowed_damage_next_statuses(report.status)
        if not self.is_bound:
            self.initial.setdefault("performed_date", timezone.localdate())
            self.initial.setdefault("repair_cost", Decimal("0.00"))


class MaintenanceScheduleForm(forms.ModelForm):
    """Staff-only form to create or edit a periodic/one-time MaintenanceSchedule."""

    class Meta:
        model = MaintenanceSchedule
        fields = (
            "asset",
            "title",
            "description",
            "frequency",
            "next_due_date",
            "assigned_to",
            "status",
        )
        labels = {
            "asset": "Aset Target",
            "title": "Judul Kegiatan Pemeliharaan",
            "description": "Checklist / Deskripsi Pekerjaan",
            "frequency": "Frekuensi Pemeliharaan",
            "next_due_date": "Tanggal Jatuh Tempo Berikutnya",
            "assigned_to": "Teknisi Penanggung Jawab",
            "status": "Status Jadwal",
        }
        widgets = {
            "asset": forms.Select(attrs={"class": SELECT_CLASS}),
            "title": forms.TextInput(
                attrs={
                    "class": INPUT_CLASS,
                    "placeholder": "Contoh: Pembersihan Filter & Kalibrasi Proyektor",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": INPUT_CLASS,
                    "rows": 3,
                    "placeholder": "Langkah kerja, checklist kalibrasi, atau kebutuhan suku cadang...",
                }
            ),
            "frequency": forms.Select(attrs={"class": SELECT_CLASS}),
            "next_due_date": forms.DateInput(
                attrs={"class": INPUT_CLASS, "type": "date"},
                format="%Y-%m-%d",
            ),
            "assigned_to": forms.Select(attrs={"class": SELECT_CLASS}),
            "status": forms.Select(attrs={"class": SELECT_CLASS}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset"].queryset = active_assets_queryset()
        self.fields["asset"].empty_label = "-- Pilih Aset Laboratorium --"
        self.fields["assigned_to"].queryset = User.objects.filter(
            is_active=True,
            role__in=(User.Role.ADMIN, User.Role.LABORAN),
        ).order_by("full_name", "username")
        self.fields["assigned_to"].empty_label = "-- Belum Ditentukan --"
        self.fields["next_due_date"].input_formats = ["%Y-%m-%d"]

        if not (self.instance and self.instance.pk):
            self.fields.pop("status", None)
            if not self.is_bound:
                self.initial.setdefault("next_due_date", timezone.localdate() + timedelta(days=7))


class MaintenanceExecuteForm(forms.Form):
    """Staff-only form to record maintenance execution (MaintenanceLog) for a schedule."""

    performed_date = forms.DateField(
        label="Tanggal Pelaksanaan",
        widget=forms.DateInput(attrs={"class": INPUT_CLASS, "type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    result_condition = forms.ChoiceField(
        label="Kondisi Akhir Aset Pasca-Pemeliharaan",
        choices=Asset.Condition.choices,
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    cost = forms.DecimalField(
        label="Biaya Pemeliharaan / Suku Cadang (Rp)",
        min_value=Decimal("0.00"),
        max_digits=14,
        decimal_places=2,
        initial=Decimal("0.00"),
        widget=forms.NumberInput(
            attrs={
                "class": INPUT_CLASS + " font-mono-num",
                "step": "0.01",
                "min": "0",
                "placeholder": "0",
            }
        ),
    )
    summary = forms.CharField(
        label="Ringkasan Tindakan & Suku Cadang",
        widget=forms.Textarea(
            attrs={
                "class": INPUT_CLASS,
                "rows": 4,
                "placeholder": "Catat tindakan pemeliharaan yang dilakukan, penggantian komponen, dan hasil pengujian...",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault("performed_date", timezone.localdate())
            self.initial.setdefault("result_condition", Asset.Condition.GOOD)
            self.initial.setdefault("cost", Decimal("0.00"))
