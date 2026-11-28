"""Forms for Online Loan Request, Walk-In Loan Recording, Rejection, and Return Inspection."""

from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.forms import INPUT_CLASS, SELECT_CLASS
from apps.inventory.models import Asset

User = get_user_model()


def borrowable_assets_queryset():
    """Return active, AVAILABLE assets that are not in MAJOR_DAMAGE condition."""
    return (
        Asset.objects.select_related("category", "location")
        .filter(is_active=True, status=Asset.Status.AVAILABLE)
        .exclude(condition=Asset.Condition.MAJOR_DAMAGE)
        .order_by("asset_code")
    )


class LoanOnlineRequestForm(forms.Form):
    """Form for authenticated users to submit an ONLINE loan request."""

    assets = forms.ModelMultipleChoiceField(
        label="Pilih Aset Tersedia",
        queryset=Asset.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Pilih minimal satu aset yang ingin dipinjam."},
    )
    borrow_date = forms.DateField(
        label="Tanggal Rencana Pinjam",
        widget=forms.DateInput(attrs={"class": INPUT_CLASS, "type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    due_date = forms.DateField(
        label="Tanggal Jatuh Tempo Kembali",
        widget=forms.DateInput(attrs={"class": INPUT_CLASS, "type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    purpose = forms.CharField(
        label="Tujuan / Keperluan Peminjaman",
        widget=forms.Textarea(
            attrs={
                "class": INPUT_CLASS,
                "rows": 3,
                "placeholder": "Contoh: Praktikum Basis Data Pertemuan 5 / Penelitian Tugas Akhir",
            }
        ),
    )
    notes = forms.CharField(
        label="Catatan Tambahan (Opsional)",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": INPUT_CLASS,
                "rows": 2,
                "placeholder": "Catatan tambahan untuk laboran jika diperlukan",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assets"].queryset = borrowable_assets_queryset()
        today = timezone.localdate()
        if not self.is_bound:
            self.initial.setdefault("borrow_date", today)
            self.initial.setdefault("due_date", today + timedelta(days=3))

    def clean(self):
        cleaned = super().clean()
        borrow_date = cleaned.get("borrow_date")
        due_date = cleaned.get("due_date")
        if borrow_date and due_date and due_date < borrow_date:
            self.add_error(
                "due_date",
                "Tanggal jatuh tempo tidak boleh lebih awal dari tanggal pinjam.",
            )
        return cleaned


class LoanWalkInForm(forms.Form):
    """Fast Walk-In counter loan form for Admin/Laboran (<30s input)."""

    borrower_user = forms.ModelChoiceField(
        label="Pilih Akun Peminjam Terdaftar (Opsional — Auto-Fill)",
        queryset=User.objects.none(),
        required=False,
        empty_label="-- Input Manual (Peminjam Tanpa Akun) --",
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    borrower_name = forms.CharField(
        label="Nama Lengkap Peminjam",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CLASS,
                "placeholder": "Nama lengkap mahasiswa / dosen",
                "autocomplete": "name",
            }
        ),
    )
    borrower_identifier = forms.CharField(
        label="NIM / NIP",
        max_length=50,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CLASS + " font-mono-num",
                "placeholder": "Contoh: H071241001",
                "autocorrect": "off",
                "autocapitalize": "characters",
                "spellcheck": "false",
            }
        ),
    )
    borrower_contact = forms.CharField(
        label="No. HP / WhatsApp / Email",
        max_length=60,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CLASS,
                "placeholder": "Contoh: 0812-3456-7890",
                "autocomplete": "tel",
                "inputmode": "tel",
                "autocorrect": "off",
                "spellcheck": "false",
            }
        ),
    )
    assets = forms.ModelMultipleChoiceField(
        label="Pilih Aset Tersedia",
        queryset=Asset.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Pilih minimal satu aset untuk dipinjamkan."},
    )
    borrow_date = forms.DateField(
        label="Tanggal Pinjam",
        widget=forms.DateInput(attrs={"class": INPUT_CLASS, "type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    due_date = forms.DateField(
        label="Tanggal Jatuh Tempo Kembali",
        widget=forms.DateInput(attrs={"class": INPUT_CLASS, "type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    purpose = forms.CharField(
        label="Keperluan Peminjaman",
        widget=forms.Textarea(
            attrs={
                "class": INPUT_CLASS,
                "rows": 2,
                "placeholder": "Contoh: Praktikum Jaringan Komputer / Presentasi Seminar",
            }
        ),
    )
    notes = forms.CharField(
        label="Catatan Serah Terima (Opsional)",
        required=False,
        widget=forms.Textarea(attrs={"class": INPUT_CLASS, "rows": 2}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["borrower_user"].queryset = User.objects.filter(
            is_active=True, role=User.Role.BORROWER
        ).order_by("full_name", "username")
        self.fields["assets"].queryset = borrowable_assets_queryset()
        today = timezone.localdate()
        if not self.is_bound:
            self.initial.setdefault("borrow_date", today)
            self.initial.setdefault("due_date", today + timedelta(days=3))

    def clean(self):
        cleaned = super().clean()
        borrow_date = cleaned.get("borrow_date")
        due_date = cleaned.get("due_date")
        if borrow_date and due_date and due_date < borrow_date:
            self.add_error(
                "due_date",
                "Tanggal jatuh tempo tidak boleh lebih awal dari tanggal pinjam.",
            )
        return cleaned


class LoanRejectForm(forms.Form):
    """Form for rejecting a PENDING loan with mandatory reason."""

    rejection_reason = forms.CharField(
        label="Alasan Penolakan",
        widget=forms.Textarea(
            attrs={
                "class": INPUT_CLASS,
                "rows": 3,
                "placeholder": "Jelaskan alasan penolakan pengajuan peminjaman...",
            }
        ),
        error_messages={"required": "Alasan penolakan wajib diisi."},
    )


class LoanReturnForm(forms.Form):
    """Dynamic per-item condition inspection form for returning a loan."""

    def __init__(self, *args, items=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.loan_items = list(items or [])
        for item in self.loan_items:
            cond_key = f"condition_{item.pk}"
            notes_key = f"notes_{item.pk}"
            self.fields[cond_key] = forms.ChoiceField(
                label=f"Kondisi Pengembalian — {item.asset.asset_code}",
                choices=Asset.Condition.choices,
                initial=item.condition_on_checkout or Asset.Condition.GOOD,
                widget=forms.RadioSelect,
            )
            self.fields[notes_key] = forms.CharField(
                label="Catatan Inspeksi (Opsional)",
                required=False,
                widget=forms.Textarea(
                    attrs={
                        "class": INPUT_CLASS,
                        "rows": 2,
                        "placeholder": "Catat kelengkapan atau gejala kerusakan jika ada...",
                    }
                ),
            )

    def get_item_rows(self):
        """Yield dicts pairing each LoanItem with its bound condition and notes fields."""
        return [
            {
                "item": item,
                "condition_field": self[f"condition_{item.pk}"],
                "notes_field": self[f"notes_{item.pk}"],
            }
            for item in self.loan_items
        ]

    def build_inspections(self) -> dict[int, dict[str, str]]:
        return {
            item.pk: {
                "condition": self.cleaned_data[f"condition_{item.pk}"],
                "notes": self.cleaned_data.get(f"notes_{item.pk}", ""),
            }
            for item in self.loan_items
        }
