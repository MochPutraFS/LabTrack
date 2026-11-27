from datetime import date
from decimal import Decimal
from io import BytesIO

import qrcode
from django.core.files.base import ContentFile


def hitung_penyusutan(aset, tanggal_acuan=None):
    """Hitung metrik penyusutan garis lurus untuk instance Aset."""
    hari_ini = tanggal_acuan or date.today()
    usia_tahun = max(0.0, (hari_ini - aset.tanggal_perolehan).days / 365.25)

    harga = aset.harga_perolehan or Decimal('0')
    residu = aset.nilai_residu or Decimal('0')
    selisih = max(Decimal('0'), harga - residu)

    if aset.umur_ekonomis_tahun > 0:
        penyusutan_per_tahun = selisih / Decimal(aset.umur_ekonomis_tahun)
    else:
        penyusutan_per_tahun = Decimal('0')

    akumulasi = min(selisih, penyusutan_per_tahun * Decimal(str(usia_tahun)))
    nilai_buku = max(residu, harga - akumulasi)
    persentase_susut = (akumulasi / harga * Decimal('100')) if harga > 0 else Decimal('0')

    return {
        'usia_tahun': round(usia_tahun, 2),
        'penyusutan_per_tahun': penyusutan_per_tahun.quantize(Decimal('0.01')),
        'akumulasi_penyusutan': akumulasi.quantize(Decimal('0.01')),
        'nilai_buku': nilai_buku.quantize(Decimal('0.01')),
        'persentase_susut': persentase_susut.quantize(Decimal('0.01')),
    }


def generate_aset_qr(aset, base_url=''):
    """Generate PNG QR Code untuk aset dan simpan ke field qr_code."""
    target = f'{base_url.rstrip("/")}/aset/scan/{aset.kode_aset}/' if base_url else aset.kode_aset
    img = qrcode.make(target)
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    filename = f'{aset.kode_aset}.png'
    aset.qr_code.save(filename, ContentFile(buffer.getvalue()), save=True)
