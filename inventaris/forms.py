from django import forms

from .models import Aset, KategoriAset, LokasiLab

INPUT_CLASS = (
    'block w-full min-h-[42px] rounded-md border border-stone-300 bg-white px-3.5 py-2 '
    'text-sm text-ink placeholder:text-stone-400 transition-colors '
    'focus:border-ink focus:outline-none focus:ring-2 focus:ring-ink/15'
)
TEXTAREA_CLASS = (
    'block w-full rounded-md border border-stone-300 bg-white px-3.5 py-2 '
    'text-sm text-ink placeholder:text-stone-400 transition-colors '
    'focus:border-ink focus:outline-none focus:ring-2 focus:ring-ink/15'
)
FILE_CLASS = (
    'block w-full text-sm text-muted file:mr-3 file:rounded-md file:border file:border-stone-300 '
    'file:bg-canvas file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-ink '
    'hover:file:bg-stone-200/70'
)


class StyledFormMixin:
    """Terapkan class Tailwind konsisten pada seluruh widget form."""

    def _apply_widget_styles(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault('rows', 3)
                widget.attrs['class'] = f"{widget.attrs.get('class', '')} {TEXTAREA_CLASS}".strip()
            elif isinstance(widget, forms.ClearableFileInput):
                widget.attrs['class'] = f"{widget.attrs.get('class', '')} {FILE_CLASS}".strip()
            else:
                widget.attrs['class'] = f"{widget.attrs.get('class', '')} {INPUT_CLASS}".strip()


class KategoriAsetForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = KategoriAset
        fields = ['kode', 'nama', 'deskripsi']
        labels = {
            'kode': 'Kode Kategori',
            'nama': 'Nama Kategori',
            'deskripsi': 'Deskripsi',
        }
        widgets = {
            'kode': forms.TextInput(attrs={'placeholder': 'Mis. KOM'}),
            'nama': forms.TextInput(attrs={'placeholder': 'Mis. Perangkat Komputer'}),
            'deskripsi': forms.Textarea(attrs={'placeholder': 'Keterangan singkat kategori barang (opsional)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_styles()

    def clean_kode(self):
        return self.cleaned_data['kode'].strip().upper()


class LokasiLabForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LokasiLab
        fields = ['kode_ruang', 'nama_ruang', 'gedung', 'penanggung_jawab', 'kapasitas']
        labels = {
            'kode_ruang': 'Kode Ruang',
            'nama_ruang': 'Nama Ruang',
            'gedung': 'Gedung',
            'penanggung_jawab': 'Penanggung Jawab',
            'kapasitas': 'Kapasitas',
        }
        widgets = {
            'kode_ruang': forms.TextInput(attrs={'placeholder': 'Mis. LAB-RPL'}),
            'nama_ruang': forms.TextInput(attrs={'placeholder': 'Mis. Laboratorium Rekayasa Perangkat Lunak'}),
            'gedung': forms.TextInput(attrs={'placeholder': 'Mis. Gedung Sains Lt. 2'}),
            'penanggung_jawab': forms.TextInput(attrs={'placeholder': 'Nama penanggung jawab ruangan'}),
            'kapasitas': forms.NumberInput(attrs={'min': 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_styles()

    def clean_kode_ruang(self):
        return self.cleaned_data['kode_ruang'].strip().upper()


class AsetForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Aset
        fields = [
            'kode_aset',
            'nama_aset',
            'kategori',
            'lokasi',
            'merk_tipe',
            'nomor_seri',
            'spesifikasi',
            'tanggal_perolehan',
            'harga_perolehan',
            'nilai_residu',
            'umur_ekonomis_tahun',
            'kondisi',
            'status',
            'foto',
            'catatan',
        ]
        labels = {
            'kode_aset': 'Kode Aset',
            'nama_aset': 'Nama Aset',
            'kategori': 'Kategori',
            'lokasi': 'Lokasi Lab',
            'merk_tipe': 'Merk / Tipe',
            'nomor_seri': 'Nomor Seri',
            'spesifikasi': 'Spesifikasi Teknis',
            'tanggal_perolehan': 'Tanggal Perolehan',
            'harga_perolehan': 'Harga Perolehan (Rp)',
            'nilai_residu': 'Nilai Residu (Rp)',
            'umur_ekonomis_tahun': 'Umur Ekonomis (Tahun)',
            'kondisi': 'Kondisi Fisik',
            'status': 'Status Aset',
            'foto': 'Foto Aset (Opsional)',
            'catatan': 'Catatan',
        }
        widgets = {
            'kode_aset': forms.TextInput(attrs={'placeholder': 'Kosongkan untuk generate otomatis'}),
            'nama_aset': forms.TextInput(attrs={'placeholder': 'Mis. Workstation PC Dell Precision'}),
            'merk_tipe': forms.TextInput(attrs={'placeholder': 'Mis. Dell Precision 3660'}),
            'nomor_seri': forms.TextInput(attrs={'placeholder': 'Opsional'}),
            'tanggal_perolehan': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'harga_perolehan': forms.NumberInput(attrs={'min': 0, 'step': '1000'}),
            'nilai_residu': forms.NumberInput(attrs={'min': 0, 'step': '1000'}),
            'umur_ekonomis_tahun': forms.NumberInput(attrs={'min': 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['kode_aset'].required = False
        self.fields['tanggal_perolehan'].input_formats = ['%Y-%m-%d']
        self._apply_widget_styles()

    def clean(self):
        cleaned = super().clean()
        harga = cleaned.get('harga_perolehan')
        residu = cleaned.get('nilai_residu')
        if harga is not None and residu is not None and residu > harga:
            self.add_error('nilai_residu', 'Nilai residu tidak boleh melebihi harga perolehan.')
        return cleaned
