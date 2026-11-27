from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

KONDISI_BADGE_MAP = {
    'BAIK': 'bg-emerald-50 text-emerald-800 border border-emerald-200',
    'RUSAK_RINGAN': 'bg-amber-50 text-amber-800 border border-amber-200',
    'RUSAK_BERAT': 'bg-red-50 text-red-800 border border-red-200',
    'PERBAIKAN': 'bg-stone-100 text-stone-800 border border-stone-300',
}

STATUS_BADGE_MAP = {
    'TERSEDIA': 'bg-emerald-50 text-emerald-800 border border-emerald-200',
    'DISETUJUI': 'bg-emerald-50 text-emerald-800 border border-emerald-200',
    'SELESAI': 'bg-emerald-50 text-emerald-800 border border-emerald-200',
    'DIKEMBALIKAN': 'bg-emerald-50 text-emerald-800 border border-emerald-200',
    'MENUNGGU': 'bg-amber-50 text-amber-800 border border-amber-200',
    'DIPINJAM': 'bg-amber-50 text-amber-800 border border-amber-200',
    'TERJADWAL': 'bg-amber-50 text-amber-800 border border-amber-200',
    'BERLANGSUNG': 'bg-amber-50 text-amber-800 border border-amber-200',
    'DIPROSES': 'bg-amber-50 text-amber-800 border border-amber-200',
    'PEMELIHARAAN': 'bg-amber-50 text-amber-800 border border-amber-200',
    'DILAPORKAN': 'bg-amber-50 text-amber-800 border border-amber-200',
    'DITOLAK': 'bg-red-50 text-red-800 border border-red-200',
    'DIBATALKAN': 'bg-red-50 text-red-800 border border-red-200',
    'TERLAMBAT': 'bg-red-50 text-red-800 border border-red-200',
    'BERAT': 'bg-red-50 text-red-800 border border-red-200',
    'TIDAK_DAPAT_DIPERBAIKI': 'bg-red-50 text-red-800 border border-red-200',
    'DIHAPUSKAN': 'bg-red-50 text-red-800 border border-red-200',
}

DEFAULT_BADGE = 'bg-stone-100 text-stone-700 border border-stone-300'


@register.filter
def rupiah(value):
    """Format angka atau Decimal menjadi format Rupiah Indonesia (mis. Rp 12.500.000)."""
    if value is None or value == '':
        return 'Rp 0'
    try:
        amount = int(round(Decimal(str(value))))
    except (InvalidOperation, ValueError, TypeError):
        return 'Rp 0'

    prefix = '-Rp ' if amount < 0 else 'Rp '
    formatted = f'{abs(amount):,}'.replace(',', '.')
    return f'{prefix}{formatted}'


@register.filter
def badge_kondisi(value):
    return KONDISI_BADGE_MAP.get(value, DEFAULT_BADGE)


@register.filter
def badge_status(value):
    return STATUS_BADGE_MAP.get(value, DEFAULT_BADGE)
