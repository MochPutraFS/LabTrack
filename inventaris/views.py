import csv
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, ProtectedError, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .decorators import role_required
from .forms import (
    AsetForm,
    JadwalPemeliharaanForm,
    KategoriAsetForm,
    LaporanKerusakanForm,
    LokasiLabForm,
    PeminjamanForm,
    PenangananKerusakanForm,
    PengembalianForm,
    SelesaiPemeliharaanForm,
)
from .models import Aset, JadwalPemeliharaan, KategoriAset, LaporanKerusakan, LokasiLab, Peminjaman
from .services import generate_aset_qr, hitung_penyusutan

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
# Peminjaman & Pengembalian Aset
# ---------------------------------------------------------------------------

def _generate_kode_peminjaman():
    today = timezone.localdate()
    prefix = f'PJM-{today:%Y%m}-'
    last = Peminjaman.objects.filter(kode_peminjaman__startswith=prefix).order_by('-kode_peminjaman').first()
    seq = int(last.kode_peminjaman.split('-')[-1]) + 1 if last else 1
    return f'{prefix}{seq:03d}'


@login_required
def peminjaman_list(request):
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else ('ADMIN' if request.user.is_superuser else 'PEMINJAM')

    qs = Peminjaman.objects.select_related('aset', 'peminjam', 'disetujui_oleh').order_by('-created_at')
    if role not in ('ADMIN', 'TEKNISI'):
        qs = qs.filter(peminjam=request.user)

    status_filter = request.GET.get('status', '').strip()
    if status_filter in dict(Peminjaman.STATUS_CHOICES):
        qs = qs.filter(status=status_filter)

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'inventaris/peminjaman/list.html', {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'status_choices': Peminjaman.STATUS_CHOICES,
        'today': timezone.localdate(),
    })


@login_required
def peminjaman_ajukan(request):
    initial = {}
    aset_id = request.GET.get('aset')
    if aset_id and aset_id.isdigit():
        aset_obj = Aset.objects.filter(pk=int(aset_id), status='TERSEDIA').exclude(kondisi='RUSAK_BERAT').first()
        if aset_obj:
            initial['aset'] = aset_obj.pk

    form = PeminjamanForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        peminjaman = form.save(commit=False)
        peminjaman.peminjam = request.user
        peminjaman.status = 'MENUNGGU'
        peminjaman.kode_peminjaman = _generate_kode_peminjaman()
        peminjaman.save()
        messages.success(request, f'Pengajuan peminjaman {peminjaman.kode_peminjaman} berhasil dikirim dan menunggu persetujuan.')
        return redirect('peminjaman_list')

    return render(request, 'inventaris/peminjaman/ajukan.html', {'form': form})


@require_POST
@role_required('ADMIN')
def peminjaman_setujui(request, pk):
    with transaction.atomic():
        peminjaman = get_object_or_404(Peminjaman.objects.select_for_update(), pk=pk)
        aset = Aset.objects.select_for_update().get(pk=peminjaman.aset_id)

        if peminjaman.status != 'MENUNGGU':
            messages.error(request, f'Peminjaman {peminjaman.kode_peminjaman} tidak berada dalam status menunggu.')
            return redirect('peminjaman_list')

        if aset.status != 'TERSEDIA' or aset.kondisi == 'RUSAK_BERAT':
            messages.error(
                request,
                f'Aset {aset.kode_aset} sedang tidak tersedia (status: {aset.get_status_display()}).',
            )
            return redirect('peminjaman_list')

        peminjaman.status = 'DISETUJUI'
        peminjaman.disetujui_oleh = request.user
        peminjaman.save()

        aset.status = 'DIPINJAM'
        aset.save(update_fields=['status', 'updated_at'])

    messages.success(request, f'Peminjaman {peminjaman.kode_peminjaman} disetujui. Status aset berubah menjadi Dipinjam.')
    return redirect('peminjaman_list')


@role_required('ADMIN')
def peminjaman_tolak(request, pk):
    peminjaman = get_object_or_404(Peminjaman.objects.select_related('aset', 'peminjam'), pk=pk)
    if peminjaman.status != 'MENUNGGU':
        messages.error(request, f'Peminjaman {peminjaman.kode_peminjaman} tidak dapat ditolak pada status saat ini.')
        return redirect('peminjaman_list')

    if request.method == 'POST':
        alasan = request.POST.get('catatan_admin', '').strip()
        with transaction.atomic():
            locked = Peminjaman.objects.select_for_update().get(pk=pk)
            if locked.status == 'MENUNGGU':
                locked.status = 'DITOLAK'
                locked.catatan_admin = alasan
                locked.disetujui_oleh = request.user
                locked.save()
        messages.success(request, f'Peminjaman {peminjaman.kode_peminjaman} telah ditolak.')
        return redirect('peminjaman_list')

    return render(request, 'inventaris/peminjaman/tolak.html', {'peminjaman': peminjaman})


@role_required('ADMIN')
def peminjaman_kembalikan(request, pk):
    peminjaman = get_object_or_404(Peminjaman.objects.select_related('aset', 'peminjam'), pk=pk)
    if peminjaman.status != 'DISETUJUI':
        messages.error(request, f'Peminjaman {peminjaman.kode_peminjaman} belum berstatus Disetujui.')
        return redirect('peminjaman_list')

    form = PengembalianForm(request.POST or None, instance=peminjaman)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            locked = Peminjaman.objects.select_for_update().get(pk=pk)
            aset = Aset.objects.select_for_update().get(pk=locked.aset_id)
            if locked.status != 'DISETUJUI':
                messages.error(request, 'Status peminjaman sudah berubah.')
                return redirect('peminjaman_list')

            locked.tanggal_kembali_aktual = form.cleaned_data['tanggal_kembali_aktual']
            locked.kondisi_saat_kembali = form.cleaned_data['kondisi_saat_kembali']
            locked.catatan_admin = form.cleaned_data['catatan_admin']
            locked.status = 'DIKEMBALIKAN'
            locked.save()

            aset.kondisi = locked.kondisi_saat_kembali
            aset.status = 'PEMELIHARAAN' if locked.kondisi_saat_kembali == 'RUSAK_BERAT' else 'TERSEDIA'
            aset.save(update_fields=['kondisi', 'status', 'updated_at'])

        messages.success(
            request,
            f'Pengembalian {peminjaman.kode_peminjaman} berhasil dicatat. Status aset kini {aset.get_status_display()}.',
        )
        return redirect('peminjaman_list')

    return render(request, 'inventaris/peminjaman/kembalikan.html', {
        'peminjaman': peminjaman,
        'form': form,
    })


# ---------------------------------------------------------------------------
# Pencatatan Kerusakan Aset
# ---------------------------------------------------------------------------

def _generate_kode_laporan():
    today = timezone.localdate()
    prefix = f'RSK-{today:%Y%m}-'
    last = LaporanKerusakan.objects.filter(kode_laporan__startswith=prefix).order_by('-kode_laporan').first()
    seq = int(last.kode_laporan.split('-')[-1]) + 1 if last else 1
    return f'{prefix}{seq:03d}'


def _generate_kode_jadwal():
    today = timezone.localdate()
    prefix = f'MNT-{today:%Y%m}-'
    last = JadwalPemeliharaan.objects.filter(kode_jadwal__startswith=prefix).order_by('-kode_jadwal').first()
    seq = int(last.kode_jadwal.split('-')[-1]) + 1 if last else 1
    return f'{prefix}{seq:03d}'


@login_required
def kerusakan_list(request):
    qs = LaporanKerusakan.objects.select_related('aset', 'pelapor', 'ditangani_oleh').order_by('-tanggal_lapor')
    status_filter = request.GET.get('status', '').strip()
    keparahan_filter = request.GET.get('keparahan', '').strip()

    if status_filter in dict(LaporanKerusakan.STATUS_CHOICES):
        qs = qs.filter(status=status_filter)
    if keparahan_filter in dict(LaporanKerusakan.KEPARAHAN_CHOICES):
        qs = qs.filter(tingkat_keparahan=keparahan_filter)

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    query_params = request.GET.copy()
    query_params.pop('page', None)

    return render(request, 'inventaris/kerusakan/list.html', {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'keparahan_filter': keparahan_filter,
        'status_choices': LaporanKerusakan.STATUS_CHOICES,
        'keparahan_choices': LaporanKerusakan.KEPARAHAN_CHOICES,
        'query_string': query_params.urlencode(),
    })


@login_required
def kerusakan_lapor(request):
    initial = {}
    aset_id = request.GET.get('aset')
    if aset_id and aset_id.isdigit():
        if Aset.objects.filter(pk=int(aset_id)).exists():
            initial['aset'] = int(aset_id)

    form = LaporanKerusakanForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            laporan = form.save(commit=False)
            laporan.pelapor = request.user
            laporan.status = 'DILAPORKAN'
            laporan.kode_laporan = _generate_kode_laporan()
            laporan.save()

            aset = Aset.objects.select_for_update().get(pk=laporan.aset_id)
            if laporan.tingkat_keparahan == 'BERAT':
                aset.kondisi = 'RUSAK_BERAT'
                aset.save(update_fields=['kondisi', 'updated_at'])
            elif aset.kondisi == 'BAIK':
                aset.kondisi = 'RUSAK_RINGAN'
                aset.save(update_fields=['kondisi', 'updated_at'])

        messages.success(request, f'Laporan kerusakan {laporan.kode_laporan} berhasil dicatat.')
        return redirect('kerusakan_detail', pk=laporan.pk)

    return render(request, 'inventaris/kerusakan/lapor.html', {'form': form})


@login_required
def kerusakan_detail(request, pk):
    laporan = get_object_or_404(
        LaporanKerusakan.objects.select_related('aset', 'aset__lokasi', 'pelapor', 'ditangani_oleh'),
        pk=pk,
    )
    profile = getattr(request.user, 'profile', None)
    can_manage = request.user.is_superuser or (profile and profile.role in ('ADMIN', 'TEKNISI'))

    form = PenangananKerusakanForm(request.POST or None, instance=laporan)
    if request.method == 'POST':
        if not can_manage:
            messages.error(request, 'Anda tidak memiliki hak akses untuk memperbarui penanganan kerusakan.')
            return redirect('kerusakan_detail', pk=laporan.pk)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.ditangani_oleh = request.user
            updated.save()
            messages.success(request, f'Status penanganan {laporan.kode_laporan} berhasil diperbarui.')
            return redirect('kerusakan_detail', pk=laporan.pk)

    jadwal_terkait = laporan.pemeliharaans.select_related('teknisi').order_by('-tanggal_jadwal')
    return render(request, 'inventaris/kerusakan/detail.html', {
        'laporan': laporan,
        'form': form,
        'can_manage': can_manage,
        'jadwal_terkait': jadwal_terkait,
    })


# ---------------------------------------------------------------------------
# Jadwal Pemeliharaan Aset
# ---------------------------------------------------------------------------

@login_required
def pemeliharaan_list(request):
    today = timezone.localdate()
    qs = JadwalPemeliharaan.objects.select_related('aset', 'teknisi', 'laporan_kerusakan').order_by('tanggal_jadwal')

    status_filter = request.GET.get('status', '').strip()
    jenis_filter = request.GET.get('jenis', '').strip()

    if status_filter in dict(JadwalPemeliharaan.STATUS_CHOICES):
        qs = qs.filter(status=status_filter)
    if jenis_filter in dict(JadwalPemeliharaan.JENIS_CHOICES):
        qs = qs.filter(jenis=jenis_filter)

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    rows = []
    for j in page_obj:
        selisih = (j.tanggal_jadwal - today).days
        is_active = j.status in ('TERJADWAL', 'BERLANGSUNG')
        rows.append({
            'obj': j,
            'selisih_hari': selisih,
            'abs_hari': abs(selisih),
            'is_overdue': is_active and selisih < 0,
            'is_due_soon': is_active and 0 <= selisih <= 7,
        })

    query_params = request.GET.copy()
    query_params.pop('page', None)

    return render(request, 'inventaris/pemeliharaan/list.html', {
        'page_obj': page_obj,
        'rows': rows,
        'status_filter': status_filter,
        'jenis_filter': jenis_filter,
        'status_choices': JadwalPemeliharaan.STATUS_CHOICES,
        'jenis_choices': JadwalPemeliharaan.JENIS_CHOICES,
        'query_string': query_params.urlencode(),
    })


@role_required('ADMIN', 'TEKNISI')
def pemeliharaan_create(request):
    initial = {}
    aset_id = request.GET.get('aset')
    laporan_id = request.GET.get('laporan')
    jenis = request.GET.get('jenis')
    if aset_id and aset_id.isdigit() and Aset.objects.filter(pk=int(aset_id)).exists():
        initial['aset'] = int(aset_id)
    if laporan_id and laporan_id.isdigit() and LaporanKerusakan.objects.filter(pk=int(laporan_id)).exists():
        initial['laporan_kerusakan'] = int(laporan_id)
    if jenis in dict(JadwalPemeliharaan.JENIS_CHOICES):
        initial['jenis'] = jenis

    form = JadwalPemeliharaanForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        jadwal = form.save(commit=False)
        jadwal.kode_jadwal = _generate_kode_jadwal()
        jadwal.status = 'TERJADWAL'
        jadwal.save()
        messages.success(request, f'Jadwal pemeliharaan {jadwal.kode_jadwal} berhasil dibuat.')
        return redirect('pemeliharaan_list')

    return render(request, 'inventaris/pemeliharaan/form.html', {
        'form': form,
        'page_title': 'Tambah Jadwal Pemeliharaan',
    })


@role_required('ADMIN', 'TEKNISI')
def pemeliharaan_edit(request, pk):
    jadwal = get_object_or_404(JadwalPemeliharaan, pk=pk)
    form = JadwalPemeliharaanForm(request.POST or None, instance=jadwal)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Jadwal {jadwal.kode_jadwal} berhasil diperbarui.')
        return redirect('pemeliharaan_list')

    return render(request, 'inventaris/pemeliharaan/form.html', {
        'form': form,
        'jadwal': jadwal,
        'page_title': f'Edit Jadwal: {jadwal.kode_jadwal}',
    })


@require_POST
@role_required('ADMIN', 'TEKNISI')
def pemeliharaan_mulai(request, pk):
    with transaction.atomic():
        jadwal = get_object_or_404(JadwalPemeliharaan.objects.select_for_update(), pk=pk)
        if jadwal.status != 'TERJADWAL':
            messages.error(request, f'Jadwal {jadwal.kode_jadwal} tidak berstatus Terjadwal.')
            return redirect('pemeliharaan_list')

        jadwal.status = 'BERLANGSUNG'
        jadwal.save(update_fields=['status', 'updated_at'])

        aset = Aset.objects.select_for_update().get(pk=jadwal.aset_id)
        aset.status = 'PEMELIHARAAN'
        aset.kondisi = 'PERBAIKAN'
        aset.save(update_fields=['status', 'kondisi', 'updated_at'])

    messages.success(request, f'Pemeliharaan {jadwal.kode_jadwal} dimulai. Status aset kini Pemeliharaan.')
    return redirect('pemeliharaan_list')


@role_required('ADMIN', 'TEKNISI')
def pemeliharaan_selesai(request, pk):
    jadwal = get_object_or_404(JadwalPemeliharaan.objects.select_related('aset', 'laporan_kerusakan'), pk=pk)
    if jadwal.status not in ('TERJADWAL', 'BERLANGSUNG'):
        messages.error(request, f'Jadwal {jadwal.kode_jadwal} sudah selesai atau dibatalkan.')
        return redirect('pemeliharaan_list')

    form = SelesaiPemeliharaanForm(
        request.POST or None,
        initial={'biaya': jadwal.biaya, 'tanggal_selesai': timezone.localdate()},
    )
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            locked = JadwalPemeliharaan.objects.select_for_update().get(pk=pk)
            aset = Aset.objects.select_for_update().get(pk=locked.aset_id)

            locked.tanggal_selesai = form.cleaned_data['tanggal_selesai']
            locked.biaya = form.cleaned_data['biaya']
            locked.catatan_hasil = form.cleaned_data['catatan_hasil']
            locked.status = 'SELESAI'
            locked.save()

            aset.kondisi = form.cleaned_data['kondisi_akhir']
            if aset.status != 'DIHAPUSKAN':
                aset.status = 'TERSEDIA'
            aset.save(update_fields=['kondisi', 'status', 'updated_at'])

            if locked.laporan_kerusakan_id:
                laporan = LaporanKerusakan.objects.select_for_update().get(pk=locked.laporan_kerusakan_id)
                laporan.status = 'SELESAI'
                if not laporan.ditangani_oleh_id:
                    laporan.ditangani_oleh = request.user
                laporan.save(update_fields=['status', 'ditangani_oleh', 'updated_at'])

        messages.success(request, f'Pemeliharaan {jadwal.kode_jadwal} selesai. Kondisi & status aset diperbarui.')
        return redirect('pemeliharaan_list')

    return render(request, 'inventaris/pemeliharaan/selesai.html', {
        'jadwal': jadwal,
        'form': form,
    })


# ---------------------------------------------------------------------------
# Laporan Kondisi & Penyusutan Aset
# ---------------------------------------------------------------------------

def _get_laporan_data(request):
    qs = Aset.objects.select_related('kategori', 'lokasi').order_by('kode_aset')

    kategori_id = request.GET.get('kategori', '').strip()
    lokasi_id = request.GET.get('lokasi', '').strip()
    kondisi = request.GET.get('kondisi', '').strip()
    tahun = request.GET.get('tahun', '').strip()

    if kategori_id.isdigit():
        qs = qs.filter(kategori_id=int(kategori_id))
    if lokasi_id.isdigit():
        qs = qs.filter(lokasi_id=int(lokasi_id))
    if kondisi in dict(Aset.KONDISI_CHOICES):
        qs = qs.filter(kondisi=kondisi)
    if tahun.isdigit():
        qs = qs.filter(tanggal_perolehan__year=int(tahun))

    asets = list(qs)
    today = timezone.localdate()

    rows = []
    total_perolehan = Decimal('0')
    total_akumulasi = Decimal('0')
    total_nilai_buku = Decimal('0')

    for aset in asets:
        metrik = hitung_penyusutan(aset, tanggal_acuan=today)
        total_perolehan += aset.harga_perolehan
        total_akumulasi += metrik['akumulasi_penyusutan']
        total_nilai_buku += metrik['nilai_buku']
        rows.append({
            'aset': aset,
            'usia_tahun': metrik['usia_tahun'],
            'penyusutan_per_tahun': metrik['penyusutan_per_tahun'],
            'akumulasi_penyusutan': metrik['akumulasi_penyusutan'],
            'nilai_buku': metrik['nilai_buku'],
            'persentase_susut': min(100, float(metrik['persentase_susut'])),
        })

    biaya_per_kategori = (
        JadwalPemeliharaan.objects.filter(status='SELESAI', aset__in=asets)
        .values('aset__kategori__nama')
        .annotate(total_biaya=Sum('biaya'), jumlah_kegiatan=Count('id'))
        .order_by('aset__kategori__nama')
    )
    total_biaya_pemeliharaan = sum((b['total_biaya'] or Decimal('0')) for b in biaya_per_kategori)

    query_params = request.GET.copy()
    query_params.pop('export', None)

    return {
        'rows': rows,
        'total_unit': len(rows),
        'total_perolehan': total_perolehan,
        'total_akumulasi': total_akumulasi,
        'total_nilai_buku': total_nilai_buku,
        'biaya_per_kategori': biaya_per_kategori,
        'total_biaya_pemeliharaan': total_biaya_pemeliharaan,
        'kategoris': KategoriAset.objects.order_by('nama'),
        'lokasis': LokasiLab.objects.order_by('nama_ruang'),
        'kondisi_choices': Aset.KONDISI_CHOICES,
        'tahun_choices': [d.year for d in Aset.objects.dates('tanggal_perolehan', 'year', order='DESC')],
        'filters': {
            'kategori': kategori_id,
            'lokasi': lokasi_id,
            'kondisi': kondisi,
            'tahun': tahun,
        },
        'query_string': query_params.urlencode(),
        'tanggal_cetak': timezone.localtime(),
    }


@role_required('ADMIN', 'TEKNISI')
def laporan_penyusutan(request):
    data = _get_laporan_data(request)

    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = 'attachment; filename="laporan_inventaris_penyusutan.csv"'
        response.write('\ufeff')

        writer = csv.writer(response)
        writer.writerow([
            'Kode Aset',
            'Nama Aset',
            'Kategori',
            'Lokasi',
            'Tanggal Perolehan',
            'Usia (Tahun)',
            'Umur Ekonomis (Tahun)',
            'Harga Perolehan (Rp)',
            'Nilai Residu (Rp)',
            'Penyusutan/Tahun (Rp)',
            'Akumulasi Penyusutan (Rp)',
            'Persentase Susut (%)',
            'Nilai Buku (Rp)',
            'Kondisi',
            'Status',
        ])
        for r in data['rows']:
            a = r['aset']
            writer.writerow([
                a.kode_aset,
                a.nama_aset,
                a.kategori.nama,
                a.lokasi.nama_ruang,
                a.tanggal_perolehan.isoformat(),
                r['usia_tahun'],
                a.umur_ekonomis_tahun,
                a.harga_perolehan,
                a.nilai_residu,
                r['penyusutan_per_tahun'],
                r['akumulasi_penyusutan'],
                r['persentase_susut'],
                r['nilai_buku'],
                a.get_kondisi_display(),
                a.get_status_display(),
            ])
        return response

    return render(request, 'inventaris/laporan/penyusutan.html', data)


@role_required('ADMIN', 'TEKNISI')
def laporan_cetak(request):
    data = _get_laporan_data(request)
    return render(request, 'inventaris/laporan/cetak.html', data)
