from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .decorators import role_required
from .models import Aset, JadwalPemeliharaan, KategoriAset, LaporanKerusakan, Peminjaman

User = get_user_model()


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    next_url = request.POST.get('next') or request.GET.get('next', '')
    context = {
        'username': '',
        'next': next_url,
        'error_message': '',
        'field_errors': {},
    }

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        context['username'] = username

        field_errors = {}
        if not username:
            field_errors['username'] = 'Username wajib diisi.'
        if not password:
            field_errors['password'] = 'Password wajib diisi.'

        if field_errors:
            context['field_errors'] = field_errors
            context['error_message'] = 'Mohon lengkapi username dan password Anda.'
            return render(request, 'inventaris/auth/login.html', context)

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect('dashboard')

        existing = User.objects.filter(username=username).first()
        if existing and not existing.is_active and existing.check_password(password):
            context['error_message'] = 'Akun Anda saat ini tidak aktif. Hubungi admin laboratorium.'
        else:
            context['error_message'] = 'Username atau password salah. Silakan periksa kembali kredensial Anda.'

    return render(request, 'inventaris/auth/login.html', context)


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, 'Anda telah berhasil keluar dari sistem.')
    return redirect('login')


@login_required
def dashboard(request):
    today = timezone.localdate()
    batas_jadwal = today + timedelta(days=30)

    asets = list(Aset.objects.select_related('kategori', 'lokasi'))
    total_aset = len(asets)
    total_nilai_buku = sum((a.nilai_buku for a in asets), 0)
    aset_tersedia = sum(1 for a in asets if a.status == 'TERSEDIA')
    aset_dipinjam = sum(1 for a in asets if a.status == 'DIPINJAM')

    kerusakan_aktif = LaporanKerusakan.objects.filter(
        status__in=['DILAPORKAN', 'DIPROSES']
    ).count()
    pemeliharaan_mendatang = JadwalPemeliharaan.objects.filter(
        status__in=['TERJADWAL', 'BERLANGSUNG'],
        tanggal_jadwal__gte=today,
        tanggal_jadwal__lte=batas_jadwal,
    ).count()

    # Data Doughnut Chart: Distribusi Kondisi Aset
    kondisi_counts = {key: 0 for key, _ in Aset.KONDISI_CHOICES}
    for aset in asets:
        if aset.kondisi in kondisi_counts:
            kondisi_counts[aset.kondisi] += 1

    kondisi_chart_data = {
        'labels': ['Baik', 'Rusak Ringan', 'Rusak Berat', 'Dalam Perbaikan'],
        'values': [
            kondisi_counts['BAIK'],
            kondisi_counts['RUSAK_RINGAN'],
            kondisi_counts['RUSAK_BERAT'],
            kondisi_counts['PERBAIKAN'],
        ],
    }

    # Data Bar Chart: Jumlah Aset per Kategori
    kategori_qs = KategoriAset.objects.annotate(jumlah=Count('asets')).order_by('nama')
    kategori_chart_data = {
        'labels': [k.nama for k in kategori_qs],
        'values': [k.jumlah for k in kategori_qs],
    }

    # Panel Operasional 1: 5 Peminjaman Terbaru
    peminjaman_terbaru = Peminjaman.objects.select_related('aset', 'peminjam').order_by('-created_at')[:5]

    # Panel Operasional 2: 5 Jadwal Pemeliharaan Aktif Terdekat
    jadwal_aktif = JadwalPemeliharaan.objects.filter(
        status__in=['TERJADWAL', 'BERLANGSUNG']
    ).select_related('aset').order_by('tanggal_jadwal')[:5]

    jadwal_terdekat = []
    for jadwal in jadwal_aktif:
        selisih = (jadwal.tanggal_jadwal - today).days
        jadwal_terdekat.append({
            'obj': jadwal,
            'selisih_hari': selisih,
            'abs_hari': abs(selisih),
        })

    context = {
        'total_aset': total_aset,
        'total_nilai_buku': total_nilai_buku,
        'aset_tersedia': aset_tersedia,
        'aset_dipinjam': aset_dipinjam,
        'kerusakan_aktif': kerusakan_aktif,
        'pemeliharaan_mendatang': pemeliharaan_mendatang,
        'kondisi_chart_data': kondisi_chart_data,
        'kategori_chart_data': kategori_chart_data,
        'peminjaman_terbaru': peminjaman_terbaru,
        'jadwal_terdekat': jadwal_terdekat,
    }
    return render(request, 'inventaris/dashboard/index.html', context)


@login_required
def module_placeholder(request, title=''):
    return render(request, 'inventaris/coming_soon.html', {'module_title': title})


@role_required('ADMIN')
def admin_module_placeholder(request, title=''):
    return render(request, 'inventaris/coming_soon.html', {'module_title': title})
