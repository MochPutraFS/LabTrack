from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .context_processors import user_context
from .decorators import role_required
from .models import UserProfile


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
