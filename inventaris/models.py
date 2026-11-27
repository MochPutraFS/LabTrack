from django.contrib.auth.models import User
from django.db import models

from .services import hitung_penyusutan


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('ADMIN', 'Admin'),
        ('TEKNISI', 'Teknisi'),
        ('PEMINJAM', 'Peminjam'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='PEMINJAM')
    nomor_identitas = models.CharField(max_length=30, unique=True)
    unit_prodi = models.CharField(max_length=100)
    no_telepon = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f'{self.user.username} ({self.role})'


class KategoriAset(models.Model):
    kode = models.CharField(max_length=10, unique=True)
    nama = models.CharField(max_length=100, unique=True)
    deskripsi = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Kategori Aset'
        ordering = ['kode']

    def __str__(self):
        return f'{self.kode} - {self.nama}'


class LokasiLab(models.Model):
    kode_ruang = models.CharField(max_length=20, unique=True)
    nama_ruang = models.CharField(max_length=100)
    gedung = models.CharField(max_length=100)
    penanggung_jawab = models.CharField(max_length=100)
    kapasitas = models.PositiveIntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Lokasi Lab'
        ordering = ['kode_ruang']

    def __str__(self):
        return f'{self.kode_ruang} - {self.nama_ruang}'


class Aset(models.Model):
    KONDISI_CHOICES = [
        ('BAIK', 'Baik'),
        ('RUSAK_RINGAN', 'Rusak Ringan'),
        ('RUSAK_BERAT', 'Rusak Berat'),
        ('PERBAIKAN', 'Perbaikan'),
    ]
    STATUS_CHOICES = [
        ('TERSEDIA', 'Tersedia'),
        ('DIPINJAM', 'Dipinjam'),
        ('PEMELIHARAAN', 'Pemeliharaan'),
        ('DIHAPUSKAN', 'Dihapuskan'),
    ]

    kode_aset = models.CharField(max_length=30, unique=True, blank=True)
    nama_aset = models.CharField(max_length=150)
    kategori = models.ForeignKey(KategoriAset, on_delete=models.PROTECT, related_name='asets')
    lokasi = models.ForeignKey(LokasiLab, on_delete=models.PROTECT, related_name='asets')
    merk_tipe = models.CharField(max_length=100)
    nomor_seri = models.CharField(max_length=100, blank=True)
    spesifikasi = models.TextField(blank=True)
    tanggal_perolehan = models.DateField()
    harga_perolehan = models.DecimalField(max_digits=14, decimal_places=2)
    nilai_residu = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    umur_ekonomis_tahun = models.PositiveIntegerField(default=5)
    kondisi = models.CharField(max_length=20, choices=KONDISI_CHOICES, default='BAIK')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='TERSEDIA')
    foto = models.ImageField(upload_to='aset_foto/', blank=True, null=True)
    qr_code = models.ImageField(upload_to='qrcodes/', blank=True, null=True)
    catatan = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Aset'
        ordering = ['kode_aset']

    def save(self, *args, **kwargs):
        if not self.kode_aset and self.kategori_id and self.tanggal_perolehan:
            prefix = f'LAB-{self.kategori.kode}-{self.tanggal_perolehan.year}-'
            last = Aset.objects.filter(kode_aset__startswith=prefix).order_by('-kode_aset').first()
            seq = int(last.kode_aset.split('-')[-1]) + 1 if last else 1
            self.kode_aset = f'{prefix}{seq:03d}'
        super().save(*args, **kwargs)

    @property
    def usia_tahun(self):
        return hitung_penyusutan(self)['usia_tahun']

    @property
    def penyusutan_per_tahun(self):
        return hitung_penyusutan(self)['penyusutan_per_tahun']

    @property
    def akumulasi_penyusutan(self):
        return hitung_penyusutan(self)['akumulasi_penyusutan']

    @property
    def nilai_buku(self):
        return hitung_penyusutan(self)['nilai_buku']

    @property
    def persentase_susut(self):
        return hitung_penyusutan(self)['persentase_susut']

    def __str__(self):
        return f'{self.kode_aset} - {self.nama_aset}'


class Peminjaman(models.Model):
    STATUS_CHOICES = [
        ('MENUNGGU', 'Menunggu'),
        ('DISETUJUI', 'Disetujui'),
        ('DITOLAK', 'Ditolak'),
        ('DIKEMBALIKAN', 'Dikembalikan'),
    ]
    KONDISI_KEMBALI_CHOICES = [
        ('BAIK', 'Baik'),
        ('RUSAK_RINGAN', 'Rusak Ringan'),
        ('RUSAK_BERAT', 'Rusak Berat'),
    ]

    kode_peminjaman = models.CharField(max_length=30, unique=True)
    aset = models.ForeignKey(Aset, on_delete=models.PROTECT, related_name='peminjamans')
    peminjam = models.ForeignKey(User, on_delete=models.PROTECT, related_name='peminjaman_user')
    disetujui_oleh = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='peminjaman_approved'
    )
    tanggal_pinjam = models.DateField()
    tanggal_rencana_kembali = models.DateField()
    tanggal_kembali_aktual = models.DateField(null=True, blank=True)
    keperluan = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='MENUNGGU')
    kondisi_saat_kembali = models.CharField(max_length=20, choices=KONDISI_KEMBALI_CHOICES, blank=True)
    catatan_admin = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Peminjaman'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.kode_peminjaman} - {self.aset.kode_aset}'


class LaporanKerusakan(models.Model):
    KEPARAHAN_CHOICES = [
        ('RINGAN', 'Ringan'),
        ('SEDANG', 'Sedang'),
        ('BERAT', 'Berat'),
    ]
    STATUS_CHOICES = [
        ('DILAPORKAN', 'Dilaporkan'),
        ('DIPROSES', 'Diproses'),
        ('SELESAI', 'Selesai'),
        ('TIDAK_DAPAT_DIPERBAIKI', 'Tidak Dapat Diperbaiki'),
    ]

    kode_laporan = models.CharField(max_length=30, unique=True)
    aset = models.ForeignKey(Aset, on_delete=models.PROTECT, related_name='kerusakans')
    pelapor = models.ForeignKey(User, on_delete=models.PROTECT, related_name='laporan_kerusakan')
    tanggal_lapor = models.DateTimeField(auto_now_add=True)
    judul_kerusakan = models.CharField(max_length=150)
    deskripsi = models.TextField()
    tingkat_keparahan = models.CharField(max_length=20, choices=KEPARAHAN_CHOICES, default='RINGAN')
    foto_bukti = models.ImageField(upload_to='kerusakan_foto/', blank=True, null=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='DILAPORKAN')
    catatan_penanganan = models.TextField(blank=True)
    ditangani_oleh = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='penanganan_kerusakan'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Laporan Kerusakan'
        ordering = ['-tanggal_lapor']

    def __str__(self):
        return f'{self.kode_laporan} - {self.judul_kerusakan}'


class JadwalPemeliharaan(models.Model):
    JENIS_CHOICES = [
        ('PREVENTIF', 'Preventif'),
        ('KOREKTIF', 'Korektif'),
        ('KALIBRASI', 'Kalibrasi'),
    ]
    STATUS_CHOICES = [
        ('TERJADWAL', 'Terjadwal'),
        ('BERLANGSUNG', 'Berlangsung'),
        ('SELESAI', 'Selesai'),
        ('DIBATALKAN', 'Dibatalkan'),
    ]

    kode_jadwal = models.CharField(max_length=30, unique=True)
    aset = models.ForeignKey(Aset, on_delete=models.PROTECT, related_name='pemeliharaans')
    laporan_kerusakan = models.ForeignKey(
        LaporanKerusakan, on_delete=models.SET_NULL, null=True, blank=True, related_name='pemeliharaans'
    )
    jenis = models.CharField(max_length=20, choices=JENIS_CHOICES, default='PREVENTIF')
    tanggal_jadwal = models.DateField()
    tanggal_selesai = models.DateField(null=True, blank=True)
    teknisi = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='tugas_pemeliharaan'
    )
    deskripsi_kegiatan = models.TextField()
    biaya = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='TERJADWAL')
    catatan_hasil = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Jadwal Pemeliharaan'
        ordering = ['tanggal_jadwal']

    def __str__(self):
        return f'{self.kode_jadwal} - {self.aset.kode_aset}'
