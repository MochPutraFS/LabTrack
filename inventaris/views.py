from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .decorators import role_required
from .forms import AsetForm, KategoriAsetForm, LokasiLabForm
from .models import Aset, JadwalPemeliharaan, KategoriAset, LaporanKerusakan, LokasiLab, Peminjaman
from .services import generate_aset_qr

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

    kategori_qs = KategoriAset.objects.annotate(jumlah=Count('asets')).order_by('nama')
    kategori_chart_data = {
        'labels': [k.nama for k in kategori_qs],
        'values': [k.jumlah for k in kategori_qs],
    }

    peminjaman_terbaru = Peminjaman.objects.select_related('aset', 'peminjam').order_by('-created_at')[:5]

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


# ---------------------------------------------------------------------------
# Master Kategori Barang (ADMIN)
# ---------------------------------------------------------------------------

@role_required('ADMIN')
def kategori_list(request):
    kategoris = KategoriAset.objects.annotate(jumlah_aset=Count('asets')).order_by('kode')
    return render(request, 'inventaris/master/kategori_list.html', {'kategoris': kategoris})


@role_required('ADMIN')
def kategori_create(request):
    form = KategoriAsetForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        messages.success(request, f'Kategori "{obj.nama}" berhasil ditambahkan.')
        return redirect('kategori_list')
    return render(request, 'inventaris/master/form.html', {
        'form': form,
        'page_title': 'Tambah Kategori Barang',
        'cancel_url': 'kategori_list',
    })


@role_required('ADMIN')
def kategori_edit(request, pk):
    obj = get_object_or_404(KategoriAset, pk=pk)
    form = KategoriAsetForm(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        messages.success(request, f'Kategori "{obj.nama}" berhasil diperbarui.')
        return redirect('kategori_list')
    return render(request, 'inventaris/master/form.html', {
        'form': form,
        'page_title': f'Edit Kategori: {obj.kode}',
        'cancel_url': 'kategori_list',
    })


@role_required('ADMIN')
def kategori_delete(request, pk):
    obj = get_object_or_404(KategoriAset, pk=pk)
    if request.method == 'POST':
        try:
            nama = obj.nama
            obj.delete()
            messages.success(request, f'Kategori "{nama}" berhasil dihapus.')
        except ProtectedError:
            messages.error(request, f'Kategori "{obj.nama}" tidak dapat dihapus karena masih digunakan oleh data aset.')
        return redirect('kategori_list')
    return render(request, 'inventaris/confirm_delete.html', {
        'page_title': 'Hapus Kategori Barang',
        'object_name': f'{obj.kode} - {obj.nama}',
        'cancel_url': 'kategori_list',
    })


# ---------------------------------------------------------------------------
# Master Lokasi Laboratorium (ADMIN)
# ---------------------------------------------------------------------------

@role_required('ADMIN')
def lokasi_list(request):
    lokasis = LokasiLab.objects.annotate(jumlah_aset=Count('asets')).order_by('kode_ruang')
    return render(request, 'inventaris/master/lokasi_list.html', {'lokasis': lokasis})


@role_required('ADMIN')
def lokasi_create(request):
    form = LokasiLabForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        messages.success(request, f'Lokasi "{obj.nama_ruang}" berhasil ditambahkan.')
        return redirect('lokasi_list')
    return render(request, 'inventaris/master/form.html', {
        'form': form,
        'page_title': 'Tambah Lokasi Laboratorium',
        'cancel_url': 'lokasi_list',
    })


@role_required('ADMIN')
def lokasi_edit(request, pk):
    obj = get_object_or_404(LokasiLab, pk=pk)
    form = LokasiLabForm(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        messages.success(request, f'Lokasi "{obj.nama_ruang}" berhasil diperbarui.')
        return redirect('lokasi_list')
    return render(request, 'inventaris/master/form.html', {
        'form': form,
        'page_title': f'Edit Lokasi: {obj.kode_ruang}',
        'cancel_url': 'lokasi_list',
    })


@role_required('ADMIN')
def lokasi_delete(request, pk):
    obj = get_object_or_404(LokasiLab, pk=pk)
    if request.method == 'POST':
        try:
            nama = obj.nama_ruang
            obj.delete()
            messages.success(request, f'Lokasi "{nama}" berhasil dihapus.')
        except ProtectedError:
            messages.error(request, f'Lokasi "{obj.nama_ruang}" tidak dapat dihapus karena masih digunakan oleh data aset.')
        return redirect('lokasi_list')
    return render(request, 'inventaris/confirm_delete.html', {
        'page_title': 'Hapus Lokasi Laboratorium',
        'object_name': f'{obj.kode_ruang} - {obj.nama_ruang}',
        'cancel_url': 'lokasi_list',
    })


# ---------------------------------------------------------------------------
# Data Aset & QR Code
# ---------------------------------------------------------------------------

@login_required
def aset_list(request):
    qs = Aset.objects.select_related('kategori', 'lokasi').order_by('kode_aset')

    q = request.GET.get('q', '').strip()
    kategori_id = request.GET.get('kategori', '').strip()
    lokasi_id = request.GET.get('lokasi', '').strip()
    kondisi = request.GET.get('kondisi', '').strip()
    status = request.GET.get('status', '').strip()

    if q:
        qs = qs.filter(
            Q(kode_aset__icontains=q) | Q(nama_aset__icontains=q) | Q(merk_tipe__icontains=q)
        )
    if kategori_id:
        qs = qs.filter(kategori_id=kategori_id)
    if lokasi_id:
        qs = qs.filter(lokasi_id=lokasi_id)
    if kondisi:
        qs = qs.filter(kondisi=kondisi)
    if status:
        qs = qs.filter(status=status)

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    query_params = request.GET.copy()
    query_params.pop('page', None)

    context = {
        'page_obj': page_obj,
        'kategoris': KategoriAset.objects.order_by('nama'),
        'lokasis': LokasiLab.objects.order_by('nama_ruang'),
        'kondisi_choices': Aset.KONDISI_CHOICES,
        'status_choices': Aset.STATUS_CHOICES,
        'filters': {
            'q': q,
            'kategori': kategori_id,
            'lokasi': lokasi_id,
            'kondisi': kondisi,
            'status': status,
        },
        'query_string': query_params.urlencode(),
    }
    return render(request, 'inventaris/aset/list.html', context)


@role_required('ADMIN')
def aset_create(request):
    form = AsetForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        aset = form.save()
        generate_aset_qr(aset, request.build_absolute_uri('/').rstrip('/'))
        messages.success(request, f'Aset "{aset.kode_aset} - {aset.nama_aset}" berhasil ditambahkan beserta QR Code.')
        return redirect('aset_detail', pk=aset.pk)
    return render(request, 'inventaris/aset/form.html', {
        'form': form,
        'page_title': 'Tambah Data Aset',
    })


@login_required
def aset_detail(request, pk):
    aset = get_object_or_404(Aset.objects.select_related('kategori', 'lokasi'), pk=pk)
    context = {
        'aset': aset,
        'riwayat_peminjaman': aset.peminjamans.select_related('peminjam').order_by('-created_at')[:5],
        'riwayat_kerusakan': aset.kerusakans.select_related('pelapor').order_by('-tanggal_lapor')[:5],
        'riwayat_pemeliharaan': aset.pemeliharaans.select_related('teknisi').order_by('-tanggal_jadwal')[:5],
    }
    return render(request, 'inventaris/aset/detail.html', context)


@role_required('ADMIN')
def aset_edit(request, pk):
    aset = get_object_or_404(Aset, pk=pk)
    form = AsetForm(request.POST or None, request.FILES or None, instance=aset)
    if request.method == 'POST' and form.is_valid():
        aset = form.save()
        generate_aset_qr(aset, request.build_absolute_uri('/').rstrip('/'))
        messages.success(request, f'Data aset "{aset.kode_aset}" berhasil diperbarui.')
        return redirect('aset_detail', pk=aset.pk)
    return render(request, 'inventaris/aset/form.html', {
        'form': form,
        'aset': aset,
        'page_title': f'Edit Aset: {aset.kode_aset}',
    })


@role_required('ADMIN')
def aset_delete(request, pk):
    aset = get_object_or_404(Aset, pk=pk)
    if request.method == 'POST':
        try:
            kode = aset.kode_aset
            aset.delete()
            messages.success(request, f'Aset "{kode}" berhasil dihapus.')
            return redirect('aset_list')
        except ProtectedError:
            messages.error(request, f'Aset "{aset.kode_aset}" tidak dapat dihapus karena masih memiliki riwayat transaksi.')
            return redirect('aset_detail', pk=aset.pk)
    return render(request, 'inventaris/confirm_delete.html', {
        'page_title': 'Hapus Data Aset',
        'object_name': f'{aset.kode_aset} - {aset.nama_aset}',
        'cancel_url': 'aset_list',
    })


@login_required
def aset_scan(request, kode_aset):
    aset = get_object_or_404(Aset.objects.select_related('kategori', 'lokasi'), kode_aset=kode_aset)
    return render(request, 'inventaris/aset/scan.html', {'aset': aset})


@login_required
def aset_print_qr(request, pk):
    aset = get_object_or_404(Aset.objects.select_related('lokasi'), pk=pk)
    if not aset.qr_code:
        generate_aset_qr(aset, request.build_absolute_uri('/').rstrip('/'))
    return render(request, 'inventaris/aset/print_qr.html', {'asets': [aset], 'single_aset': aset})


@login_required
def aset_print_qr_massal(request):
    ids_param = request.GET.get('ids', '').strip()
    qs = Aset.objects.select_related('lokasi').order_by('kode_aset')
    if ids_param:
        valid_ids = [int(i) for i in ids_param.split(',') if i.strip().isdigit()]
        if valid_ids:
            qs = qs.filter(pk__in=valid_ids)
    asets = list(qs)
    base_url = request.build_absolute_uri('/').rstrip('/')
    for aset in asets:
        if not aset.qr_code:
            generate_aset_qr(aset, base_url)
    return render(request, 'inventaris/aset/print_qr.html', {'asets': asets, 'single_aset': None})


# ---------------------------------------------------------------------------
# Placeholder routes untuk modul S05-S07
# ---------------------------------------------------------------------------

@login_required
def module_placeholder(request, title=''):
    return render(request, 'inventaris/coming_soon.html', {'module_title': title})
