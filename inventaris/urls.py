from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    # Placeholder routes untuk modul S04-S07 agar sidebar aman dari NoReverseMatch
    path('aset/', views.module_placeholder, {'title': 'Data Aset'}, name='aset_list'),
    path('peminjaman/', views.module_placeholder, {'title': 'Peminjaman'}, name='peminjaman_list'),
    path('kerusakan/', views.module_placeholder, {'title': 'Laporan Kerusakan'}, name='kerusakan_list'),
    path('pemeliharaan/', views.module_placeholder, {'title': 'Jadwal Pemeliharaan'}, name='pemeliharaan_list'),
    path(
        'laporan/kondisi-penyusutan/',
        views.module_placeholder,
        {'title': 'Laporan & Penyusutan'},
        name='laporan_penyusutan',
    ),
    path('kategori/', views.admin_module_placeholder, {'title': 'Kategori Barang'}, name='kategori_list'),
    path('lokasi/', views.admin_module_placeholder, {'title': 'Lokasi Laboratorium'}, name='lokasi_list'),
]
