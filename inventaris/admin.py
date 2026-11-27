from django.contrib import admin

from .models import (
    Aset,
    JadwalPemeliharaan,
    KategoriAset,
    LaporanKerusakan,
    LokasiLab,
    Peminjaman,
    UserProfile,
)

admin.site.register(UserProfile)
admin.site.register(KategoriAset)
admin.site.register(LokasiLab)
admin.site.register(Aset)
admin.site.register(Peminjaman)
admin.site.register(LaporanKerusakan)
admin.site.register(JadwalPemeliharaan)
