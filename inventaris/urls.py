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

    # Placeholder routes untuk modul S05-S07
    path('peminjaman/', views.module_placeholder, {'title': 'Peminjaman'}, name='peminjaman_list'),
    path('kerusakan/', views.module_placeholder, {'title': 'Laporan Kerusakan'}, name='kerusakan_list'),
    path('pemeliharaan/', views.module_placeholder, {'title': 'Jadwal Pemeliharaan'}, name='pemeliharaan_list'),
    path(
        'laporan/kondisi-penyusutan/',
        views.module_placeholder,
        {'title': 'Laporan & Penyusutan'},
        name='laporan_penyusutan',
    ),
]
