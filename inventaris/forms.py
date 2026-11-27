from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from .models import Aset, JadwalPemeliharaan, KategoriAset, LaporanKerusakan, LokasiLab, Peminjaman

User = get_user_model()

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


class PeminjamanForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Peminjaman
        fields = ['aset', 'tanggal_pinjam', 'tanggal_rencana_kembali', 'keperluan']
        labels = {
            'aset': 'Aset Laboratorium',
            'tanggal_pinjam': 'Tanggal Pinjam',
            'tanggal_rencana_kembali': 'Tanggal Rencana Kembali',
            'keperluan': 'Keperluan Peminjaman',
        }
        widgets = {
            'tanggal_pinjam': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'tanggal_rencana_kembali': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'keperluan': forms.Textarea(attrs={'placeholder': 'Tuliskan kegiatan atau keperluan penggunaan aset'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['aset'].queryset = (
            Aset.objects.filter(status='TERSEDIA')
            .exclude(kondisi='RUSAK_BERAT')
            .select_related('lokasi')
            .order_by('kode_aset')
        )
        self.fields['tanggal_pinjam'].input_formats = ['%Y-%m-%d']
        self.fields['tanggal_rencana_kembali'].input_formats = ['%Y-%m-%d']
        if not self.initial.get('tanggal_pinjam'):
            self.initial['tanggal_pinjam'] = timezone.localdate()
        self._apply_widget_styles()

    def clean(self):
        cleaned = super().clean()
        aset = cleaned.get('aset')
        tgl_pinjam = cleaned.get('tanggal_pinjam')
        tgl_kembali = cleaned.get('tanggal_rencana_kembali')

        if tgl_pinjam and tgl_kembali and tgl_kembali < tgl_pinjam:
            self.add_error('tanggal_rencana_kembali', 'Tanggal rencana kembali tidak boleh lebih awal dari tanggal pinjam.')
        if aset and (aset.status != 'TERSEDIA' or aset.kondisi == 'RUSAK_BERAT'):
            self.add_error('aset', 'Aset yang dipilih saat ini tidak tersedia untuk dipinjam.')
        return cleaned


class PengembalianForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Peminjaman
        fields = ['tanggal_kembali_aktual', 'kondisi_saat_kembali', 'catatan_admin']
        labels = {
            'tanggal_kembali_aktual': 'Tanggal Kembali Aktual',
            'kondisi_saat_kembali': 'Kondisi Aset Saat Kembali',
            'catatan_admin': 'Catatan Admin (Opsional)',
        }
        widgets = {
            'tanggal_kembali_aktual': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'catatan_admin': forms.Textarea(attrs={'placeholder': 'Catatan kondisi atau kelengkapan saat pengembalian'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tanggal_kembali_aktual'].required = True
        self.fields['tanggal_kembali_aktual'].input_formats = ['%Y-%m-%d']
        if not self.initial.get('tanggal_kembali_aktual'):
            self.initial['tanggal_kembali_aktual'] = timezone.localdate()
        self.fields['kondisi_saat_kembali'].required = True
        self.fields['kondisi_saat_kembali'].choices = Peminjaman.KONDISI_KEMBALI_CHOICES
        self.initial.setdefault('kondisi_saat_kembali', 'BAIK')
        self._apply_widget_styles()


class LaporanKerusakanForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LaporanKerusakan
        fields = ['aset', 'judul_kerusakan', 'tingkat_keparahan', 'deskripsi', 'foto_bukti']
        labels = {
            'aset': 'Aset Laboratorium',
            'judul_kerusakan': 'Judul Kerusakan',
            'tingkat_keparahan': 'Tingkat Keparahan',
            'deskripsi': 'Deskripsi Kerusakan',
            'foto_bukti': 'Foto Bukti (Opsional)',
        }
        widgets = {
            'judul_kerusakan': forms.TextInput(attrs={'placeholder': 'Mis. Layar tidak menyala / kabel putus'}),
            'deskripsi': forms.Textarea(attrs={'placeholder': 'Jelaskan gejala kerusakan dan kondisi terakhir'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['aset'].queryset = Aset.objects.select_related('lokasi').order_by('kode_aset')
        self._apply_widget_styles()


class PenangananKerusakanForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LaporanKerusakan
        fields = ['status', 'catatan_penanganan']
        labels = {
            'status': 'Status Penanganan',
            'catatan_penanganan': 'Catatan Penanganan',
        }
        widgets = {
            'catatan_penanganan': forms.Textarea(attrs={'placeholder': 'Hasil pemeriksaan atau tindak lanjut'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_styles()


class JadwalPemeliharaanForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = JadwalPemeliharaan
        fields = ['aset', 'jenis', 'laporan_kerusakan', 'tanggal_jadwal', 'teknisi', 'deskripsi_kegiatan', 'biaya']
        labels = {
            'aset': 'Aset Laboratorium',
            'jenis': 'Jenis Pemeliharaan',
            'laporan_kerusakan': 'Laporan Kerusakan Terkait (Opsional)',
            'tanggal_jadwal': 'Tanggal Jadwal',
            'teknisi': 'Teknisi Penanggung Jawab',
            'deskripsi_kegiatan': 'Deskripsi Kegiatan',
            'biaya': 'Estimasi Biaya (Rp)',
        }
        widgets = {
            'tanggal_jadwal': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'deskripsi_kegiatan': forms.Textarea(attrs={'placeholder': 'Rencana tindakan pemeliharaan atau kalibrasi'}),
            'biaya': forms.NumberInput(attrs={'min': 0, 'step': '1000'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['aset'].queryset = Aset.objects.select_related('lokasi').order_by('kode_aset')
        self.fields['laporan_kerusakan'].required = False
        self.fields['laporan_kerusakan'].queryset = LaporanKerusakan.objects.select_related('aset').order_by('-tanggal_lapor')
        self.fields['teknisi'].required = False
        self.fields['teknisi'].queryset = User.objects.filter(
            Q(profile__role__in=['TEKNISI', 'ADMIN']) | Q(is_superuser=True)
        ).distinct().order_by('username')
        self.fields['tanggal_jadwal'].input_formats = ['%Y-%m-%d']
        if not self.initial.get('tanggal_jadwal'):
            self.initial['tanggal_jadwal'] = timezone.localdate()
        self._apply_widget_styles()


class SelesaiPemeliharaanForm(StyledFormMixin, forms.Form):
    KONDISI_AKHIR_CHOICES = [
        ('BAIK', 'Baik'),
        ('RUSAK_RINGAN', 'Rusak Ringan'),
        ('RUSAK_BERAT', 'Rusak Berat'),
    ]

    tanggal_selesai = forms.DateField(
        label='Tanggal Selesai',
        input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
    )
    biaya = forms.DecimalField(
        label='Realisasi Biaya (Rp)',
        min_value=0,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'min': 0, 'step': '1000'}),
    )
    kondisi_akhir = forms.ChoiceField(
        label='Kondisi Akhir Aset',
        choices=KONDISI_AKHIR_CHOICES,
        initial='BAIK',
    )
    catatan_hasil = forms.CharField(
        label='Catatan Hasil Pemeliharaan',
        required=False,
        widget=forms.Textarea(attrs={'placeholder': 'Ringkasan pekerjaan dan hasil uji fungsi'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get('tanggal_selesai'):
            self.initial['tanggal_selesai'] = timezone.localdate()
        self._apply_widget_styles()
