import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .context_processors import user_context
from .decorators import role_required
from .models import Aset, JadwalPemeliharaan, KategoriAset, LaporanKerusakan, LokasiLab, Peminjaman, UserProfile
from .templatetags.inventaris_tags import badge_kondisi, badge_status, rupiah


@role_required('ADMIN')
def _admin_only_view(request):
    return HttpResponse('ok-admin')


class AuthAndRBACTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('admin_lab', 'admin@unhas.ac.id', 'AdminLab123!', first_name='Admin')
        UserProfile.objects.create(
            user=self.admin, role='ADMIN', nomor_identitas='NIP-001', unit_prodi='Lab Terpadu'
        )
        self.teknisi = User.objects.create_user('teknisi_lab', 'teknisi@unhas.ac.id', 'TeknisiLab123!')
        UserProfile.objects.create(
            user=self.teknisi, role='TEKNISI', nomor_identitas='NIP-002', unit_prodi='Lab Terpadu'
        )
        self.peminjam = User.objects.create_user('mhs_andi', 'andi@unhas.ac.id', 'Peminjam123!')
        UserProfile.objects.create(
            user=self.peminjam, role='PEMINJAM', nomor_identitas='H071221001', unit_prodi='Sistem Informasi'
        )
        self.superuser = User.objects.create_superuser('root_lab', 'root@unhas.ac.id', 'RootLab123!')

    def test_dashboard_redirects_anonymous_to_login(self):
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

    def test_login_succeeds_for_all_roles(self):
        credentials = [
            ('admin_lab', 'AdminLab123!', 'ADMIN'),
            ('teknisi_lab', 'TeknisiLab123!', 'TEKNISI'),
            ('mhs_andi', 'Peminjam123!', 'PEMINJAM'),
        ]
        for username, password, expected_role in credentials:
            with self.subTest(username=username):
                response = self.client.post(reverse('login'), {'username': username, 'password': password})
                self.assertRedirects(response, reverse('dashboard'))
                dash = self.client.get(reverse('dashboard'))
                self.assertEqual(dash.status_code, 200)
                self.assertEqual(dash.context['user_role'], expected_role)
                self.assertIsNotNone(dash.context['user_profile'])
                self.client.logout()

    def test_login_wrong_password_shows_indonesian_error(self):
        response = self.client.post(reverse('login'), {'username': 'admin_lab', 'password': 'SalahPassword!'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Username atau password salah')
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_login_empty_fields_shows_inline_errors(self):
        response = self.client.post(reverse('login'), {'username': '', 'password': ''})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Username wajib diisi.')
        self.assertContains(response, 'Password wajib diisi.')

    def test_authenticated_user_redirected_from_login(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('login'))
        self.assertRedirects(response, reverse('dashboard'))

    def test_login_blocks_external_next_redirect(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'admin_lab', 'password': 'AdminLab123!', 'next': 'https://evil.example.com/phish'},
        )
        self.assertRedirects(response, reverse('dashboard'))

    def test_logout_requires_post_and_sets_success_message(self):
        self.client.force_login(self.admin)
        get_resp = self.client.get(reverse('logout'))
        self.assertEqual(get_resp.status_code, 405)

        post_resp = self.client.post(reverse('logout'), follow=True)
        self.assertRedirects(post_resp, reverse('login'))
        self.assertFalse(post_resp.wsgi_request.user.is_authenticated)
        msgs = [m.message for m in get_messages(post_resp.wsgi_request)]
        self.assertTrue(any('berhasil keluar' in m for m in msgs))

    def test_role_required_allows_matching_role_and_superuser_and_blocks_others(self):
        factory = RequestFactory()

        for user, expected_status in [
            (self.admin, 200),
            (self.superuser, 200),
            (self.peminjam, 302),
        ]:
            with self.subTest(user=user.username):
                req = factory.get('/admin-only/')
                req.user = user
                req.session = self.client.session
                req._messages = FallbackStorage(req)
                resp = _admin_only_view(req)
                self.assertEqual(resp.status_code, expected_status)
                if expected_status == 302:
                    self.assertEqual(resp.url, reverse('dashboard'))
                    msgs = [m.message for m in get_messages(req)]
                    self.assertTrue(any('tidak memiliki hak akses' in m for m in msgs))

    def test_context_processor_handles_superuser_without_profile(self):
        factory = RequestFactory()
        req = factory.get('/')
        req.user = self.superuser
        ctx = user_context(req)
        self.assertEqual(ctx['user_role'], 'ADMIN')
        self.assertIsNone(ctx['user_profile'])


class LayoutAndDashboardTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('admin_lab', 'admin@example.com', 'AdminLab123!')
        UserProfile.objects.create(
            user=self.admin, role='ADMIN', nomor_identitas='NIP-001', unit_prodi='Lab Terpadu'
        )
        self.peminjam = User.objects.create_user('mhs_andi', 'andi@example.com', 'Peminjam123!')
        UserProfile.objects.create(
            user=self.peminjam, role='PEMINJAM', nomor_identitas='H071221001', unit_prodi='Sistem Informasi'
        )

        self.kategori = KategoriAset.objects.create(kode='KOM', nama='Komputer')
        self.lokasi = LokasiLab.objects.create(
            kode_ruang='LAB-01', nama_ruang='Lab Komputasi', gedung='Gedung A', penanggung_jawab='Admin'
        )
        today = timezone.localdate()
        self.aset1 = Aset.objects.create(
            nama_aset='PC Workstation 01',
            kategori=self.kategori,
            lokasi=self.lokasi,
            merk_tipe='Dell Precision',
            tanggal_perolehan=date(today.year, 1, 1),
            harga_perolehan=Decimal('12500000'),
            nilai_residu=Decimal('2500000'),
            umur_ekonomis_tahun=5,
            kondisi='BAIK',
            status='TERSEDIA',
        )
        self.aset2 = Aset.objects.create(
            nama_aset='Oscilloscope Digital',
            kategori=self.kategori,
            lokasi=self.lokasi,
            merk_tipe='Rigol DS1054Z',
            tanggal_perolehan=date(today.year, 1, 1),
            harga_perolehan=Decimal('6000000'),
            nilai_residu=Decimal('1000000'),
            umur_ekonomis_tahun=5,
            kondisi='RUSAK_RINGAN',
            status='DIPINJAM',
        )
        Peminjaman.objects.create(
            kode_peminjaman='PJM-001',
            aset=self.aset2,
            peminjam=self.peminjam,
            tanggal_pinjam=today,
            tanggal_rencana_kembali=today + timedelta(days=3),
            keperluan='Praktikum',
            status='MENUNGGU',
        )
        LaporanKerusakan.objects.create(
            kode_laporan='KRS-001',
            aset=self.aset2,
            pelapor=self.peminjam,
            judul_kerusakan='Probe longgar',
            deskripsi='Konektor probe channel 1 longgar',
            status='DILAPORKAN',
        )
        JadwalPemeliharaan.objects.create(
            kode_jadwal='JDL-001',
            aset=self.aset1,
            jenis='PREVENTIF',
            tanggal_jadwal=today + timedelta(days=5),
            deskripsi_kegiatan='Pembersihan rutin',
            status='TERJADWAL',
        )

    def test_template_filters(self):
        self.assertEqual(rupiah(Decimal('12500000')), 'Rp 12.500.000')
        self.assertEqual(rupiah(None), 'Rp 0')
        self.assertEqual(rupiah(-5000), '-Rp 5.000')
        self.assertIn('emerald', badge_kondisi('BAIK'))
        self.assertIn('amber', badge_kondisi('RUSAK_RINGAN'))
        self.assertIn('red', badge_status('DITOLAK'))

    def test_dashboard_renders_kpis_charts_and_sidebar_by_role(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_aset'], 2)
        self.assertEqual(resp.context['aset_tersedia'], 1)
        self.assertEqual(resp.context['aset_dipinjam'], 1)
        self.assertEqual(resp.context['kerusakan_aktif'], 1)
        self.assertEqual(resp.context['pemeliharaan_mendatang'], 1)
        self.assertContains(resp, 'id="kondisi-chart-data"')
        self.assertContains(resp, 'id="kategori-chart-data"')
        self.assertContains(resp, 'Kategori Barang')
        self.assertContains(resp, 'PJM-001')
        self.assertContains(resp, 'JDL-001')

        # Non-admin tidak melihat menu Master Data dan diblokir dari /kategori/
        self.client.force_login(self.peminjam)
        resp_user = self.client.get(reverse('dashboard'))
        self.assertEqual(resp_user.status_code, 200)
        self.assertNotContains(resp_user, 'Kategori Barang')
        blocked = self.client.get(reverse('kategori_list'))
        self.assertRedirects(blocked, reverse('dashboard'))

    def test_sidebar_placeholder_routes_accessible(self):
        self.client.force_login(self.admin)
        for name in ['aset_list', 'peminjaman_list', 'kerusakan_list', 'pemeliharaan_list', 'laporan_penyusutan', 'kategori_list', 'lokasi_list']:
            with self.subTest(url_name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)


class MasterAsetAndQRTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('admin_lab', 'admin@example.com', 'AdminLab123!')
        UserProfile.objects.create(
            user=self.admin, role='ADMIN', nomor_identitas='NIP-001', unit_prodi='Lab Terpadu'
        )
        self.peminjam = User.objects.create_user('mhs_andi', 'andi@example.com', 'Peminjam123!')
        UserProfile.objects.create(
            user=self.peminjam, role='PEMINJAM', nomor_identitas='H071221001', unit_prodi='Sistem Informasi'
        )
        self.kategori = KategoriAset.objects.create(kode='KOM', nama='Komputer')
        self.lokasi = LokasiLab.objects.create(
            kode_ruang='LAB-RPL', nama_ruang='Lab RPL', gedung='Gedung A', penanggung_jawab='Admin'
        )
        self.aset = Aset.objects.create(
            nama_aset='Workstation 01',
            kategori=self.kategori,
            lokasi=self.lokasi,
            merk_tipe='Dell Precision',
            tanggal_perolehan=date(2025, 1, 10),
            harga_perolehan=Decimal('15000000'),
            nilai_residu=Decimal('3000000'),
            umur_ekonomis_tahun=5,
        )

    def test_kategori_and_lokasi_crud_and_protected_error(self):
        self.client.force_login(self.admin)

        # Tambah kategori baru
        resp = self.client.post(reverse('kategori_create'), {
            'kode': 'jar',
            'nama': 'Jaringan',
            'deskripsi': 'Switch dan router',
        })
        self.assertRedirects(resp, reverse('kategori_list'))
        jar = KategoriAset.objects.get(kode='JAR')
        self.assertEqual(jar.nama, 'Jaringan')

        # Hapus kategori yang tidak terpakai berhasil
        del_ok = self.client.post(reverse('kategori_delete', args=[jar.pk]))
        self.assertRedirects(del_ok, reverse('kategori_list'))
        self.assertFalse(KategoriAset.objects.filter(pk=jar.pk).exists())

        # Hapus kategori & lokasi yang masih dipakai aset tertahan ProtectedError
        del_kat = self.client.post(reverse('kategori_delete', args=[self.kategori.pk]), follow=True)
        self.assertRedirects(del_kat, reverse('kategori_list'))
        self.assertTrue(KategoriAset.objects.filter(pk=self.kategori.pk).exists())
        self.assertContains(del_kat, 'tidak dapat dihapus')

        del_lok = self.client.post(reverse('lokasi_delete', args=[self.lokasi.pk]), follow=True)
        self.assertRedirects(del_lok, reverse('lokasi_list'))
        self.assertTrue(LokasiLab.objects.filter(pk=self.lokasi.pk).exists())
        self.assertContains(del_lok, 'tidak dapat dihapus')

    def test_create_aset_generates_kode_and_qr_and_detail_scan_print(self):
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(MEDIA_ROOT=tmpdir):
            self.client.force_login(self.admin)
            resp = self.client.post(reverse('aset_create'), {
                'kode_aset': '',
                'nama_aset': 'Proyektor Laser',
                'kategori': self.kategori.pk,
                'lokasi': self.lokasi.pk,
                'merk_tipe': 'Epson EB-L200',
                'nomor_seri': 'SN-9988',
                'spesifikasi': '4200 Lumens',
                'tanggal_perolehan': '2026-01-15',
                'harga_perolehan': '10000000',
                'nilai_residu': '1000000',
                'umur_ekonomis_tahun': '5',
                'kondisi': 'BAIK',
                'status': 'TERSEDIA',
                'catatan': '',
            })
            created = Aset.objects.get(nama_aset='Proyektor Laser')
            self.assertRedirects(resp, reverse('aset_detail', args=[created.pk]))
            self.assertTrue(created.kode_aset.startswith('LAB-KOM-2026-'))
            self.assertTrue(bool(created.qr_code))
            self.assertTrue(created.qr_code.name.endswith(f'{created.kode_aset}.png'))

            detail_resp = self.client.get(reverse('aset_detail', args=[created.pk]))
            self.assertEqual(detail_resp.status_code, 200)
            self.assertContains(detail_resp, created.kode_aset)
            self.assertContains(detail_resp, 'Unduh PNG')

            scan_resp = self.client.get(reverse('aset_scan', args=[created.kode_aset]))
            self.assertEqual(scan_resp.status_code, 200)
            self.assertContains(scan_resp, 'Ajukan Pinjam')

            print_resp = self.client.get(reverse('aset_print_qr', args=[created.pk]))
            self.assertEqual(print_resp.status_code, 200)
            self.assertContains(print_resp, created.kode_aset)

            massal_resp = self.client.get(reverse('aset_print_qr_massal'))
            self.assertEqual(massal_resp.status_code, 200)
            self.assertContains(massal_resp, self.aset.kode_aset)

    def test_aset_search_filter_and_role_restriction(self):
        self.client.force_login(self.peminjam)
        list_resp = self.client.get(reverse('aset_list'), {'q': 'Workstation', 'kondisi': 'BAIK'})
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, self.aset.kode_aset)
        self.assertNotContains(list_resp, 'Tambah Aset')

        # Peminjam tidak boleh membuat aset
        blocked = self.client.get(reverse('aset_create'))
        self.assertRedirects(blocked, reverse('dashboard'))
