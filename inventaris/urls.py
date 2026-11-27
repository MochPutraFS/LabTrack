from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Master Kategori Barang (ADMIN)
    path('kategori/', views.kategori_list, name='kategori_list'),
    path('kategori/tambah/', views.kategori_create, name='kategori_create'),
    path('kategori/<int:pk>/edit/', views.kategori_edit, name='kategori_edit'),
    path('kategori/<int:pk>/hapus/', views.kategori_delete, name='kategori_delete'),

    # Master Lokasi Laboratorium (ADMIN)
    path('lokasi/', views.lokasi_list, name='lokasi_list'),
    path('lokasi/tambah/', views.lokasi_create, name='lokasi_create'),
    path('lokasi/<int:pk>/edit/', views.lokasi_edit, name='lokasi_edit'),
    path('lokasi/<int:pk>/hapus/', views.lokasi_delete, name='lokasi_delete'),

    # Data Aset & QR Code
    path('aset/', views.aset_list, name='aset_list'),
    path('aset/tambah/', views.aset_create, name='aset_create'),
    path('aset/cetak-qr-massal/', views.aset_print_qr_massal, name='aset_print_qr_massal'),
    path('aset/scan/<str:kode_aset>/', views.aset_scan, name='aset_scan'),
    path('aset/<int:pk>/', views.aset_detail, name='aset_detail'),
    path('aset/<int:pk>/edit/', views.aset_edit, name='aset_edit'),
    path('aset/<int:pk>/hapus/', views.aset_delete, name='aset_delete'),
    path('aset/<int:pk>/cetak-qr/', views.aset_print_qr, name='aset_print_qr'),

    # Peminjaman & Pengembalian Aset
    path('peminjaman/', views.peminjaman_list, name='peminjaman_list'),
    path('peminjaman/ajukan/', views.peminjaman_ajukan, name='peminjaman_ajukan'),
    path('peminjaman/<int:pk>/setujui/', views.peminjaman_setujui, name='peminjaman_setujui'),
    path('peminjaman/<int:pk>/tolak/', views.peminjaman_tolak, name='peminjaman_tolak'),
    path('peminjaman/<int:pk>/kembalikan/', views.peminjaman_kembalikan, name='peminjaman_kembalikan'),

    # Pencatatan Kerusakan Aset
    path('kerusakan/', views.kerusakan_list, name='kerusakan_list'),
    path('kerusakan/lapor/', views.kerusakan_lapor, name='kerusakan_lapor'),
    path('kerusakan/<int:pk>/', views.kerusakan_detail, name='kerusakan_detail'),

    # Jadwal Pemeliharaan Aset
    path('pemeliharaan/', views.pemeliharaan_list, name='pemeliharaan_list'),
    path('pemeliharaan/tambah/', views.pemeliharaan_create, name='pemeliharaan_create'),
    path('pemeliharaan/<int:pk>/edit/', views.pemeliharaan_edit, name='pemeliharaan_edit'),
    path('pemeliharaan/<int:pk>/mulai/', views.pemeliharaan_mulai, name='pemeliharaan_mulai'),
    path('pemeliharaan/<int:pk>/selesai/', views.pemeliharaan_selesai, name='pemeliharaan_selesai'),

    # Placeholder routes untuk modul S07
    path(
        'laporan/kondisi-penyusutan/',
        views.module_placeholder,
        {'title': 'Laporan & Penyusutan'},
        name='laporan_penyusutan',
    ),
]
