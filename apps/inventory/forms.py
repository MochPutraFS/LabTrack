"""Forms for Category, Location, Asset CRUD, Location Move, and Asset Retirement."""

from pathlib import Path

from django import forms

from apps.accounts.forms import CHECKBOX_CLASS, INPUT_CLASS, SELECT_CLASS
from apps.inventory.models import Asset, Category, Location

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2 MB (NFR-02)


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ("code", "name", "default_useful_life_years", "description")
        labels = {
            "code": "Kode Kategori",
            "name": "Nama Kategori",
            "default_useful_life_years": "Umur Ekonomis Default (Tahun)",
            "description": "Deskripsi",
        }
        widgets = {
            "code": forms.TextInput(
                attrs={
                    "class": INPUT_CLASS,
                    "placeholder": "Contoh: KOM, JAR, PRJ",
                    "autocorrect": "off",
                    "autocapitalize": "characters",
                    "spellcheck": "false",
                }
            ),
            "name": forms.TextInput(attrs={"class": INPUT_CLASS, "placeholder": "Contoh: Komputer & Workstation"}),
            "default_useful_life_years": forms.NumberInput(attrs={"class": INPUT_CLASS, "min": 1, "max": 50}),
            "description": forms.Textarea(attrs={"class": INPUT_CLASS, "rows": 2}),
        }


class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ("code", "name", "building", "floor", "pic_name", "description", "is_active")
        labels = {
            "code": "Kode Ruangan",
            "name": "Nama Ruangan / Laboratorium",
            "building": "Gedung",
            "floor": "Lantai",
            "pic_name": "Penanggung Jawab (PIC)",
            "description": "Keterangan / Kapasitas",
            "is_active": "Lokasi Aktif",
        }
        widgets = {
            "code": forms.TextInput(
                attrs={
                    "class": INPUT_CLASS,
                    "placeholder": "Contoh: LAB-RPL",
                    "autocorrect": "off",
                    "autocapitalize": "characters",
                    "spellcheck": "false",
                }
            ),
            "name": forms.TextInput(attrs={"class": INPUT_CLASS, "placeholder": "Contoh: Lab RPL & Basis Data"}),
            "building": forms.TextInput(attrs={"class": INPUT_CLASS, "placeholder": "Contoh: Gedung Sains"}),
            "floor": forms.TextInput(attrs={"class": INPUT_CLASS, "placeholder": "Contoh: Lantai 2"}),
            "pic_name": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "description": forms.Textarea(attrs={"class": INPUT_CLASS, "rows": 2}),
            "is_active": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASS}),
        }


class AssetForm(forms.ModelForm):
    asset_code = forms.CharField(
        label="Kode Aset",
        required=False,
        help_text="Kosongkan untuk menghasilkan otomatis (LAB-KAT-TAHUN-URUT).",
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CLASS + " font-mono-num",
                "placeholder": "Otomatis jika dikosongkan",
                "autocorrect": "off",
                "autocapitalize": "characters",
                "spellcheck": "false",
            }
        ),
    )

    class Meta:
        model = Asset
        fields = (
            "asset_code",
            "name",
            "category",
            "location",
            "brand",
            "model_name",
            "serial_number",
            "acquisition_date",
            "acquisition_cost",
            "useful_life_years",
            "salvage_value",
            "condition",
            "status",
            "photo",
            "specifications",
        )
        labels = {
            "name": "Nama Aset",
            "category": "Kategori",
            "location": "Lokasi Ruangan",
            "brand": "Merek",
            "model_name": "Model / Tipe",
            "serial_number": "Nomor Seri",
            "acquisition_date": "Tanggal Perolehan",
            "acquisition_cost": "Harga Perolehan (Rp)",
            "useful_life_years": "Umur Ekonomis (Tahun)",
            "salvage_value": "Nilai Residu (Rp)",
            "condition": "Kondisi Fisik",
            "status": "Status Operasional",
            "photo": "Foto Aset (JPG/PNG/WebP, maks 2 MB)",
            "specifications": "Spesifikasi & Catatan",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "category": forms.Select(attrs={"class": SELECT_CLASS}),
            "location": forms.Select(attrs={"class": SELECT_CLASS}),
            "brand": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "model_name": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "serial_number": forms.TextInput(attrs={"class": INPUT_CLASS + " font-mono-num"}),
            "acquisition_date": forms.DateInput(attrs={"class": INPUT_CLASS, "type": "date"}, format="%Y-%m-%d"),
            "acquisition_cost": forms.NumberInput(attrs={"class": INPUT_CLASS + " font-mono-num", "step": "0.01", "min": "0"}),
            "useful_life_years": forms.NumberInput(attrs={"class": INPUT_CLASS + " font-mono-num", "min": "1", "max": "50"}),
            "salvage_value": forms.NumberInput(attrs={"class": INPUT_CLASS + " font-mono-num", "step": "0.01", "min": "0"}),
            "condition": forms.Select(attrs={"class": SELECT_CLASS}),
            "status": forms.Select(attrs={"class": SELECT_CLASS}),
            "photo": forms.ClearableFileInput(attrs={"class": INPUT_CLASS, "accept": ".jpg,.jpeg,.png,.webp"}),
            "specifications": forms.Textarea(attrs={"class": INPUT_CLASS, "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["acquisition_date"].input_formats = ["%Y-%m-%d"]
        # Prevent setting RETIRED directly here; retiring requires Admin-only retire workflow
        if not (self.instance and self.instance.pk and self.instance.status == Asset.Status.RETIRED):
            self.fields["status"].choices = [
                c for c in Asset.Status.choices if c[0] != Asset.Status.RETIRED
            ]
        if self.instance and self.instance.pk:
            self.fields["asset_code"].disabled = True
            self.fields["asset_code"].help_text = "Kode aset tidak dapat diubah setelah dibuat."

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and hasattr(photo, "size"):
            ext = Path(photo.name).suffix.lower()
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                raise forms.ValidationError("Format foto harus JPG, PNG, atau WebP.")
            if photo.size > MAX_IMAGE_BYTES:
                raise forms.ValidationError("Ukuran foto maksimal 2 MB.")
        return photo

    def clean(self):
        cleaned = super().clean()
        cost = cleaned.get("acquisition_cost")
        salvage = cleaned.get("salvage_value")
        if cost is not None and salvage is not None and salvage > cost:
            self.add_error("salvage_value", "Nilai residu tidak boleh lebih besar dari harga perolehan.")
        return cleaned


class AssetMoveForm(forms.Form):
    """Form for relocating an asset to another laboratory room."""

    to_location = forms.ModelChoiceField(
        label="Lokasi Tujuan",
        queryset=Location.objects.filter(is_active=True),
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    reason = forms.CharField(
        label="Alasan Mutasi",
        widget=forms.Textarea(
            attrs={
                "class": INPUT_CLASS,
                "rows": 3,
                "placeholder": "Contoh: Dipindahkan untuk kebutuhan praktikum semester ganjil",
            }
        ),
    )

    def __init__(self, *args, current_location=None, **kwargs):
        super().__init__(*args, **kwargs)
        if current_location:
            self.fields["to_location"].queryset = Location.objects.filter(is_active=True).exclude(
                pk=current_location.pk
            )


class AssetRetireForm(forms.Form):
    """Admin-only form to retire (soft-delete) an asset with mandatory reason."""

    reason = forms.CharField(
        label="Alasan Penghapusbukuan",
        widget=forms.Textarea(
            attrs={
                "class": INPUT_CLASS,
                "rows": 3,
                "placeholder": "Jelaskan alasan penghapusbukuan aset (misal: rusak permanen / melewati umur ekonomis)",
            }
        ),
    )
